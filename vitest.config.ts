import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  test: {
    environment: "node",
    // Secrets tooling is plain ESM (.mjs) so it runs under bare `node` with no
    // build step; the app and its tests are TypeScript.
    include: ["tests/**/*.test.ts", "tests/**/*.test.mjs"],
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
});
