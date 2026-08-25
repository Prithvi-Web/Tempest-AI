# C6 — THE DATASTORE CUTOVER MASTER PROMPT

> **Normative for phase C6.** Subordinate to `docs/TEMPEST-V3-MASTER-PROMPT.md` and `CLAUDE.md`
> (Laws L1–L36); where this file adds detail it governs, where it conflicts with a Law the Law
> wins. Decisions: **ADR-0068** + its C1 amendment (the fallback, ENGAGED) and **ADR-0090** (the
> seam). Plan: `docs/PLAN-V3.md` §C6. Dispositions: `docs/MERGE-CONTRACT.md`.
>
> **Written 2026-08-25, at the close of C6.0, from measurements rather than from reading.** Every
> number below was taken by running something. Where a count is static rather than executed, it
> says so. Where something is unknown, it says that too — those are the most valuable lines here.

---

## 0. HOW TO USE THIS FILE

### 0.1 Every C6 session begins the same way

```bash
cd "$HOME/Desktop/Claude Code/tempest"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# 1. Know the tip. A document that hard-codes its own SHA is stale the moment it is committed.
git rev-parse --short HEAD && git log --oneline origin/main..HEAD | wc -l && git status --short | wc -l

# 2. Know the tree's REAL state before writing anything (master prompt §0.1 rule 6).
TEMPEST_DEV=1 TEMPEST_NO_POWER_PAUSE=1 make verify > /tmp/verify.log 2>&1; echo "MAKE_EXIT=$?" >> /tmp/verify.log
grep -E "^MAKE_EXIT=" /tmp/verify.log     # read THIS line, never a task notification (trap 40)

# 3. Know the CONTROL still holds — the number every C6 claim is measured against.
./scripts/data-control.sh                 # 66/66 suites · 2371 tests · CONTROL_EXIT=0
```

Read order: `CLAUDE.md` → `docs/TEMPEST-V3-MASTER-PROMPT.md` → **this file** → `docs/PLAN-V3.md`
§C6 (find the first unchecked box) → ADR-0068, its amendment, and ADR-0090 in `docs/DECISIONS.md`
→ `docs/MERGE-CONTRACT.md` data-layer rows.

### 0.2 The completion rule, restated because it is the rule most often broken

You may not write "done", "complete", "working", "passing", or "green" without pasting the actual
terminal output of the relevant gate **in the same message**. A checkbox flipped without pasted
output is a lie in the repository's history. **Claimed-passing is failing.**

### 0.3 Work order

- **One sub-phase at a time** (C6.1 → C6.5). Land it green, with its gate, with an ADR if it
  deviated, then stop and report in plain English. The owner is a non-coder.
- **Authoring is single-threaded.** Write each piece in one coherent voice. Subagents are for
  **read-only reconnaissance and adversarial review**, never for writing the implementation —
  and reviewers get read-only instructions explicitly (trap 42).
- **TDD, strictly.** Failing test → minimal implementation → refactor. Property-based tests for
  anything touching the query matcher, the update engine, or the aggregation evaluator.
- **The bar: 100% coverage, zero known defects, no red CI, ever.** Never weaken a gate to pass it.
- **No TODO-as-deferral.** Undone work is a `docs/PLAN-V3.md` item, never a comment.

### 0.4 When this prompt is wrong

It will be wrong somewhere — it was written before the store existed. When it is: **stop, write
the ADR, and say so.** Do not silently do something else, and do not implement something you can
see is wrong because a document said to. C6.0 already produced four such corrections and they are
the most useful part of this file.

---

## 1. WHAT C6 IS

**One sentence:**

> LibreChat's vendored Mongoose data layer — 90,889 lines, 66 test suites, 2,371 tests — must run
> green against a store Tempest wrote, which speaks MongoDB's wire protocol over a Unix domain
> socket and answers out of SQLite, **without a single vendored file being edited.**

Two halves, both mandatory:

**The store must be correct.** Not "correct enough for the happy path" — correct against 1,803
tests written by people who did not know it existed, including tests that spy on the driver, that
assert on transaction read concerns, and that read query-planner output.

**The store must be invisible.** `packages/platform/data/` stays byte-for-byte upstream. Its
delta-ledger row in `packages/platform/UPSTREAM.md` stays **empty**. If C6 ends with edits inside
that tree, the phase failed even if every test passes, because L27 says upstream mergeability is
a shipped feature and `data-schemas` is the most schema-active package in the vendored tree.

---

## 2. GROUND TRUTH — MEASURED 2026-08-24/25, DO NOT REDISCOVER

### 2.1 What C6.0 established (commits `4959911`, `6b356d1`, `4ee92ea`)

