/** The absorbed proof surface's single doorway (C3).
 *
 * The outer wiring — the one inline route entry in the vendored router and the one sidebar
 * link — imports exactly this module, so the whole subtree stays one lazy chunk and the
 * vendored tree's knowledge of it stays one line wide. `navManifest.path` and
 * `routes.TEMPEST_BASE` state the same fact; `routes.ts` is where it lives.
 */
export { default } from './TempestViews';
export { TEMPEST_BASE } from './routes';

export const navManifest = { path: 'tempest', label: 'Tempest' } as const;
