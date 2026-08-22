// The C3 seam build config (L27: zero edits to vendored files). Build with:
//
//   pnpm --filter @librechat/frontend exec vite build --config tempest/vite.config.mjs
//
// It removes exactly the browser-deployment machinery the tempest:// protocol cannot
// use: the PWA service worker (a native shell has no browser-update layer; the protocol
// already serves registerSW.js as a no-op) and the precompressed .br/.gz siblings (the
// protocol serves plain files, so they would only bloat the bundled resources).
// Upstream's chunking is deliberately KEPT: the WKWebView render crash once blamed on
// chunk order was really two Reacts in one bundle — fixed at the root by the react pin
// in pnpm-workspace.yaml, and pinned there with its reasoning.
import vendored from '../vite.config.ts';

export default async (env) => {
  const base = typeof vendored === 'function' ? await vendored(env) : vendored;
  const plugins = (base.plugins ?? []).flat(Infinity).filter(Boolean);
  const isServiceWorker = (p) =>
    String(p?.name ?? '').startsWith('vite-plugin-pwa') || p?.name === 'emit-sw-heal';
  const isCompression = (p) => String(p?.name ?? '').includes('compression');
  if (!plugins.some(isServiceWorker)) {
    // Fail loud on upstream drift: if the PWA plugin is gone from the vendored config,
    // this override is stale and the service-worker neutralization must be re-audited —
    // a silent no-op here could ship an update layer the shell must never have.
    throw new Error(
      'tempest/vite.config.mjs: no vite-plugin-pwa plugins found in the vendored ' +
        'vite.config.ts — upstream changed shape; re-audit the service-worker neutralization',
    );
  }
  base.plugins = plugins.filter((p) => !isServiceWorker(p) && !isCompression(p));
  return base;
};
