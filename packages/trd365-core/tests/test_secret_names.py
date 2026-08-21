"""
That the loader script writes the names the resolver reads.

``scripts/secrets/set-environment.sh`` derives its list of Key Vault secret
names from :mod:`trd365_core.environments`, so in principle they cannot
disagree. In practice "derives from" is a shell script calling a Python snippet
and reformatting the answer, and every step of that is somewhere a name can
acquire an underscore it should not have.

The consequence of a mismatch is specific and nasty: a name that is close but
wrong does not error anywhere. :func:`describe` falls back to the placeholder for
that field, :func:`connection_settings` then refuses to connect, and the message
names a credential whoever ran the script is certain they supplied.

So the script is actually run, in dry-run mode, against a filled-in copy of its
own template, and the names it reports are compared with a set computed here
straight from :func:`describe`. Two independent routes to the same answer, rather
than a restatement of one of them.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from trd365_core.environments import DB_KEYS, PLACEHOLDER, Environment, describe

REPO_ROOT = Path(__file__).resolve().parents[3]
LOADER = REPO_ROOT / "scripts" / "secrets" / "set-environment.sh"
TEMPLATE = REPO_ROOT / "scripts" / "secrets" / "environment.env.example"

pytestmark = pytest.mark.skipif(
    not LOADER.exists() or shutil.which("bash") is None,
    reason="needs the repo checkout and bash",
)

#: Every field the template offers, filled with something recognisable. Values do
#: not matter — only which names come back — but they must be non-empty, because
#: an empty value is exactly how the script is told a field was not supplied.
FILLED = {
    "MAINDB_DBNAME": "main_db",
    "MAINDB_PASSWORD": "main-pw",
    "ORGDB_DBNAME": "org_db",
    "ORGDB_PASSWORD": "org-pw",
    "MAINDB_SSH_PASSWORD": "ssh-pw",
    "ORGDB_SSH_PASSWORD": "ssh-pw",
    "TRD365AI_DBNAME": "ai_db",
    "TRD365AI_PASSWORD": "ai-pw",
}


def names_the_resolver_would_need(env: Environment) -> set[str]:
    """
    The secrets that must exist for ``env`` to be usable, named as the vault
    names them.

    Computed from the code's own topology: a database whose server is unknown
    cannot be configured from a vault at all, a known ``dbname`` needs no secret,
    and a tunnel adds exactly one password.
    """
    wanted: set[str] = set()
    for db_key in DB_KEYS:
        settings = describe(env, db_key, {})
        if PLACEHOLDER in settings.host:
            continue
        fields = ["password"]
        if settings.dbname == PLACEHOLDER:
            fields.append("dbname")
        if settings.ssh_tunnel is not None:
            fields.append("ssh-password")
        wanted |= {f"trd365-{env.value}-{db_key}-{field}" for field in fields}
    return wanted


def run_loader(env: Environment, tmp_path: Path) -> set[str]:
    """Run the script in dry-run mode and return the names it would write."""
    filled = tmp_path / f"{env.value}.env"
    lines = [
        f"{key}={FILLED[key]}"
        for line in TEMPLATE.read_text().splitlines()
        if (key := line.split("=", 1)[0].strip()) in FILLED
    ]
    assert len(lines) == len(FILLED), "the template no longer offers every field FILLED covers"
    filled.write_text("\n".join(lines) + "\n")

    result = subprocess.run(
        ["bash", str(LOADER), env.value, str(filled)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Dry run" in result.stdout, "the script must not write without --apply"
    return set(re.findall(r"^  (trd365-[a-z0-9-]+)\s", result.stdout, re.MULTILINE))


class TestTheScriptAndTheResolverAgree:
    @pytest.mark.parametrize("env", list(Environment))
    def test_the_names_written_are_exactly_the_names_needed(self, env, tmp_path):
        assert run_loader(env, tmp_path) == names_the_resolver_would_need(env)

    def test_dev_and_qa_need_no_bastion_password(self, tmp_path):
        for env in (Environment.DEV, Environment.QA):
            assert not any("ssh" in name for name in run_loader(env, tmp_path))

    def test_stage_needs_a_bastion_password_for_both_databases(self, tmp_path):
        names = run_loader(Environment.STAGE, tmp_path)
        assert "trd365-stage-maindb-ssh-password" in names
        assert "trd365-stage-orgdb-ssh-password" in names

    def test_nothing_is_asked_for_a_database_with_no_known_server(self, tmp_path):
        # trd365ai outside prod. Filling the template's fields for it should be
        # reported as ignored rather than written under a name nothing reads.
        for env in (Environment.DEV, Environment.QA, Environment.STAGE):
            assert not any("trd365ai" in name for name in run_loader(env, tmp_path))


class TestTheGuards:
    def test_a_missing_required_value_stops_the_run(self, tmp_path):
        filled = tmp_path / "qa.env"
        filled.write_text("MAINDB_DBNAME=main_db\nMAINDB_PASSWORD=pw\n")  # orgdb absent
        result = subprocess.run(
            ["bash", str(LOADER), "qa", str(filled)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "ORGDB_PASSWORD" in result.stdout
        assert "required field" in result.stderr

    def test_an_unknown_environment_is_refused(self, tmp_path):
        filled = tmp_path / "x.env"
        filled.write_text("MAINDB_PASSWORD=pw\n")
        result = subprocess.run(
            ["bash", str(LOADER), "production", str(filled)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "not one of dev, qa, stage, prod" in result.stderr

    def test_a_value_with_shell_metacharacters_survives_intact(self, tmp_path):
        # The file is parsed, not sourced. `$`, a quote and a space in a password
        # are ordinary; expanding or splitting any of them would store the wrong
        # secret and the failure would look like a wrong password.
        import hashlib

        password = "p$$w'rd with space`echo x`"
        filled = tmp_path / "qa.env"
        filled.write_text(
            "\n".join(
                [
                    "MAINDB_DBNAME=main_db",
                    f"MAINDB_PASSWORD={password}",
                    "ORGDB_DBNAME=org_db",
                    "ORGDB_PASSWORD=org-pw",
                ]
            )
            + "\n"
        )
        result = subprocess.run(
            ["bash", str(LOADER), "qa", str(filled)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        expected = hashlib.sha256(password.encode()).hexdigest()[:12]
        row = next(
            line for line in result.stdout.splitlines() if "trd365-qa-maindb-password" in line
        )
        assert expected in row

    def test_no_value_is_ever_printed(self, tmp_path):
        filled = tmp_path / "qa.env"
        filled.write_text(
            "MAINDB_DBNAME=main_db\nMAINDB_PASSWORD=hunter2\nORGDB_DBNAME=o\nORGDB_PASSWORD=swordfish\n"
        )
        result = subprocess.run(
            ["bash", str(LOADER), "qa", str(filled)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "hunter2" not in result.stdout + result.stderr
        assert "swordfish" not in result.stdout + result.stderr
