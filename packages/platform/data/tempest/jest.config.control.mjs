/**
 * C6.0 — the CONTROL harness: LibreChat's own 66 suites, run against a real `mongod`.
 *
 * This exists so that "green against the store C1 selected" can mean something. A suite that
 * fails against @tempest/docstore AND against real MongoDB has found nothing; only a suite
 * that fails against one of them has (trap 54 — a differential check must ask both sides
 * under the same conditions). The number this config produces is that other side.
 *
 * It is Tempest-owned and lives in the seam directory, so `packages/platform/data/src/**` and
 * the vendored `jest.config.mjs` stay byte-for-byte upstream (L27, empty delta-ledger row).
 *
 * EXACTLY ONE override, and it is a layout adaptation rather than a behaviour change.
 * Upstream's `transformIgnorePatterns` is written for npm's FLAT `node_modules`:
 *
 *     /node_modules/(?!mdast-util-|micromark|…)
 *
 * Under pnpm the real path of an ESM-only dependency is
 *
 *     …/node_modules/.pnpm/micromark-extension-gfm@3.0.0/node_modules/micromark-extension-gfm/index.js
 *
 * The regex is unanchored, so it is tested at BOTH `/node_modules/` positions. At the second
 * one the lookahead correctly sees `micromark-extension-gfm` and refuses to match — but at the
 * FIRST it sees `.pnpm`, which is on nobody's exception list, so the pattern matches, the file
 * is never transformed, and jest dies on `Cannot use import statement outside a module`.
 *
 * Adding `\.pnpm` to the exception list makes the first position fail the lookahead too, which
 * leaves the second position — the one carrying the real package name — as the only decider.
 * The set of packages that get transformed is therefore identical to upstream's intent; only
 * the directory shape it is matched against differs.
 */
import upstream from '../jest.config.mjs';

const PNPM_STORE_HOP = '\\.pnpm|';

export default {
  ...upstream,
  rootDir: '..',
  transformIgnorePatterns: upstream.transformIgnorePatterns.map((pattern) =>
    pattern.replace('/node_modules/(?!', `/node_modules/(?!${PNPM_STORE_HOP}`),
  ),
};
