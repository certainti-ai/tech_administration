#!/usr/bin/env python3
"""
Static checks for infra/terraform, for when `terraform validate` cannot run.

`validate` needs `init`, `init` needs the provider registry, and the registry is
blocked from Claude Code sessions (see docs/HANDOFF.md §10). These are the checks
that catch the mistakes actually made here: a variable referenced but never
declared, a local left behind after a refactor, a resource indexed `[0]` without
a `count`, and — the one that bites hardest — a `${...}` in the cloud-init
template that `templatefile()` never supplies, which fails at apply time after
resources have already been created.

    python tools/check_terraform.py [dir]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TEMPLATEFILE = re.compile(r"templatefile\(\s*\"[^\"]+\"\s*,\s*\{(.*?)\n\s*\}\)", re.S)


def locals_bodies(blob: str) -> list[str]:
    """
    Every ``locals { ... }`` body, found by matching braces.

    A regex anchored on a closing brace in column zero misses a single-line
    block, and then reports every local it defines as undefined — a false alarm
    that teaches people to ignore the checker.
    """
    bodies: list[str] = []
    for match in re.finditer(r"\blocals\s*\{", blob):
        depth, start = 1, match.end()
        index = start
        while index < len(blob) and depth:
            if blob[index] == "{":
                depth += 1
            elif blob[index] == "}":
                depth -= 1
            index += 1
        bodies.append(blob[start : index - 1])
    return bodies


def top_level_assignments(body: str) -> set[str]:
    """
    Names assigned at the top level of a block.

    Depth-aware on purpose: a nested object's keys are not locals, and counting
    them would mask a local that really is unused.
    """
    names: set[str] = set()
    depth = 0
    # A single-line block writes several assignments on one line; splitting on
    # commas as well as newlines covers both spellings.
    for line in re.split(r"[\n,]", body):
        stripped = line.strip()
        if depth == 0:
            match = re.match(r"([A-Za-z0-9_]+)\s*=", stripped)
            if match:
                names.add(match.group(1))
        depth += line.count("{") + line.count("[") - line.count("}") - line.count("]")
    return names


def check(directory: Path) -> list[str]:
    files = sorted(directory.glob("*.tf"))
    if not files:
        return [f"no .tf files in {directory}"]
    blob = "\n".join(p.read_text() for p in files)
    problems: list[str] = []

    declared = set(re.findall(r'^variable\s+"([^"]+)"', blob, re.M))
    used = set(re.findall(r"\bvar\.([A-Za-z0-9_]+)", blob))
    problems += [f"var.{n} is used but never declared" for n in sorted(used - declared)]
    problems += [f"variable {n!r} is declared but never used" for n in sorted(declared - used)]

    defined_locals: set[str] = set()
    for body in locals_bodies(blob):
        defined_locals |= top_level_assignments(body)
    used_locals = set(re.findall(r"\blocal\.([A-Za-z0-9_]+)", blob))
    problems += [f"local.{n} is used but never defined" for n in sorted(used_locals - defined_locals)]
    problems += [
        f"local {n!r} is defined but never used" for n in sorted(defined_locals - used_locals)
    ]

    for kind, name in sorted(set(re.findall(r'^resource\s+"([^"]+)"\s+"([^"]+)"', blob, re.M))):
        body = re.search(
            rf'resource\s+"{re.escape(kind)}"\s+"{re.escape(name)}"\s*\{{(.*?)^\}}',
            blob,
            re.M | re.S,
        )
        indexed = f"{kind}.{name}[0]" in blob
        has_count = bool(body and re.search(r"^\s*count\s*=", body.group(1), re.M))
        if indexed and not has_count:
            problems += [f"{kind}.{name} is indexed [0] but declares no count"]

    for template in sorted(directory.glob("*.tftpl")):
        needed = set(re.findall(r"\$\{([a-z_][a-z0-9_]*)\}", template.read_text()))
        match = TEMPLATEFILE.search(blob)
        if match is None:
            problems += [f"{template.name} exists but no templatefile() call was found"]
            continue
        supplied = set(re.findall(r"^\s*([a-z_][a-z0-9_]*)\s*=", match.group(1), re.M))
        problems += [
            f"{template.name} needs ${{{n}}} but templatefile() does not supply it"
            for n in sorted(needed - supplied)
        ]
        problems += [
            f"templatefile() supplies {n!r} but {template.name} never uses it"
            for n in sorted(supplied - needed)
        ]

    return problems


def main(argv: list[str]) -> int:
    directory = Path(argv[1]) if len(argv) > 1 else Path("infra/terraform")
    problems = check(directory)
    if problems:
        print("\n".join(f"  {p}" for p in problems))
        print(f"\n{len(problems)} problem(s) in {directory}")
        return 1
    print(f"{directory}: references, locals and template inputs all resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