`packages/platform/data` is now a pnpm workspace member and its suites run. **The CONTROL:**

```
$ ./scripts/data-control.sh
Test Suites: 66 passed, 66 total
Tests:       2371 passed, 2371 total
Time:        55.242 s
All files    |   77.84 |    73.82 |   82.83 |   78.02 |
CONTROL_EXIT=0                    mongod-arm64-darwin-8.2.6
```

**This is the single most important artifact in C6.** A suite that fails against the Tempest store
*and* against real MongoDB has found nothing; only a suite that fails against exactly one of them
has (trap 54 — a differential check must ask both sides under the same conditions). Re-take the
control whenever the vendored tree moves.

### 2.2 The shape of the work

| | measured | how |
|---|---|---|
| vendored data layer | 90,889 LOC TS, 282 source files | `find src -name '*.ts' \| xargs wc -l` |
| the gate | 66 spec files, **2,371 tests** | executed; a static sweep says 2,252 — 11 files use `it.each` |
| store-backed vs not | **44 suites / 1,803 static tests** boot a server; **22 / 449** run in-process | static classification on `MongoMemoryServer\|MongoMemoryReplSet` |
| raw-driver suites | **19** — 16 via `Model.collection.*`, 3 via `connection.db`, disjoint sets | grep, counted separately then unioned |
| replica-set suites | **2** — `methods/userGroup.spec.ts`, `methods/mcpAuthority.spec.ts`, both for multi-document transactions, neither for change streams | grep `MongoMemoryReplSet` |
| query operators | **17** | key-position sweep of non-spec `src/**` |
| update operators | **12** — 11 in key position plus `$bit` (only ever assigned); `$rename` and the positional `$` handled separately (§2.3) | as above |
| aggregation stages | **11** | as above |
| aggregation expressions | **18** | as above |
| index declarations | **235** — 116 `schema.index()` + 119 field-level `index: true` | comments stripped first |
| index options | 32 `unique`, 14 `partialFilterExpression`, 11 `expireAfterSeconds`, 6 `sparse`, **0 text**, **0 collation** | comments stripped first |
| `.aggregate()` call sites | 22 (16 source, 6 spec) | `grep -rnE "\.aggregate(<[^(]*>)?\("` — a naive grep finds only 10 |
| migrations | 4, in `src/migrations/`, **none with a down path** | + 6 more one-way CLI scripts in `packages/platform/config/` |

**Report the store-backed number, never the headline one.** "2,371 green against @tempest/docstore"
would be true and misleading on a day the store could not serve a single query, because 449 of
those tests never touch it. The number that means something is **1,803**.

### 2.3 The exact operator surface — this is the spec

**Query (17):** `$and $elemMatch $eq $exists $gt $gte $in $lt $lte $ne $nin $nor $not $options
$or $regex $size`

**Update (12):** `$addToSet $currentDate $each $inc $pull $pullAll $push $set $setOnInsert
$slice $unset` (11 in key position) **+ `$bit`**, which is only ever *assigned*
(`aclEntry.ts:464`) and so appears in no sweep — a checklist-driven implementation misses it.

Two things that are **not** in that 12 and still need handling: the **positional `$`** (a path
form, not an operator — §4 case 1), and **`$rename`**, which has no key-position call site
anywhere in non-spec sources but is one of `tenantIsolation.ts:30`'s `STRIP_OPERATORS`
(`['$unset', '$rename']`), so the plugin can put it into an update document your engine then
receives.

**Aggregation stages (11):** `$addFields $count $facet $group $limit $lookup $match $project
$skip $sort $unwind`

**Aggregation expressions (18):** `$concatArrays $cond $convert $dateToString $filter $first
$ifNull $indexOfCP $isArray $let $literal $map $max $mergeObjects $min $strLenCP $substrCP $sum`
— plus `$$ROOT` and user-defined `$let` variables.

**Used ZERO times — do not build until something needs them:** `$type $all $mod $jsonSchema
$pop $mul $position $where $text $bitsAllSet $near $comment`, `$out`, `$merge`, `$graphLookup`,
`$unionWith`, `$bucket`, `$sample`, `$sortByCount`, `$replaceRoot`, `$setWindowFields`,
`allowDiskUse`, collation, text indexes, change streams, `arrayFilters`, `$[]`, `$[<id>]`.

**Four tokens are false positives** and are members of hand-written mongoose `Document` types,
not operators: `$where`, `$op`, `$locals` (`methods/user.ts:111-113`), `$isDefault`
(`methods/conversation.ts:32`). The four buckets plus these four account for all 61 distinct
`$`-tokens the sweep finds — that arithmetic is what makes the partition checkable.

