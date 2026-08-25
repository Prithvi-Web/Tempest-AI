/**
 * The client caches that describe "which models can I pick" (ADR-0085).
 *
 * Two query keys, named here rather than at the call site because they are a CONTRACT with
 * the vendored data-provider and a typo in either one fails silently — `invalidateQueries`
 * on a key nothing uses does nothing at all, and the symptom is identical to not calling it.
 *
 * The values are upstream's `QueryKeys.endpoints` and `QueryKeys.models`. They are written
 * out rather than imported because importing from the vendored tree pulls it into this seam's
 * tsconfig, which is red at baseline (see `tabs.tsx`). `modelWorld.spec` in
 * `packages/desktop/tests` reads the enum out of the provider package and asserts these two
 * strings still match it, so the copy cannot drift without a test going red.
 */

/** `QueryKeys.endpoints` — which providers exist and what they are called. */
export const ENDPOINTS_KEY = "endpoints";

/** `QueryKeys.models` — which models each provider offers. */
export const MODELS_KEY = "models";

/**
 * Both, in the order a reader would expect: the providers, then their models.
 *
 * Invalidated whenever the local model server starts or stops. Neither query expires on its
 * own — both are `staleTime: Infinity, refetchOnMount: false` — so nothing else will ever
 * cause the picker to notice that a model became available.
 */
export const MODEL_WORLD_KEYS = [ENDPOINTS_KEY, MODELS_KEY] as const;
