import { describe, expect, it } from "vitest";
import {
  isValidVaultName,
  roundTrips,
  toVaultName,
} from "../scripts/secrets/naming.mjs";
import {
  entries,
  findByEnv,
  groups,
  selectEntries,
  validateManifest,
} from "../scripts/secrets/manifest.mjs";
import {
  applyPush,
  compareWithEnv,
  digest,
  dotenvQuote,
  fetchAll,
  planPush,
  renderDotenv,
  renderShell,
  shellQuote,
} from "../scripts/secrets/sync.mjs";
import { resolveVaultName, vaultUrl } from "../scripts/secrets/client.mjs";

/** In-memory stand-in for Azure's SecretClient. */
function fakeVault(initial = {}) {
  const store = new Map(Object.entries(initial));
  return {
    store,
    async setSecret(name, value) {
      store.set(name, value);
      return { name, value };
    },
    async getSecret(name) {
      if (!store.has(name)) {
        const error = new Error(`Secret not found: ${name}`);
        error.statusCode = 404;
        throw error;
      }
      return { name, value: store.get(name) };
    },
  };
}

describe("toVaultName", () => {
  it("lowercases and swaps underscores for hyphens", () => {
    expect(toVaultName("MAINDB_SSH_PASSWORD")).toBe("maindb-ssh-password");
  });

  it("rejects names that are not environment variables", () => {
    expect(() => toVaultName("has spaces")).toThrow(TypeError);
    expect(() => toVaultName("")).toThrow(TypeError);
  });
});

describe("isValidVaultName", () => {
  it("accepts what Key Vault accepts and rejects what it does not", () => {
    expect(isValidVaultName("maindb-password")).toBe(true);
    expect(isValidVaultName("maindb_password")).toBe(false);
    expect(isValidVaultName("")).toBe(false);
    expect(isValidVaultName("a".repeat(128))).toBe(false);
  });
});

describe("roundTrips", () => {
  it("is true for conventional SCREAMING_SNAKE names", () => {
    expect(roundTrips("MAINDB_PASSWORD")).toBe(true);
  });

  it("is false for mixed-case names, which is why the manifest is explicit", () => {
    // TF_VAR_repo_pat would restore as TF_VAR_REPO_PAT and Terraform would
    // silently ignore it, so this entry carries an explicit vault name.
    expect(roundTrips("TF_VAR_repo_pat")).toBe(false);
  });
});

describe("manifest", () => {
  it("is structurally valid", () => {
    expect(validateManifest()).toEqual([]);
  });

  it("covers all 33 configured variables", () => {
    expect(entries).toHaveLength(33);
  });

  it("preserves the exact case of TF_VAR_repo_pat", () => {
    const entry = findByEnv("TF_VAR_repo_pat");
    expect(entry).toBeDefined();
    expect(entry?.env).toBe("TF_VAR_repo_pat");
    expect(entry?.secret).toBe("tf-var-repo-pat");
  });

  it("excludes the bootstrap service principal by default", () => {
    const names = selectEntries().map((entry) => entry.env);
    expect(names).not.toContain("ARM_CLIENT_SECRET");
    expect(names).toContain("MAINDB_PASSWORD");
  });

  it("includes the service principal only when explicitly asked", () => {
    const names = selectEntries({ includeBootstrap: true }).map((e) => e.env);
    expect(names).toContain("ARM_CLIENT_SECRET");
  });

  it("can be narrowed to one group", () => {
    const names = selectEntries({ groupIds: ["trd365ai"] }).map((e) => e.env);
    expect(names).toHaveLength(6);
    expect(names.every((name) => name.startsWith("TRD365AI_"))).toBe(true);
  });

  it("marks every group's bootstrap flag consistently on its entries", () => {
    for (const group of groups) {
      expect(group.entries.every((e) => e.bootstrap === group.bootstrap)).toBe(true);
    }
  });
});

describe("planPush", () => {
  const selected = selectEntries({ groupIds: ["trd365ai"] });

  it("skips variables that are unset rather than writing empty secrets", () => {
    const plan = planPush(selected, {
      TRD365AI_HOST: "db.example.internal",
      TRD365AI_PASSWORD: "hunter2",
    });

    expect(plan.writes.map((w) => w.entry.env)).toEqual([
      "TRD365AI_HOST",
      "TRD365AI_PASSWORD",
    ]);
    expect(plan.missing).toHaveLength(4);
  });

  it("treats an empty string as unset", () => {
    const plan = planPush(selected, { TRD365AI_HOST: "" });
    expect(plan.writes).toHaveLength(0);
    expect(plan.missing.map((e) => e.env)).toContain("TRD365AI_HOST");
  });

  it("carries a digest instead of exposing the value", () => {
    const plan = planPush(selected, { TRD365AI_PASSWORD: "hunter2" });
    expect(plan.writes[0].digest).toBe(digest("hunter2"));
    expect(plan.writes[0].digest).not.toContain("hunter2");
  });
});