**`$slice` is counted twice on purpose.** It is a `$push` modifier *and* an unrelated aggregation
expression (`methods/mcpAuthority.ts:1100`). Dispatch on context, never on name.

**`$min`/`$max` are aggregation accumulators here, not update operators.** All three real
occurrences are inside `$group` in `methods/insights.ts` (`:473`, `:593`, `:601`). A first cut of
this table filed them as update operators; there are **zero** update call sites for either.

---

## 3. THE ARCHITECTURE (ADR-0090)

### 3.1 The seam, and why it is the wire protocol

Three seams were possible. Aliasing the `mongodb` package binds us to driver internals
(`client.s.options.hosts[0].host`, `Object.getOwnPropertyNames(Collection.prototype)`).
`mongoose.setDriver()` binds us to mongoose internals (buffering queues, `_getCollection`).
Both put an internals contract into the merge path of the two most actively developed packages we
depend on. **The wire protocol binds us to something versioned, documented, and stable**, and
leaves the real driver and real mongoose running unmodified.

Three facts from the tree made the alternatives unsafe, and they decide arguments you will have
again:

1. **19 suites bypass the model layer entirely** and drive `Model.collection.*` / `connection.db`.
2. **The suites spy on the driver itself.** `migrations/mcpServerNames.spec.ts:72` calls
   `jest.spyOn(mongoose.mongo.Collection.prototype, 'find')`;
   `methods/mcpAuthority.spec.ts:280-283` spies `mongoose.Aggregate.prototype.session` and
   `mongoose.Query.prototype.session`. Under the wire seam `mongoose.mongo` **is** the real
   driver, so these pass unmodified. Under a shim they are spying on us.
3. **L27.** A wire protocol in the merge path is survivable; an internals contract is not.

**Proven before the decision, not after** (spikes, in the session scratchpad):

```
CONNECTED — readyState 1 / INSERTED / FOUND [...]      SPIKE_RESULT=PASS
CONNECTED topology= Single / SESSION_OK / TRANSACTION_OK   SPIKE_TX=PASS
INDEX_CREATED / CROSS_TENANT_INSERT_OK
DUPLICATE_REJECTED name=MongoServerError code=11000    SPIKE_UNIQUE=PASS
```

The handshake was the only genuinely unknown risk and it is retired: real mongoose 8.24.1 + real
mongodb 6.20.0 completed server discovery over a UDS against a ~170-line server and round-tripped
a document. **`SPIKE_TX` proved the transaction command *path*, not isolation semantics** — that
is C6.1's work and §5 sets its bar.

### 3.2 Where the store lives

```
packages/docstore/                  NEW, Tempest-owned, a pnpm workspace member
  package.json                      @tempest/docstore · type: module · engines.node >= 22.13
  src/
    wire/        framing, OP_MSG (kind-0 + kind-1 sections), OP_QUERY, the hello handshake
    command/     find insert update delete aggregate getMore killCursors createIndexes
                 listIndexes dropIndex listCollections drop count distinct findAndModify
                 endSessions ping hello buildInfo
    query/       the 17 query operators, projection, sort
    update/      the 14 update operators, array modifiers, the positional `$`, pipeline updates
    aggregate/   the 11 stages + the 18 expression operators
    index/       the index catalogue: unique / partial / TTL / sparse, over SQLite indices
    storage/     node:sqlite — documents, the JSON mirror, WAL, the schema stamp
    explain/     EXPLAIN QUERY PLAN → Mongo's explain vocabulary (§5.4 — truthful or absent)
    server.ts    the UDS listener
  tests/
```

Conventions, matching `packages/ts-sidecar` (the house pattern for a Node package): TypeScript run
directly via `node --experimental-strip-types`, `vitest run` for tests, `tsc --noEmit` for
typecheck, `strict` + `noUncheckedIndexedAccess` + `exactOptionalPropertyTypes`, **no build step**.
Trap 33: node needs the explicit strip-types flag plus warning suppression.

**`node:sqlite`, not `better-sqlite3`** — unflagged from Node 22.13.0 (verified against that
release's notes) and CI pins `node-version: 22`, which resolves above it. Zero native builds, zero
extra processes. **Add an explicit runtime guard** so a wrong Node fails loudly rather than
mysteriously (L15.3).

### 3.3 One platform store file, and a bridge with a date

`packages/api/src/tempest_api/platformstore.py` already exists — 246 lines, written at C5, whose
docstring says it is shaped *"so C6's Mongoose-methods adapter lands on this exact schema rather
than migrating it."* It is **not** Mongo-compatible: three query shapes (`get` by id,
`find_equal` ordered, `list_ordered`) serving the Tempest agent surface's turns.

