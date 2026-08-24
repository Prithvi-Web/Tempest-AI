/**
 * The two tabs Tempest contributes to the app's one settings home, and the entries in them
 * (ADR-0082).
 *
 * The vendored dialog is registry-driven — `TABS` in `Nav/Settings/types.ts`, `registry` in
 * `Nav/Settings/registry.tsx` — which is exactly the extension point this needed. Two spread
 * expressions in those files are the whole of the vendored change (`UPSTREAM.md`); everything
 * that makes the tabs real is here, in the seam, where `make verify` typechecks it.
 *
 * **Every panel is lazy.** The panels reach the host through `views/hooks.ts`, which imports
 * the generated tauri bindings, and `registry.tsx` is in the client's MAIN chunk — a static
 * import would pull `@tauri-apps/api` into every bundle including the browser harness and
 * server mode. `streamHost.ts` already established this discipline for the SSE seam and gives
 * the reason in as many words; `React.lazy` is the component-shaped version of it.
 */

import { Suspense, lazy } from "react";
import type { ComponentType, ReactNode } from "react";

import { TEMPEST_ENGINE_TAB, TEMPEST_MODELS_TAB } from "./tabIds";
import type { TempestSettingsTab } from "./tabIds";

/**
 * The dialog's shapes, declared HERE rather than imported from
 * `~/components/Nav/Settings/types`.
 *
 * Not a preference — a constraint. `make verify` typechecks this seam with its own tsconfig,
 * and that gate is green; the VENDORED client's own `tsc` is red at baseline (thousands of
 * pre-existing React/Recoil conflicts, exit 2). One `import type` from `src/` pulls that whole
 * tree into this project and turns the seam's only real type signal into noise.
 *
 * So the shapes are mirrored, structurally, and the fields that must line up with upstream's
 * are held by two nets instead: the literal `labelKey` values below are checked against the
 * English locale by `tempest-settings-manifest.test.ts` (the same assertion upstream's own
 * `registry.spec.ts` makes over its registry), and the whole manifest is exercised through the
 * real dialog by the e2e suite. A drift in upstream's `TabMeta` therefore fails a test rather
 * than passing quietly.
 */
interface TempestSectionMeta {
  id: TempestSectionId;
  labelKey: TempestSectionLabelKey;
}

interface TempestTabMeta {
  id: TempestSettingsTab;
  labelKey: TempestTabLabelKey;
  icon: ReactNode;
  sections: TempestSectionMeta[];
}

interface TempestSettingEntry {
  id: string;
  tab: TempestSettingsTab;
  section: TempestSectionId;
  labelKey: TempestEntryLabelKey;
  keywords?: string[];
  Component: ComponentType;
}

/** The section ids this seam owns. `Nav/Settings/types.ts` widens `SectionId` with exactly
 * these six strings; the manifest test asserts the two lists agree. */
export type TempestSectionId =
  | "tempestLocalModels"
  | "tempestProviderKeys"
  | "tempestProofStorage"
  | "tempestProofSync"
  | "tempestProofEditor"
  | "tempestProofPrivacy";

type TempestTabLabelKey = "com_tempest_settings_tab_models" | "com_tempest_settings_tab_engine";

type TempestSectionLabelKey =
  | "com_tempest_settings_section_local_models"
  | "com_tempest_settings_section_provider_keys"
  | "com_tempest_settings_section_proof_storage"
  | "com_tempest_settings_section_proof_sync"
  | "com_tempest_settings_section_proof_editor"
  | "com_tempest_settings_section_proof_privacy";

type TempestEntryLabelKey =
  | "com_tempest_settings_label_local_models"
  | "com_tempest_settings_label_engine_key"
  | "com_tempest_settings_label_bundle_budget"
  | "com_tempest_settings_label_team_server"
  | "com_tempest_settings_label_editor_runners"
  | "com_tempest_settings_label_telemetry"
  | "com_tempest_settings_label_diagnostics";

/**
 * A panel, loaded when its tab is first rendered and not before.
 *
 * The fallback is deliberately a bare sized box rather than a spinner: these chunks resolve
 * from the local bundle in a frame or two, and a spinner that flashes for 30 ms reads as a
 * fault. The height keeps the section from collapsing and re-jolting the dialog (CLS = 0 is a
 * gate, §12).
 */
function panel(load: () => Promise<{ default: ComponentType }>, name: string): ComponentType {
  const Loaded = lazy(load);
  const Panel = () => (
    <Suspense fallback={<div className="h-16" aria-hidden="true" />}>
      <Loaded />
    </Suspense>
  );
  Panel.displayName = `TempestSettings(${name})`;
  return Panel;
}

function namedPanel(
  load: () => Promise<Record<string, ComponentType>>,
  exportName: string,
): ComponentType {
  return panel(
    () => load().then((module) => ({ default: module[exportName] as ComponentType })),
    exportName,
  );
}

const ModelsPanel = panel(() => import("./ModelsPanel"), "Models");
const EngineKeyPanel = panel(() => import("./EngineKeyPanel"), "EngineKey");
const StoragePanel = namedPanel(() => import("./EnginePanels"), "StoragePanel");
const SyncPanel = namedPanel(() => import("./EnginePanels"), "SyncPanel");
const EditorRunnersPanel = namedPanel(() => import("./EnginePanels"), "EditorRunnersPanel");
const TelemetryPanel = namedPanel(() => import("./EnginePanels"), "TelemetryPanel");
const DiagnosticsPanel = namedPanel(() => import("./EnginePanels"), "DiagnosticsPanel");

