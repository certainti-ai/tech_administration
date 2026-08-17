import { defineConfig } from "vitest/config";

/** Root config — covers repo-wide tooling only. The web app has its own. */
export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.mjs"],
  },
});
