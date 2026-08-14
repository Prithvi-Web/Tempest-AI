/** Sidecar entry: read requests line-by-line on stdin, write responses on stdout. */
import { createInterface } from "node:readline";

import { Dispatcher } from "./rpc.js";

export function buildDispatcher(): Dispatcher {
  const d = new Dispatcher();
  d.register("ping", () => ({ pong: true, sidecar: "@tempest/ts-sidecar", version: "0.1.0" }));
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
