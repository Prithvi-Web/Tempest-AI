# Third-Party Licenses

Every third-party work Tempest copies, adapts, or derives from is recorded here **at the moment
of adoption**, not at release. Missing attribution is an avoidable legal problem discovered at
the worst possible time — enterprise procurement diligence (v2 failure mode 10).

> **Enforced, not merely intended:** `python -m tempest.dev.license_check --third-party-notices`
> runs inside `make verify` and in CI. It fails the build if Tempest's own MIT LICENSE is
> missing or lacks a copyright holder, if package metadata omits the licence, if a project
> named here does not reproduce its licence text, if a section marked `CODE DERIVED` names
> no derived module, or if a named project is not credited in the README.

**Scope note.** Reading a project to learn how it solved a problem creates no obligation.
Copying or closely adapting its code does. This file lists both categories explicitly, so a
reviewer can tell which is which without reading git history.

---

## LibreChat

- **Upstream:** https://github.com/danny-avila/LibreChat
- **License:** MIT
- **Adoption status:** **COPYING AUTHORIZED** (owner decision, 2026-08-18) — currently
  **no code copied**; the derivation table below is empty and says so.
- **Adoption decision record:** `docs/DECISIONS.md` ADR-0038 and its amendment; capabilities
  and their proof-native wiring in `docs/PLATFORM-V2.md` (P1–P14).

**What this means.** LibreChat is MIT, so copying and adapting its code is permitted — for
commercial use, with modification, and with no copyleft obligation. The owner has authorized
doing so. **MIT is permissive, not obligation-free:** any copied or closely-adapted code must
carry the copyright notice and licence text with it. The mechanics, which are not optional:

1. The derived Tempest module is added to the table below with its **upstream path and commit**.
2. The derived file carries a header comment naming LibreChat, the upstream path, and MIT.
3. The MIT notice reproduced at the end of this section stays intact.
4. `license_check` fails the build if this section is marked `CODE DERIVED` and the table names
   no module — the status line is a claim, the table is the fact behind it.

**The practical reality, stated so nobody plans around a fantasy.** LibreChat is
Node/Express + React + MongoDB, deployed as a multi-user web service; Tempest is
Rust/Tauri + Python + SQLite, local-first. Whole-file vendoring mostly does not typecheck across
that gap — a JavaScript Express route handler is not a Rust Tauri command. So in practice the
adoption is: **copy what ports (schemas, config shapes, protocol handling, prompt/tool
formats, algorithms), re-implement what doesn't, and attribute either way.** The React webview
is the one place where near-verbatim reuse is genuinely likely, and it is the place to be most
careful about notices. L25 still governs: whatever arrives must be subordinated to the proof
engine, never bolted on as a parallel product.

| Tempest module | Derived from (upstream path @ commit) | Notes |
|---|---|---|
| *(none yet)* | — | copying authorized 2026-08-18; nothing derived so far |

**Trademarks are not licensed.** The MIT grant covers code, not brand. No LibreChat name, mark,
logo, or visual identity appears anywhere in Tempest, and nothing implies endorsement or
affiliation.

**Related repository, separately licensed.** LibreChat's RAG API lives in its own repository
(`danny-avila/rag_api`) under its own terms. Nothing from it is adopted; if that changes, it
gets its own section here after an independent license review — the MIT grant on LibreChat does
not extend to it.

**License text, reproduced in full:**

```
MIT License

Copyright (c) 2026 LibreChat

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

*(Retrieved from the upstream `LICENSE` file, 2026-08-18. If upstream amends the copyright
line, this reproduction is refreshed and the change noted here.)*

---

## Stub for future adoptions

Copy this block for every new third-party work. An entry lands in the same commit as the code
that adopts it — never later.

````markdown
## <Project>

- **Upstream:** <url>
- **License:** <SPDX id>
- **Adoption status:** REFERENCE ONLY | CODE DERIVED
- **Adoption decision record:** docs/DECISIONS.md ADR-XXXX

| Tempest module | Derived from (upstream path @ commit) | Notes |
|---|---|---|
|  |  |  |

**License text, reproduced in full:**

```
<verbatim license text>
```
````

---

## The corpus is NOT vendored code (correcting a plausible assumption)

`docs/QUESTIONS.md` Q5 planned to vendor permissively-licensed functions into `corpus/impure/`
with per-file attribution headers. **That plan was overridden by ADR-0010 and never happened.**
The 30 corpus functions are **hand-written faithful replicas of named real-world idioms** — each
docstring cites the pattern it replicates (k8s health probes, retry-after-404, REST pagination,
docker-secrets env-or-file, lockfile checksums, backoff jitter) — not copies of third-party
source. Vendoring would have dragged licence files and dead logic into the repo when the
corpus's whole value is its IO *shape*.

So there is **no third-party copyright in `corpus/impure/`** and nothing to attribute there. This
section exists because "corpus drawn from real open-source repos" reads like vendoring, and a
future reviewer should be able to settle the question here instead of guessing. If the corpus
ever does grow by real-repo extracts under permissive licences (ADR-0010 leaves that door open),
each extract gets an attribution header **and** a section in this file, in the same commit.
