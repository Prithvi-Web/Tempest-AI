# Third-Party Licenses

Every third-party work Tempest copies, adapts, or derives from is recorded here **at the moment
of adoption**, not at release. Missing attribution is an avoidable legal problem discovered at
the worst possible time — enterprise procurement diligence (v2 failure mode 10).

> **Gate status, stated honestly:** `python -m tempest.dev.license_check --third-party-notices`
> — which will enforce this file's presence and its coverage of every adoption entry in
> `docs/DECISIONS.md` — **is built in Phase 19 and does not exist yet.** Until it does, this
> file is maintained by discipline alone, which is precisely the weaker guarantee that the gate
> exists to replace. Until Phase 19 lands, treat any adoption commit as incomplete without a
> matching entry here.

**Scope note.** Reading a project to learn how it solved a problem creates no obligation.
Copying or closely adapting its code does. This file lists both categories explicitly, so a
reviewer can tell which is which without reading git history.

---

## LibreChat

- **Upstream:** https://github.com/danny-avila/LibreChat
- **License:** MIT
- **Adoption status:** **REFERENCE ONLY — no code copied as of 2026-08-18.**
- **Adoption decision record:** `docs/DECISIONS.md` ADR-0038; capabilities and their
  proof-native wiring in `docs/PLATFORM-V2.md` (P1–P14).

**What this means today.** Tempest is Rust/Tauri + Python + SQLite, local-first. LibreChat is
Node/Express + React + MongoDB, deployed as a multi-user web service. Their code cannot be
vendored into this stack and will not be. P1–P14 adopt *capabilities* — the problems they have
already solved well (multi-provider abstraction, resumable streaming, MCP client behavior) are
studied as a reference implementation, then re-implemented in Tempest's stack and subordinated
to the proof engine (L25).

**If that ever changes** — if any Tempest module is copied or closely adapted from LibreChat
source — then at that moment: (1) the module is named in the table below with its upstream
path and commit, (2) the MIT notice below is preserved in the derived file's header, and
(3) an ADR records the derivation. `license_check` fails if an ADR marks a module as derived
and this file does not list it.

| Tempest module | Derived from (upstream path @ commit) | Notes |
|---|---|---|
| *(none)* | — | Reference-only as of 2026-08-18 |

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

```markdown
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
```

---

## Vendored corpus code (pre-existing, v1)

`corpus/impure/` vendors small permissively-licensed (MIT/BSD/Apache) functions from real
open-source repositories so the determinism gate is hermetic and offline. **Each vendored file
carries its own attribution header** naming the source repository, commit, and license; GPL and
other copyleft code is excluded by policy. See `docs/QUESTIONS.md` Q5. Those per-file headers
are the authoritative attribution for that directory and are checked by `license_check`
alongside this file.
