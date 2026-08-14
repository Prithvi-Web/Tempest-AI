import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The desktop UI consumes the SAME generated hooks as the web dashboard (zero drift extends to
// the app). The alias order matters: the api-client shim must win before the catch-all "@/".
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: "@/lib/api-client", replacement: resolve(__dirname, "src/api.ts") },
      { find: "@", replacement: resolve(__dirname, "../../packages/web/src") },
      {
        find: "@tempest/shared-schema/types",
        replacement: resolve(__dirname, "../../packages/shared-schema/types.ts"),
      },
    ],
  },
  build: { target: "es2022" },
  clearScreen: false,
  server: { port: 1420, strictPort: true },
});