1. **`@tempest/docstore` opens the SAME platform SQLite file** and adds its own tables beside
   C5's `documents` table. L33 counts *stores*; a second file is the forbidden third one in
   everything but name.
2. **`platformstore.py` is a BRIDGE, retired at C7**, when LibreChat's conversation/message
   models become the single source of truth. Until then it is frozen except defect fixes. A
   bridge with no removal date is two implementations wearing a trenchcoat.
3. **Fix its missing schema stamp as part of C6.1.** It opens with `CREATE TABLE IF NOT EXISTS`
   and trusts what it finds. Of the tree's four SQLite openers, two stamp (`index/store.py` via
   `meta.schema_version`, `db/local_store.py` via `alembic_version` + a coded revision chain) and
   two do not (`agent/turnlog.py`, `platformstore.py`). This is a gap in half the tree, not a
   house rule one file broke — but C6 puts a **second writer** on that file, which is what turns
   it from survivable into load-bearing. Trap 37: *a schema stamp is a claim, not a fact; every
   open verifies the live schema and repairs or refuses loudly.*

**Pragmas differ per opener — choose deliberately, do not copy-paste.** `index/store.py`: WAL +
`foreign_keys=ON`. `turnlog.py`: WAL + `synchronous=FULL`. `platformstore.py`: WAL +
`synchronous=FULL` + `busy_timeout=30000`, and its `_ensure_wal` READS the journal mode first
because changing it needs an EXCLUSIVE lock that SQLite refuses immediately rather than waiting —
a data-loss bug it already paid for. Read that function before writing yours.

### 3.4 Suggested storage shape (not binding — measure it)

- **Per-namespace tables.** One table per `<db>.<collection>`, so ordinary (non-partial) indices
  work and `drop` is a `DROP TABLE`. This sidesteps the planner problem `platformstore.py`
  documents: *a partial index whose WHERE names a literal collection is unusable when the query
  binds the collection as a parameter.*
- **BSON blob is the source of truth; a JSON mirror is for indexing only.** Matching runs on the
  decoded document so type fidelity is exact (ObjectId vs string, int32 vs double, Date vs ISO
  string). The mirror accelerates candidate selection and must never be the answer.
- **Watch the null/missing gap.** `json_extract` returns SQL NULL for both a JSON `null` and an
  absent field, and SQLite treats NULLs as distinct in a UNIQUE index — Mongo treats missing as
  null and *would* conflict. Use a sentinel, and pin it with a test.
- **Cursors:** materialize a result set keyed by cursor id, with a cap and a reaper.
- **Transactions:** map a Mongo session's transaction onto a SQLite transaction on a dedicated
  connection. WAL gives a reader snapshot isolation, which is what §5.2 demands.

---

## 4. THE HARD CASES — WHERE THIS WILL BITE

Every one of these is a real call site, opened and read. They are listed because a checklist-driven
implementation misses them.

