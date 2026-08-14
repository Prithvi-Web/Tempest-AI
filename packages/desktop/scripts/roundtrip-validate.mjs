// TypeScript-side leg of the §9b round-trip gate: every payload the Rust types re-serialized
// must validate against the SAME domain-schema.json the TS contract derives from. ajv runs the
// 2020-12 dialect the OpenAPI 3.1 components are written in.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";

import { Ajv2020 } from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const here = dirname(fileURLToPath(import.meta.url));
const schema = JSON.parse(
  readFileSync(join(here, "../../shared-schema/domain-schema.json"), "utf8"),
);

const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
ajv.addSchema(schema, "domain");

let total = 0;
let invalid = 0;
const errors = [];

const rl = createInterface({ input: process.stdin, terminal: false });
rl.on("line", (line) => {
  if (!line.trim()) return;
  total += 1;
  const { type, value } = JSON.parse(line);
  const valid = ajv.validate({ $ref: `domain#/$defs/${type}` }, value);
  if (!valid) {
    invalid += 1;
    errors.push(`${type}: ${ajv.errorsText(ajv.errors)}`);
  }
});
rl.on("close", () => {
  console.log(JSON.stringify({ total, invalid, errors: errors.slice(0, 20) }));
  process.exit(0);
});
