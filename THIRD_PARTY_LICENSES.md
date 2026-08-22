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
- **Adoption status:** **CODE DERIVED — VENDORED WHOLESALE** (v3 convergence, 2026-08-21).
  Thirteen upstream trees vendored at commit `d602452c05ed767315a753264f02368c10f31e19` into
  `packages/platform/`, byte-for-byte except the six brand-asset replacements recorded in
  `packages/platform/UPSTREAM.md` (trademarks are not licensed by MIT). Upstream's `LICENSE`
  travels with the vendored work at `packages/platform/LICENSE`.
- **Adoption decision record:** `docs/DECISIONS.md` ADR-0064 (LibreChat is the base) and
  ADR-0063…ADR-0076; per-subsystem dispositions in `docs/MERGE-CONTRACT.md`; original scope
  ADR-0038 and its amendment, refusals overturned per the pointer note there.

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

> **v3 note (2026-08-21).** The paragraph above described the v2 posture (adopt capabilities,
> re-implement in our stack). ADR-0064 changed the shape: the Node/React platform is now
> vendored **whole** and runs as supervised sidecars/the webview of the desktop app — the code
> does not need to "typecheck across the gap" because it keeps its own stack. L25's test is
> superseded by L30's classification for the v3 scope (`CLAUDE.md`).

**Attribution mechanics for wholesale-vendored trees.** The thirteen trees below are copied
verbatim, so the notice travels the way upstream itself carries it: the complete MIT licence
with LibreChat's copyright line at the vendored root (`packages/platform/LICENSE`), plus this
section and the per-tree derivation rows. **Per-file headers are added only to files
individually copied or closely adapted into Tempest's own trees** (outside
`packages/platform/`) — inserting a header into ~4,200 vendored files would be a repo-wide
inline edit that destroys the byte-for-byte property L27's upstream mergeability depends on,
while adding nothing the tree-root licence does not already grant.

| Tempest module | Derived from (upstream path @ commit) | Notes |
|---|---|---|
| `packages/platform/server/**` | `api/**` @ `d602452c` | vendored unmodified |
| `packages/platform/api/**` | `packages/api/**` @ `d602452c` | vendored unmodified |
| `packages/platform/data/**` | `packages/data-schemas/**` @ `d602452c` | vendored unmodified, byte-for-byte (ADR-0068) |
| `packages/platform/provider/**` | `packages/data-provider/**` @ `d602452c` | vendored unmodified |
| `packages/platform/client/**` | `client/**` @ `d602452c` | unmodified except 6 brand-asset placeholder replacements (`packages/platform/UPSTREAM.md`) |
| `packages/platform/client-pkg/**` | `packages/client/**` @ `d602452c` | vendored unmodified |
| `packages/platform/e2e/**` | `e2e/**` @ `d602452c` | vendored unmodified |
| `packages/platform/config/**` | `config/**` @ `d602452c` | vendored unmodified |
| `packages/platform/search/**` | `search/**` @ `d602452c` | vendored unmodified |
| `packages/platform/otel/**` | `otel/**` @ `d602452c` | vendored unmodified |
| `packages/platform/redis-config/**` | `redis-config/**` @ `d602452c` | vendored unmodified |
| `packages/platform/skill/**` | `skill/**` @ `d602452c` | vendored unmodified |
| `packages/platform/LICENSE` | `LICENSE` @ `d602452c` | upstream MIT text, travels with the work |

**LibreChat's own dependency obligations.** At the adopted commit upstream ships no
third-party-licences file of its own; its dependency obligations are declared in the
`package.json` manifests, which travel inside the vendored trees, and resolve to each
dependency's own licence at install time. Nothing in the vendored source embeds another
project's code without its own notice.

**Trademarks are not licensed.** The MIT grant covers code, not brand. LibreChat's own visual
identity (logo, favicons, touch icons) was **stripped in the vendoring commit** — replaced with
neutral placeholders, itemized in `packages/platform/UPSTREAM.md` — so no LibreChat mark, logo,
or trade dress exists in the tree or will ship in the product. The LibreChat *name* necessarily
appears inside vendored source (package identifiers, imports, this attribution — uses the MIT
notice itself requires); it is never used as product branding, and nothing implies endorsement
or affiliation. Remaining text-level name surfaces inside the unshipped client are replaced in
C3's identity pass before the client is ever built or shipped.

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

## LobeHub Icons

- **Upstream:** https://github.com/lobehub/lobe-icons (published as `@lobehub/icons-static-svg`)
- **License:** MIT
- **Adoption status:** **CODE DERIVED** (provider badges, 2026-08-22). Fifteen AI-provider brand
  glyphs were adapted from the `@lobehub/icons-static-svg@1.94.0` package — recomposed onto
  Tempest's own circular badge, mono glyphs re-inked, gradient ids namespaced — and shipped as
  the model-selector icons. Each derived file carries a header naming this source. The
  `llamacpp.svg` glyph is an original Tempest mark, not from LobeHub.
- **Adoption decision record:** nominative use of provider marks per the C1 posture recorded in
  `packages/platform/UPSTREAM.md` (brand marks identify their providers; they are not LibreChat
  or Tempest trade dress, and nothing implies endorsement by the named providers).

| Tempest module | Derived from (upstream path @ commit) | Notes |
|---|---|---|
| `packages/platform/client/tempest/assets/providers/*.svg` (15 of 16) | `@lobehub/icons-static-svg@1.94.0` `icons/*.svg` | glyphs recomposed on a Tempest badge; `llamacpp.svg` is original |

**Trademark note.** The glyphs depict third-party brand marks (OpenAI, Google, Mistral, and so
on). They are used **nominatively** — solely to label each provider's own row in the model
selector, exactly as the upstream icon set intends — never as Tempest branding. The MIT grant
below covers the icon *code*; the marks remain their owners' property.

**License text, reproduced in full:**

```
MIT License

Copyright (c) 2023 LobeHub

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

*(Retrieved from the upstream `LICENSE` file, 2026-08-22.)*

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