| # | Case | Sites | Why it is hard |
|---|---|---|---|
| 1 | **Positional `$`** | `methods/conversationTag.ts:332` (`'tags.$'`), `methods/user.ts:522` (`'subagentAdmissionFences.$.expiresAt'`) | The update must know WHICH array index the query predicate matched. `user.ts:522` is a compare-and-swap fence asserting `modifiedCount === 1`, so the emulation must preserve exact modified counts. `$[]`/`$[<id>]`/`arrayFilters` are used **zero** times — a real scope reduction. |
| 2 | **`$pull` with a full predicate** | `agent.ts:979,1052,1257`, `config.ts:295`, `skill.ts:1664`, `user.ts:485,536`, `userGroup.ts:1329` | Runs the whole query evaluator per array element, then rewrites the array. `config.ts:295` pulls from a **scalar-string** array using `$regex` as the element predicate — a distinct code path from the subdocument form. |
| 3 | **`$not` + `$elemMatch`** | `user.ts:551`, `skill.ts:1658` | A negated existential over an array of subdocuments. `skill.ts:1658` combines `$in` **and** `$not:$elemMatch` on the same field — "contains any of ids AND contains nothing outside ids". Its own comment says a plain `$pull` would *silently widen* the result, so getting it wrong is an authorization bug, not a perf bug. |
| 4 | **`$not` three-valued semantics** | `agent.ts:641` (`{ $exists: true, $not: { $size: 0 } }`) | Mongo's `$not` also matches documents where the field is **missing**. A naive SQL `NOT` diverges. `agent.ts:641` sidesteps it with `$exists: true`; `user.ts:551` and `skill.ts:1658` do not. |
| 5 | **`$each` + negative `$slice`** | `schedule.ts:1210,1300`, `triggerDelivery.ts:728,774,803` | A ring buffer: append, then keep the LAST N. Must be atomic with the `$push`. |
| 6 | **`$bit`** | `aclEntry.ts:464-472` | Built dynamically (`update.$bit = { permBits: { or: X } }`, later `and: ~Y`), so it appears in **no** key-position sweep. Both sub-operators in one update. |
| 7 | **Aggregation-pipeline updates** | `agent.ts:32-92` (`createEdgeCleanupPipeline`) | A stage array passed to `updateMany`/`findOneAndUpdate`, using `$set` as a *stage* with `$filter`/`$map`/`$let`. A second evaluator surface. |
| 8 | **The tenant-isolation `pre('aggregate')` hook** | `models/plugins/tenantIsolation.ts:158-171` | Unshifts `{ $match: { tenantId } }` into **every** pipeline, applied to 37 schemas. Your `$match` must handle being first, always. |
| 9 | **Arbitrary caller-supplied pipelines** | `aclEntry.ts:557-560` (`aggregateAclEntries`) | A public exported method taking `PipelineStage[]` straight through. The runtime surface is **not** statically bounded by this tree. |
| 10 | **`$facet` with runtime-constructed keys** | `insights.ts:329,353` | The `recentConversations` facet is spread in only when there is no search term. |
| 11 | **`$dateToString` with an IANA timezone** | `insights.ts:359,408,432` | A caller-supplied zone string, validated only against `Intl.DateTimeFormat`. Not a fixed offset. |
| 12 | **Order-dependent `$first`** | `insights.ts:548-552` | Preceded by an explicit `$sort`. `$group` must preserve input order. |
| 13 | **`$group` `_id` in four shapes** | across `insights.ts`, `aclEntry.ts`, `agentCategory.ts` | `null`, a field path, a literal string, and a compound object — one of whose keys is itself a `$dateToString` expression. |
| 14 | **`$lookup`, localField/foreignField only** | `prompt.ts:618`, `insights.ts:299` | The correlated `let`/`pipeline` form is explicitly forbidden upstream with regression tests. Do not implement it. |
| 15 | **`collection.indexes()` throwing is control flow** | `migrations/tenantIndexes.ts:62-70` | The "collection does not exist" skip branch depends on it **throwing**, and two spec cases assert that branch is reached. |
| 16 | **Case-insensitive matching without collation** | `auditLog.ts:86`, plus 12 sites passing a bare JS `RegExp` as a query value | Collation is used zero times; `$regex` + `$options: 'i'` and raw RegExp objects are the mechanism. |
| 17 | **`agent.ts` forwards operators verbatim** | `agent.ts:226-232` | Caller-supplied `$push`/`$pull`/`$addToSet` payloads pass straight into the update. |

---

## 5. WHAT THE TESTS DEMAND BEYOND DATA CORRECTNESS

These are the assertions that fail a store which merely stores things correctly.

### 5.1 Driver-level observability

`migrations/mcpServerNames.spec.ts:69-89` spies `mongoose.mongo.Collection.prototype.find` and
asserts it was called **exactly twice**, every call carrying `readPreference: 'primary'` and
`readConcern: { level: 'majority' }`. `methods/mcpAuthority.spec.ts:498-523` counts driver
operations by name via `mongoose.set('debug', …)` and requires exactly **14**, two of them named
`configs.aggregate` and `agents.aggregate`. **Your store must not change how many operations the
driver issues, nor their names.**

### 5.2 Real transaction isolation

`methods/mcpAuthority.spec.ts:276-311` asserts `startTransaction` was called with
`{ readPreference: 'primary', readConcern: { level: 'snapshot' }, writeConcern: { w: 'majority' } }`,
that a session was attached to **12** queries and **2** aggregations, that per-query `read`/
`readConcern` were never called, and that `find` was issued **7** times with `singleBatch: true`.
Snapshot isolation is what a reader inside a WAL transaction already gets from SQLite — natural,
but *natural is not measured*. Two suites need a replica set for multi-document transactions:
`methods/userGroup.spec.ts` and `methods/mcpAuthority.spec.ts`.

### 5.3 Real constraint enforcement

`migrations/tenantIndexes.spec.ts:189-231`, through the **raw driver**: the same email inserts
under `tenant-a` and `tenant-b`, and a second insert under `tenant-dup` must
`rejects.toThrow(/E11000|duplicate key/)`. The C6.0 spike already showed SQLite's own UNIQUE
constraint surfacing as `MongoServerError code=11000`. `migrations/mcpAuthorityIndexes.spec.ts`
additionally requires `createIndex` to **return the index name** and to be idempotent — calling
the migration twice returns the identical name array.

