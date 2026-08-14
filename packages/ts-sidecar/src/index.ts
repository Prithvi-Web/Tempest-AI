/**
 * Sidecar entry: read requests line-by-line on stdin, write responses on stdout.
 *
 * Launched from source — `node --experimental-strip-types src/index.ts` — so imports use explicit
 * `.ts` specifiers (Node's type stripping does not remap `.js`; the repo's Node 24 strips types
 * natively and the flag keeps Node 22.6+ working). No build step, no dist.
 */
import { createInterface } from "node:readline";

import { selectTargets } from "./analyze.ts";
import { parseSelectTargetsParams, parseValuePoolsParams } from "./params.ts";
import { valuePools } from "./pools.ts";
import { Dispatcher } from "./rpc.ts";

export function buildDispatcher(): Dispatcher {
  const d = new Dispatcher();
  d.register("ping", () => ({ pong: true, sidecar: "@tempest/ts-sidecar", version: "0.1.0" }));
  d.register("selectTargets", (params) => selectTargets(parseSelectTargetsParams(params)));
  d.register("valuePools", (params) => valuePools(parseValuePoolsParams(params)));
  return d;
}

const isMain = process.argv[1]?.endsWith("index.ts") || process.argv[1]?.endsWith("index.js");
if (isMain) {
  const dispatcher = buildDispatcher();
  const rl = createInterface({ input: process.stdin, terminal: false });
  rl.on("line", (line) => {
    if (line.trim() === "") return;
    void dispatcher.dispatch(line).then((resp) => {
      process.stdout.write(JSON.stringify(resp) + "\n");
    });
  });
}