/**
 * The tab marks, drawn here rather than imported from `lucide-react`.
 *
 * Not aesthetics — the same constraint that keeps the vendored types out of this file. Two
 * copies of `@types/react` are resolvable in this workspace, and lucide's
 * `ForwardRefExoticComponent` is typed against the other one, so `createElement(Boxes, …)`
 * fails to typecheck HERE while being perfectly fine in the vendored tree (whose own tsc is
 * red at baseline and reports it alongside thousands of others). `TempestViews.tsx` draws its
 * own rail icons for exactly this reason; these two match that set.
 */
function BoxesMark(): JSX.Element {
  return (
    <svg
      className="icon-sm"
      viewBox="0 0 18 18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M2.5 5.5 6 3.5l3.5 2L6 7.5zM8.5 12.5 12 10.5l3.5 2L12 14.5z" />
      <path d="M2.5 5.5v4L6 11.5v-4M9.5 5.5v4L6 11.5M8.5 12.5v2M15.5 12.5v2" />
    </svg>
  );
}

/** The bolt, matching the proof surface's mark on the main rail: one idea, one icon. */
function BoltMark(): JSX.Element {
  return (
    <svg
      className="icon-sm"
      viewBox="0 0 18 18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M10 2 4 10h4l-1 6 6-8h-4z" />
    </svg>
  );
}

const MODEL_SECTIONS: TempestSectionMeta[] = [
  { id: "tempestLocalModels", labelKey: "com_tempest_settings_section_local_models" },
  { id: "tempestProviderKeys", labelKey: "com_tempest_settings_section_provider_keys" },
];

const ENGINE_SECTIONS: TempestSectionMeta[] = [
  { id: "tempestProofStorage", labelKey: "com_tempest_settings_section_proof_storage" },
  { id: "tempestProofSync", labelKey: "com_tempest_settings_section_proof_sync" },
  { id: "tempestProofEditor", labelKey: "com_tempest_settings_section_proof_editor" },
  { id: "tempestProofPrivacy", labelKey: "com_tempest_settings_section_proof_privacy" },
];

export const TEMPEST_SETTINGS_TABS: TempestTabMeta[] = [
  {
    id: TEMPEST_MODELS_TAB,
    labelKey: "com_tempest_settings_tab_models",
    icon: <BoxesMark />,
    sections: MODEL_SECTIONS,
  },
  {
    id: TEMPEST_ENGINE_TAB,
    labelKey: "com_tempest_settings_tab_engine",
    icon: <BoltMark />,
    sections: ENGINE_SECTIONS,
  },
];

/**
 * The entries this seam owns. Upstream's three provider-key entries are NOT here — they are
 * upstream's components, and they move tab in `registry.tsx` by editing the two fields that
 * say where they live, which is a smaller and more honest change than re-declaring them.
 */
export const TEMPEST_SETTINGS_ENTRIES: TempestSettingEntry[] = [
  {
    id: "tempestLocalModels",
    tab: TEMPEST_MODELS_TAB,
    section: "tempestLocalModels",
    labelKey: "com_tempest_settings_label_local_models",
    keywords: ["local", "model", "download", "offline", "llama", "gguf", "qwen", "serve", "free"],
    Component: ModelsPanel,
  },
  {
    id: "tempestEngineKey",
    tab: TEMPEST_MODELS_TAB,
    section: "tempestProviderKeys",
    labelKey: "com_tempest_settings_label_engine_key",
    keywords: ["anthropic", "key", "proof", "harness", "synthesis", "credentials"],
    Component: EngineKeyPanel,
  },
  {
    id: "tempestBundleBudget",
    tab: TEMPEST_ENGINE_TAB,
    section: "tempestProofStorage",
    labelKey: "com_tempest_settings_label_bundle_budget",
    keywords: ["bundle", "budget", "storage", "disk", "evidence", "data folder"],
    Component: StoragePanel,
  },
  {
    id: "tempestTeamServer",
    tab: TEMPEST_ENGINE_TAB,
    section: "tempestProofSync",
    labelKey: "com_tempest_settings_label_team_server",
    keywords: ["sync", "server", "team", "push", "share", "source"],
    Component: SyncPanel,
  },
  {
    id: "tempestEditorRunners",
    tab: TEMPEST_ENGINE_TAB,
    section: "tempestProofEditor",
    labelKey: "com_tempest_settings_label_editor_runners",
    keywords: ["editor", "language server", "lsp", "pylsp", "completion", "runner"],
    Component: EditorRunnersPanel,
  },
  {
    id: "tempestTelemetry",
    tab: TEMPEST_ENGINE_TAB,
    section: "tempestProofPrivacy",
    labelKey: "com_tempest_settings_label_telemetry",
    keywords: ["telemetry", "privacy", "usage", "counters", "anonymous"],
    Component: TelemetryPanel,
  },
  {
    id: "tempestDiagnostics",
    tab: TEMPEST_ENGINE_TAB,
    section: "tempestProofPrivacy",
    labelKey: "com_tempest_settings_label_diagnostics",
    keywords: ["diagnostic", "bundle", "support", "export", "redaction"],
    Component: DiagnosticsPanel,
  },
];