### 5.4 A truthful explain, or none — this is L4

`methods/aclEntry.spec.ts:1225` calls `.hint(name).explain('queryPlanner')` and requires the
winning plan to contain `IXSCAN` and **not** `COLLSCAN`.
`methods/prompt.getPromptGroup.spec.ts:216` requires an `IDHACK` / `EXPRESS_IXSCAN` /
`IXSCAN{_id:1}` stage, `indexesUsed` containing `_id_`, and `totalDocsExamined <= 1`.

These are satisfiable **honestly**, because SQLite reports its own real plan — verified directly:

```
SEARCH jdoc USING INDEX idx_email (ns=? AND <expr>=?)      → IXSCAN, indexName from the catalogue
SEARCH jdoc USING PRIMARY KEY (ns=? AND id=?)              → IDHACK / IXSCAN {_id: 1}
SCAN jdoc                                                   → COLLSCAN
```

> **Emitting `IXSCAN` because a test wants to see it is a fabricated execution result and L4
> forbids it.** Report what `EXPLAIN QUERY PLAN` actually said, including `COLLSCAN` when nothing
> was indexed — a test that then goes red has found a missing index, which is the entire value of
> the assertion. `.hint()` maps to SQLite's `INDEXED BY`.

---

## 6. THE SUB-PHASES

### C6.1 — `@tempest/docstore`

Build order that keeps you honest: **wire → storage → query → update → index → aggregate →
explain**, each with its own tests before the next. Do not chase the 1,803 until the conformance
suite (below) is green — a large red number tells you nothing about which layer is wrong.

**Gate — upstream's own conformance suite, with its teeth checked first.** LibreChat ships
FerretDB/DocumentDB compat suites in `packages/platform/data/misc/`, URI-driven and documented as
runnable *"against MongoDB (for parity)"*. Three things must be true before they are a gate:

1. **They self-skip to green.** Ten of eleven open with
   `const describeIfFerretDB = FERRETDB_URI ? describe : describe.skip`. Pointed at nothing, jest
   reports success having executed no assertion. **The gate must assert a minimum executed-test
   count**, not merely exit 0.
2. **Two are out of scope and are excluded by name, with the reason recorded**:
   `multiTenancy.ferretdb.spec.ts` shells out (`execSync("docker exec … psql")`) and asserts on
   FerretDB's PostgreSQL catalog; `sharding.ferretdb.spec.ts` is a sharding PoC.
3. **They have no control side yet** — `misc/` is excluded by upstream's own
   `testPathIgnorePatterns`, so they have never run here against real MongoDB either. Take that
   control first (trap 54), or a red here cannot be told from a red anywhere.

The in-scope subset is ~63 tests of exactly the operations upstream found risky on a non-Mongo
backend: `aclBitops` (14), `pullAll` (11), `migrationAntiJoin` (9), `promptLookup` (9),
`randomPrompts` (9), `pullSubdocument` (6), `bulkWrite` (5).

### C6.2 — The 66 suites against the Tempest store

- A **Tempest-owned jest config** maps `mongodb-memory-server` to a shim that boots the store and
  returns its socket URI. The specs stay byte-identical to upstream — **42** call
  `MongoMemoryServer.create()` then `mongoose.connect(uri)` and **2** use `MongoMemoryReplSet`
  (42 + 2 = the 44 store-backed suites; no suite anywhere constructs a raw `MongoClient`).
- Every difference from the C6.0 control is fixed or recorded as a named, reasoned exception.
  **A suite failing in both is not a finding; a suite failing only here is.**
- Report **1,803**, not 2,371 (§2.2).
- Their suites join `make verify-v3` and the CI `node` job.

### C6.3 — The Redis interface

**Far smaller than ADR-0068 §4 implies, and this was measured.** A complete in-memory
implementation already exists upstream behind the same interfaces and is selected automatically
when Redis is off (`api/src/stream/implementations/InMemoryJobStore.ts`; `cacheFactory.ts` gates
on `cacheConfig.USE_REDIS`). Eight independent gates degrade gracefully today; **zero Redis code
runs anywhere right now** because `platform/api` and `platform/server` are not workspace members.

So C6.3 is mostly *verify and wire*, not *build*. What genuinely needs attention: two subsystems
disable rather than degrade (`authUserDocCache` warns and turns off; the schedules engine refuses
to arm), stream **delta coalescing** exists only in the Redis path and is off by default, and two
of 36 `getLogStores` namespaces are Mongo-backed via a hand-written `keyvMongo` that reaches past
Mongoose to the raw driver — which your store must therefore serve.

