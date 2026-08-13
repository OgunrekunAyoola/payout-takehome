import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // Server-only modules (src/lib/api.ts, the signing helper) are never imported by a
    // test: they reach the network and hold the webhook secret. The tests target the
    // rules and the components, which is where the behaviour worth protecting lives.
  },
});
