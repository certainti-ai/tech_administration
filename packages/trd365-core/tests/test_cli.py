"""The CLI safety conventions — the estate's headline bug, guarded."""

import pytest

from trd365_core import cli
from trd365_core.environments import Environment
from trd365_core.errors import UnsafeOperationError


def parse(args, **kwargs):
    parser = cli.build_parser("test utility", **kwargs)
    return cli.common_args(parser.parse_args(args))


class TestEnvironmentIsRequired:
    def test_omitting_env_is_an_error(self, capsys):
        parser = cli.build_parser("test utility")
        with pytest.raises(SystemExit):
            parser.parse_args([])
        assert "--env" in capsys.readouterr().err

    def test_an_invalid_environment_is_rejected(self):
        parser = cli.build_parser("test utility")
        with pytest.raises(SystemExit):
            parser.parse_args(["--env", "production"])

    def test_each_valid_environment_parses(self):
        for name in ("dev", "qa", "stage", "prod"):
            assert parse(["--env", name]).env is Environment.parse(name)


class TestApplyGating:
    def test_dry_run_is_the_default(self):
        args = parse(["--env", "prod"])
        assert args.apply is False
        assert args.dry_run is True
        assert args.mode == "DRY RUN"

    def test_apply_enables_writes(self):
        args = parse(["--env", "dev", "--apply"])
        assert args.apply is True
        assert args.dry_run is False
        assert args.mode == "APPLY"

    def test_read_only_utilities_do_not_offer_apply(self):
        parser = cli.build_parser("report", destructive=False)
        with pytest.raises(SystemExit):
            parser.parse_args(["--env", "prod", "--apply"])

    def test_read_only_utilities_still_report_dry_run(self):
        assert parse(["--env", "prod"], destructive=False).apply is False


class TestDryRunIsRejected:
    """
    Three legacy tools wrote by default and used --dry-run to preview. After
    the reversal, an operator typing --dry-run out of habit must not have it
    ignored while the tool deletes for real.
    """

    def test_dry_run_exits_rather_than_being_ignored(self):
        parser = cli.build_parser("test utility")
        with pytest.raises(SystemExit):
            parser.parse_args(["--env", "prod", "--dry-run"])

    def test_the_error_explains_the_change(self, capsys):
        parser = cli.build_parser("test utility")
        with pytest.raises(SystemExit):
            parser.parse_args(["--env", "prod", "--dry-run"])
        message = capsys.readouterr().err
        assert "--dry-run has been removed" in message
        assert "--apply" in message

    def test_dry_run_is_not_advertised_in_help(self, capsys):
        parser = cli.build_parser("test utility")
        with pytest.raises(SystemExit):
            parser.parse_args(["--help"])
        assert "--dry-run" not in capsys.readouterr().out


class TestProductionConfirmation:
    def test_no_prompt_for_a_dry_run(self):
        args = parse(["--env", "prod"])
        cli.confirm_production(args, "purge", input_fn=lambda _: pytest.fail("prompted"))

    def test_no_prompt_outside_production(self):
        args = parse(["--env", "stage", "--apply"])
        cli.confirm_production(args, "purge", input_fn=lambda _: pytest.fail("prompted"))

    def test_typing_the_environment_name_proceeds(self, capsys):
        args = parse(["--env", "prod", "--apply"])
        cli.confirm_production(args, "purge", input_fn=lambda _: "prod")
        assert "WRITE TO PRODUCTION" in capsys.readouterr().err

    def test_anything_else_aborts(self):
        args = parse(["--env", "prod", "--apply"])
        with pytest.raises(UnsafeOperationError, match="nothing was written"):
            cli.confirm_production(args, "purge", input_fn=lambda _: "yes")

    def test_assume_yes_skips_the_prompt_for_non_interactive_callers(self):
        args = parse(["--env", "prod", "--apply"])
        cli.confirm_production(
            args, "purge", assume_yes=True, input_fn=lambda _: pytest.fail("prompted")
        )


class TestBanner:
    def test_dry_run_banner_says_nothing_will_be_written(self):
        banner = cli.describe_mode(parse(["--env", "prod"]), "purge-account")
        assert "env=prod" in banner
        assert "DRY RUN" in banner
        assert "no changes will be written" in banner

    def test_apply_banner_is_unambiguous(self):
        banner = cli.describe_mode(parse(["--env", "dev", "--apply"]), "purge-account")
        assert "APPLY" in banner
        assert "no changes" not in banner