### C6.4 — Migrations, and the honest replacement for up/down parity

**The plan's gate cannot be satisfied as written and this is the record of why.** Four migrations,
**not one with a down path** — `down`, `reverse`, `rollback`, `revert` appear nowhere in
`src/migrations/`. `tenantIndexes.ts` drops **24** named indexes across 13 collections and, though
`collection.indexes()` hands it the full specs, records only their *names* — irreversible in
principle. Six more one-way scripts live in `packages/platform/config/`. Authoring reverse paths
means editing vendored business logic, which L27 forbids.

Replace it with the two properties that are true and testable:
- **Idempotence** — running a migration twice leaves the same state as once (three of the four
  specs already assert this).
- **Store-level round trip** — a snapshot taken before, restored after, is byte-identical. That
  is what a "down" was actually protecting.

Record it as an ADR amendment. **Do not quietly rewrite the checkbox.**

### C6.5 — Cross-store references grow teeth

The five declared references in `docs/MERGE-CONTRACT.md` implemented as opaque ids. **None of the
five fields exists anywhere in the code today** — every hit is the table itself and a store_check
fixture. `store_check` currently reads only the *declaration*; C6.5 makes it check the declaration
against the live store, which is what its own docstring says C6 is for.

---

## 7. THE GATES

```bash
# the control — the other side of every comparison
./scripts/data-control.sh                                   # 66/66 · 2371 · CONTROL_EXIT=0

# their suites against the Tempest store (C6.2) — NOT `pnpm … test` (watches) and
# NOT `test:ci` (fails: 7 suites cannot load under pnpm's layout)
( cd packages/platform/data && npx jest --config tempest/jest.config.control.mjs --ci )

# the whole tree
TEMPEST_DEV=1 TEMPEST_NO_POWER_PAUSE=1 make verify          # read the logged MAKE_EXIT line
make verify-linux-denominator                               # before EVERY push; ~16 min; do not interleave
uv run python -m tempest.dev.store_check --no-sspl-binaries --no-proof-data-in-document-store
uv run python -m tempest.dev.upstream_check --max-inline-deltas 40 --ledger-complete
uv run python -m tempest.dev.perf_suite --enforce-budgets   # add the document-store p95 row
pnpm install --frozen-lockfile                              # CI's literal command, 5 places
```

**`perf_suite` has 14 budgets and none is the document-store row C6's own gate names** — the
metric keys are `cold_launch_s, merged_cold_launch_s, open_file_ms, keystroke_ms, completion_ms,
idle_rss_mb, idle_cpu_pct` plus seven rows carrying no metric key at all.
Add one: append a frozen `PerfBudget` to the `BUDGETS` tuple naming a `metric` key read from
`bench.json["metrics"][metric]`; p95 is enforced only when `bench.json["samples"][metric]` holds
≥2 raw values. The §10 budget is **p50 5 ms / p95 20 ms**. The C1 proxy measured 0.003–0.036 ms
at p95 over 110k documents — roughly 500× headroom — but that was a micro-benchmark, **not** a
measurement through the vendored Mongoose models. C6 takes the real number.

Note `perf_suite` is **not** in `make verify`, `verify-v3`, or CI. `store_check` **is**.

---

## 8. TRAPS — PAID FOR, DO NOT REPAY

**From C6.0 (2026-08-25):**

1. **A count over a self-documenting tree must strip comments first.** Three index-option counts
   were inflated because upstream's *prose about* partial and TTL indexes counted as declarations.
2. **`pnpm --filter … exec true` prints nothing whether it matches or not** — a "verification"
   that cannot fail. It produced a wrong correction *of* a wrong claim. Use `list`.
3. **A shell `case` on a raw path is a string test, not a path test.** An SSPL guard was bypassed
   by `binaries`, `./mongo-bins`, `packages/../mongo-bins`, and a symlink. Resolve with
   `cd && pwd -P` before comparing.
4. **`store_check` could not see the filename its own downloader writes.** `mongod-arm64-darwin-8.2.6`
   stems to `mongod-arm64-darwin-8`, so a 147 MB SSPL binary could be **committed** under a gate
   printing "L33 holds". Fixed with prefix matching + 4 pins, 3 mutation-proven.
5. **`packageExtensions` cannot declare devDependencies.** Using it for
   `mongodb-memory-server-core` would declare a RUNTIME dependency able to fetch an SSPL mongod.
   Use `publicHoistPattern` — and pnpm 11 reads these from `pnpm-workspace.yaml`, **not**
   `.npmrc` (`.modules.yaml` recorded `[]` when they were written there). Changing them forces a
   full relink that pnpm refuses without a TTY; `CI=true` permits it.
