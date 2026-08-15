/** Test-only globals installed by shim.js (see fixtures.ts addInitScript). */
interface Window {
  __E2E__: {
    /** Deliver a host-emitted Tauri event to in-page listeners; returns delivery count. */
    emit(name: string, payload: unknown): number;
  };
  __E2E_BRIDGE_URL__?: string;
  /** Installed by src/devValidate.ts in dev builds (Boundary B deep validation). */
  __TEMPEST_DEV_VALIDATE__?: (command: string, data: unknown) => void;
}
