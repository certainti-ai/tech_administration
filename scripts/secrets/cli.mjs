import { execFileSync } from "node:child_process";
import path from "node:path";

/** Minimal flag parser: `--flag`, `--key value`, `--key=value`, repeatable keys. */
export function parseArgs(argv) {
  const flags = {};
  const positional = [];

  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) {
      positional.push(token);
      continue;
    }

    const body = token.slice(2);
    const eq = body.indexOf("=");
    let key;
    let value;

    if (eq !== -1) {
      key = body.slice(0, eq);
      value = body.slice(eq + 1);
    } else {
      key = body;
      const next = argv[i + 1];
      if (next !== undefined && !next.startsWith("--")) {
        value = next;
        i += 1;
      } else {
        value = true;
      }
    }

    if (key in flags) {
      flags[key] = [...[flags[key]].flat(), value];
    } else {
      flags[key] = value;
    }
  }

  return { flags, positional };
}

export function asList(value) {
  if (value === undefined) return null;
  return [value].flat().flatMap((item) => String(item).split(","));
}

/**
 * Refuse to write secret material somewhere git would pick it up.
 *
 * A `.env` file that is not ignored is one `git add -A` away from being
 * committed, so this is a hard stop rather than a warning.
 */
export function assertSafeOutputPath(target) {
  const resolved = path.resolve(target);

  let insideRepo = true;
  try {
    execFileSync("git", ["rev-parse", "--is-inside-work-tree"], {
      cwd: path.dirname(resolved),
      stdio: "pipe",
    });
  } catch {
    insideRepo = false;
  }

  if (!insideRepo) return resolved;

  try {
    execFileSync("git", ["check-ignore", "-q", resolved], {
      cwd: path.dirname(resolved),
      stdio: "pipe",
    });
    return resolved;
  } catch {
    throw new Error(
      [
        `Refusing to write secrets to ${resolved}`,
        "",
        "That path is inside a git working tree and is not ignored, so the file",
        "could be committed. Add it to .gitignore, or write outside the repo.",
      ].join("\n"),
    );
  }
}

export function fail(message) {
  process.exitCode = 1;
  console.error(message);
}

/** Pad for aligned console tables. */
export function pad(value, width) {
  const text = String(value);
  return text.length >= width ? text : text + " ".repeat(width - text.length);
}