6. **Upstream's `transformIgnorePatterns` assumes npm's FLAT `node_modules`.** Under pnpm the
   first `/node_modules/` segment is `.pnpm`, the lookahead succeeds, and every ESM-only
   dependency goes untransformed.
7. **Do not cite a test by a name you have not opened.** Held all session — which is how §5.2's
   `readConcern: snapshot` requirement was found at all.
8. **A gate that self-skips reports green having run nothing** (§C6.1).
9. **Verify after committing, not before.** The first C6.0 verify ran with two files untracked;
   local green in a tree full of untracked output is not CI green on a fresh checkout (trap 44).

**Inherited and directly relevant:** 13 (owner pushes via GitHub Desktop) · 17
(`TEMPEST_NO_POWER_PAUSE=1` on direct gates) · 18 (pipefail; and in zsh it is `$pipestatus[1]`,
not `${PIPESTATUS[0]}`) · 22 (ubuntu runners ship a live Docker) · 37 (a schema stamp is a claim)
· 40 (a task notification's exit code is the wrapper's — read the logged line) · 42 (reviewers are
read-only) · 43 (100% coverage proves which LINES ran, not which STATES were considered) · 45 (a
guard's argument is not a proof of the guard — write the bypass and RUN it) · 47 (a gate can
measure the wrong thing entirely) · 48 (the review of a fix is not optional because the fix was
careful) · 49 (a diagnosis you did not run is a guess) · 52 (a crash window one line wide can
close a resource forever) · 54 (a differential check must ask both sides under the same
conditions) · 56 (a marker's existence is not its contents, and one OS can hide the difference).

**And the meta-lesson, which is the reason this file exists.** An adversarial review of C6.0 —
a change set whose every gate was already green — reported 21 findings, of which **8 survived**
verification: a bypassable guard, a blind gate, three wrong numbers in an ADR, a gate command
documented without being run, and a proposed gate that would have self-skipped. **Green is where
suspicion starts, not where it ends.** Run the review. Verify its findings adversarially before
acting on them — 13 of the 21 were refuted, and acting on those would have made the tree worse.

---

## 9. DEFINITION OF DONE FOR C6

- [ ] `make verify` exit 0, complete, output pasted — including 100% coverage on `@tempest/docstore`.
- [ ] `make verify-linux-denominator` exit 0, output pasted.
- [ ] **1,803 store-backed tests green** against `@tempest/docstore`, compared row-for-row against
      the C6.0 control; every difference fixed or recorded as a named exception.
- [ ] Upstream's in-scope conformance suites green, **with a minimum executed-test assertion**, and
      their own control taken first.
- [ ] `store_check` green **and extended** to check the five cross-store references against the
      live store.
- [ ] `upstream_check` green with the `packages/platform/data/` delta-ledger row **still empty** —
      `git diff` over `packages/platform` shows zero edits to vendored files.
- [ ] `perf_suite` carries a document-store row, measured **through the vendored Mongoose models**,
      inside the §10 budget (p50 5 ms / p95 20 ms).
- [ ] Migration idempotence + store round-trip, with the ADR amendment recording why up/down
      parity was replaced.
- [ ] Redis interface verified against the in-memory path; the two non-degrading subsystems
      addressed or recorded.
- [ ] `pnpm install --frozen-lockfile` exit 0.
- [ ] An adversarial review run over the whole phase, its findings verified, survivors fixed.
- [ ] `docs/PLAN-V3.md` C6 boxes flipped **in the same commit** as their pasted output.
- [ ] CI green on the runner — not just locally. macOS has hidden a Linux-only defect in this
      repository before (37 failures, ADR-0058).

---

## 10. WHAT IS STILL UNKNOWN — SAY SO RATHER THAN GUESS

1. **Whether the 1,803 are reachable at all** without an exception list. Nobody has run a
   non-Mongo store against them. The honest posture is a measured number with named exceptions,
   not a promise of 100%.
2. **The real p95 through Mongoose.** The C1 figure is a micro-benchmark proxy and says so.
3. **Whether `explain` satisfies both suites** once translated. The mapping is verified to exist;
   the assertions have not been run against it.
4. **The command inventory.** `docs/PLAN-V3.md` C6.0 still carries one unchecked box: record the
   driver's `commandStarted` stream during a control run, so "what must the store implement?"
   becomes a measurement from a real execution of 2,371 tests rather than a reading exercise.
   **That inventory, not this document, is what C6.1 should build against.** Take it early.
5. **Windows and Linux.** Everything in C6.0 was measured on macOS/arm64.
