/** Desktop replacement for the web dashboard's api-client: same generated `paths` contract,
 * but the base URL arrives at runtime from the Tauri shell (which picked the sidecar's port
 * and injected `window.__TEMPEST_API__` before the page loaded). */
import createClient from "openapi-fetch";

import type { paths } from "@tempest/shared-schema/types";

declare global {
  interface Window {
    __TEMPEST_API__?: string;
  }
}

export const apiBaseUrl: string =
  (typeof window !== "undefined" && window.__TEMPEST_API__) || "http://127.0.0.1:8000";

export const client = createClient<paths>({ baseUrl: apiBaseUrl });
