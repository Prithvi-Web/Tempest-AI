/** The absorbed views' URL space, built in one place (replaces the desktop shell's `router.ts`).
 *
 * The desktop webview routed on query params (`?view=run&id=3`) because it had no router and no
 * server-side route table. Inside the platform client the router IS react-router, so the same
 * states are real paths under one mount point — and `TEMPEST_BASE` is the single fact the outer
 * wiring and this subtree have to agree on.
 *
 * Every href is built here rather than written inline, for the reason the query-param version
 * gave: the editor route names a project and a file, both arbitrary strings, and a path that
 * cannot survive its own filenames is not a path.
 */

/** Where the subtree is mounted. `navManifest.path` in `index.ts` is the same string. */
export const TEMPEST_BASE = "/tempest";

export function runsPath(): string {
  return TEMPEST_BASE;
}

export function runPath(id: number): string {
  return `${TEMPEST_BASE}/runs/${id}`;
}

export function targetPath(id: number): string {
  return `${TEMPEST_BASE}/targets/${id}`;
}

export function divergencePath(id: number): string {
  return `${TEMPEST_BASE}/divergences/${id}`;
}

export function provePath(): string {
  return `${TEMPEST_BASE}/prove`;
}

export function watchPath(): string {
  return `${TEMPEST_BASE}/watch`;
}

export function composerPath(): string {
  return `${TEMPEST_BASE}/composer`;
}

export function logsPath(): string {
  return `${TEMPEST_BASE}/logs`;
}

export function settingsPath(): string {
  return `${TEMPEST_BASE}/settings`;
}

/** The editor names a project and a file inside it. Both are carried as search params and encoded
 * by `URLSearchParams` rather than by hand: a path contains `/`, `&` and `#` routinely, and path
 * segments would have to be re-escaped at every link site to survive them. */
export function editorPath(repo: string, file: string): string {
  const query = new URLSearchParams({ repo, file });
  return `${TEMPEST_BASE}/editor?${query.toString()}`;
}

/** A row id out of the URL, or `null`.
 *
 * A MISSING or malformed id must not become run #0: `Number(undefined)` is NaN and `Number("")`
 * is 0, so the presence check comes first and only a positive integer names a row (ids are
 * 1-based database keys). The caller sends `null` back to the list rather than fetching nothing.
 */
export function rowId(raw: string | undefined): number | null {
  if (raw === undefined || raw === "") return null;
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}