describe("applyPush", () => {
  it("writes each planned secret under its vault name", async () => {
    const vault = fakeVault();
    const selected = selectEntries({ groupIds: ["trd365ai"] });
    const plan = planPush(selected, {
      TRD365AI_HOST: "db.example.internal",
      TRD365AI_PASSWORD: "hunter2",
    });

    const { applied, failed } = await applyPush(vault, plan);

    expect(failed).toHaveLength(0);
    expect(applied).toHaveLength(2);
    expect(vault.store.get("trd365ai-host")).toBe("db.example.internal");
    expect(vault.store.get("trd365ai-password")).toBe("hunter2");
  });

  it("records a failure without aborting the remaining writes", async () => {
    const vault = fakeVault();
    vault.setSecret = async (name, value) => {
      if (name === "trd365ai-host") throw new Error("forbidden");
      vault.store.set(name, value);
    };

    const selected = selectEntries({ groupIds: ["trd365ai"] });
    const plan = planPush(selected, {
      TRD365AI_HOST: "db.example.internal",
      TRD365AI_PASSWORD: "hunter2",
    });

    const { applied, failed } = await applyPush(vault, plan);

    expect(failed).toHaveLength(1);
    expect(applied.map((e) => e.env)).toEqual(["TRD365AI_PASSWORD"]);
    expect(vault.store.get("trd365ai-password")).toBe("hunter2");
  });
});

describe("fetchAll", () => {
  it("returns values keyed by environment name, not vault name", async () => {
    const vault = fakeVault({ "trd365ai-host": "db.example.internal" });
    const selected = selectEntries({ groupIds: ["trd365ai"] });

    const { values, missing } = await fetchAll(vault, selected);

    expect(values.get("TRD365AI_HOST")).toBe("db.example.internal");
    expect(missing).toHaveLength(5);
  });

  it("treats a 404 as missing rather than an error", async () => {
    const vault = fakeVault();
    const { values, missing } = await fetchAll(
      vault,
      selectEntries({ groupIds: ["trd365ai"] }),
    );
    expect(values.size).toBe(0);
    expect(missing).toHaveLength(6);
  });

  it("propagates errors that are not 404s", async () => {
    const vault = fakeVault();
    vault.getSecret = async () => {
      const error = new Error("boom");
      error.statusCode = 500;
      throw error;
    };
    await expect(
      fetchAll(vault, selectEntries({ groupIds: ["trd365ai"] })),
    ).rejects.toThrow("boom");
  });
});

describe("compareWithEnv", () => {
  const selected = selectEntries({ groupIds: ["trd365ai"] });

  it("classifies each entry without exposing values", async () => {
    const vault = fakeVault({
      "trd365ai-host": "db.example.internal",
      "trd365ai-password": "vault-value",
    });

    const { rows } = await compareWithEnv(vault, selected, {
      TRD365AI_HOST: "db.example.internal",
      TRD365AI_PASSWORD: "different",
      TRD365AI_USER: "app",
    });

    const byEnv = Object.fromEntries(rows.map((r) => [r.entry.env, r.status]));
    expect(byEnv.TRD365AI_HOST).toBe("match");
    expect(byEnv.TRD365AI_PASSWORD).toBe("differ");
    expect(byEnv.TRD365AI_USER).toBe("vault-missing");
    expect(byEnv.TRD365AI_PORT).toBe("absent-both");

    const serialised = JSON.stringify(rows);
    expect(serialised).not.toContain("vault-value");
    expect(serialised).not.toContain("different");
  });

  it("reports env-missing once a value exists only in the vault", async () => {
    const vault = fakeVault({ "trd365ai-host": "db.example.internal" });
    const { rows } = await compareWithEnv(vault, selected, {});
    const host = rows.find((r) => r.entry.env === "TRD365AI_HOST");
    expect(host?.status).toBe("env-missing");
  });
});

describe("renderers", () => {
  it("quotes shell values so embedded quotes cannot break out", () => {
    expect(shellQuote("plain")).toBe("'plain'");
    expect(shellQuote("it's")).toBe(`'it'\\''s'`);
    expect(shellQuote("a b; rm -rf /")).toBe("'a b; rm -rf /'");
  });

  it("escapes dotenv values that would otherwise break the line", () => {
    expect(dotenvQuote("plain")).toBe('"plain"');
    expect(dotenvQuote('say "hi"')).toBe('"say \\"hi\\""');
    expect(dotenvQuote("line1\nline2")).toBe('"line1\\nline2"');
    expect(dotenvQuote("back\\slash")).toBe('"back\\\\slash"');
  });

  it("renders exports and dotenv lines for every value", () => {
    const values = new Map([
      ["TRD365AI_HOST", "db.example.internal"],
      ["TRD365AI_PASSWORD", "p@ss'word"],
    ]);

    expect(renderShell(values)).toBe(
      `export TRD365AI_HOST='db.example.internal'\nexport TRD365AI_PASSWORD='p@ss'\\''word'`,
    );
    expect(renderDotenv(values)).toBe(
      `TRD365AI_HOST="db.example.internal"\nTRD365AI_PASSWORD="p@ss'word"`,
    );
  });
});

describe("resolveVaultName", () => {
  it("prefers the explicit argument, then the environment", () => {
    expect(resolveVaultName("explicit-kv", {})).toBe("explicit-kv");
    expect(resolveVaultName(undefined, { AZURE_KEY_VAULT_NAME: "env-kv" })).toBe(
      "env-kv",
    );
  });

  it("explains itself when no vault is named", () => {
    expect(() => resolveVaultName(undefined, {})).toThrow(/AZURE_KEY_VAULT_NAME/);
  });

  it("rejects names Azure would not accept", () => {
    expect(() => resolveVaultName("no", {})).toThrow(/not a valid Key Vault name/);
    expect(() => resolveVaultName("has_underscore", {})).toThrow();
  });

  it("builds the vault URL", () => {
    expect(vaultUrl("certainti-kv")).toBe("https://certainti-kv.vault.azure.net");
  });
});
