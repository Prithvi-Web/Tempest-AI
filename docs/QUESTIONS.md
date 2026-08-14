# §16 Question List — genuinely ambiguous points, with the defaults this build chose

Per ADR-0002 (autonomous session), each question is answered with a recorded default instead of
blocking. Overturn any of these and the affected surface is small and isolated.

**Q1. Which LLM provider/key powers Stage-3 adapter synthesis, given the CLI must also run fully
offline?**
→ Default: deterministic type-driven synthesis always; Anthropic `claude-sonnet-5` used only when
the **end user** supplies their own `ANTHROPIC_API_KEY` (strict BYOK — the project owner never
pays for anyone's tokens; no key ships with Tempest). (ADR-0006)

**Q2. What happens on machines without Docker, given Law L6 forbids unsandboxed execution?**
→ Default: `UNPROVEN(SANDBOX_UNAVAILABLE)` for user repos; a process-isolation backend exists only
for Tempest's own trusted fixtures/corpus so gates can run here; CI enforces the Docker path.
(ADR-0003)

**Q3. GitHub repo name/visibility, and how does it get published without `gh` auth?**
→ Default: local repo `tempest`, published by the user via GitHub Desktop (their standing
workflow); visibility is the user's choice at publish time. Phase 6's live-PR gate runs
post-publication. (ADR-0005)

**Q4. GitHub OAuth app credentials for the dashboard — who registers them?**
→ Default: real Auth.js wiring with a loud dev-mode credential for local compose; the user
registers the OAuth app (Settings → Developer settings → OAuth Apps) before any deployment and
fills `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET`. (ADR-0007)

**Q5. The 30-function Phase-2 corpus must be "drawn from real open-source repos" — vendored code or
referenced checkouts?**
→ Default: vendor small permissively-licensed (MIT/BSD/Apache) functions with per-file attribution
headers (repo, commit, license) into `corpus/impure/`, so the gate is hermetic and offline. GPL
code is excluded. (ADR to be appended when the corpus lands in Phase 2.)

**Q6. "Node 22" is pinned but the dev machine runs Node 24.**
→ Default: `engines >=22`, CI pins 22. (ADR-0004)

**Q7. §16 says "produce the docs, then wait" — wait for whom in an autonomous run?**
→ Default: don't block; record the answers here and proceed. (ADR-0002)
