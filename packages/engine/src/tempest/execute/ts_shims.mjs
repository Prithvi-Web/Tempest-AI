/**
 * JS determinism shims (Law L3) — preloaded via `node --import` BEFORE the target module,
 * mirroring tempest/determinism/_shims.py's role: base and head must observe identical
 * ambient conditions, so wall clocks and entropy are pinned to a seeded, deterministic
 * sequence. Wave 1 covers the pure-function surface: Date, Math.random, performance.now,
 * and crypto.getRandomValues. Network/fs interception is the JS record/replay half
 * (wave 2) — targets touching those classify IMPURE_RECORDABLE and never reach a worker.
 */

const EPOCH_MS = 1_700_000_000_000; // a fixed, plausible instant — identical on both sides
let ticks = 0;

function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const seed = Number.parseInt(process.env.TEMPEST_JS_SEED ?? "0", 10) || 0;
const rng = mulberry32(seed ^ 0x9e3779b9);

Math.random = rng;

const RealDate = Date;
function now() {
  ticks += 1; // strictly monotonic: repeated reads advance identically on both sides
  return EPOCH_MS + ticks;
}

globalThis.Date = class extends RealDate {
  constructor(...args) {
    if (args.length === 0) {
      super(now());
    } else {
      super(...args);
    }
  }
  static now() {
    return now();
  }
};

if (globalThis.performance) {
  globalThis.performance.now = () => now() - EPOCH_MS;
}

if (globalThis.crypto?.getRandomValues) {
  globalThis.crypto.getRandomValues = (view) => {
    const bytes = new Uint8Array(view.buffer, view.byteOffset, view.byteLength);
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(rng() * 256);
    return view;
  };
}

if (globalThis.crypto?.randomUUID) {
  globalThis.crypto.randomUUID = () => {
    const hex = () => Math.floor(rng() * 16).toString(16);
    const s = Array.from({ length: 32 }, hex);
    s[12] = "4"; // version nibble, like the real thing
    s[16] = ((Math.floor(rng() * 4) | 8) & 0xf).toString(16); // variant nibble
    const j = s.join("");
    return `${j.slice(0, 8)}-${j.slice(8, 12)}-${j.slice(12, 16)}-${j.slice(16, 20)}-${j.slice(20)}`;
  };
}
