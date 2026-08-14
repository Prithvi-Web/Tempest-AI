# Sandbox Escape Review (Phase 7)

Threat model: **user code is hostile by assumption** (master spec §14.8). Tempest executes
arbitrary repo code; the sandbox is the only thing between that code and the host.

## Execution surfaces and their containment

| Surface | Containment | Notes |
|---|---|---|
| Target code (user repos) | `DockerSandbox` only | `--network none`, `--read-only` rootfs, repo mounted `:ro`, scratch volume, `--tmpfs /tmp`, `--memory`, `--pids-limit`, `--cap-drop ALL`, `--security-opt no-new-privileges`, seccomp allowlist (`docker/seccomp-tempest.json`), non-root UID 10001 |
| First-party fixtures/corpus | `ProcessSandbox` | Reachable ONLY with the committed repo marker + `TEMPEST_DEV=1` (ADR-0008). Scrubbed env (8 vars), no inherited fds, session isolation (`start_new_session`), `RLIMIT_CPU=120s`, `RLIMIT_CORE=0`, `RLIMIT_AS` on Linux; per-input wall timeout with SIGKILL of the process group |
| Adapter/probe code | Same sandbox as the target | Synthesis is validated by execution inside the sandbox — proposed adapter code never runs in the runner process |
| Introspection | Same sandbox | `inspect`/`typing` run in the worker, not the runner |

## Reviewed risks

1. **Runner-side evaluation of worker output.** The worker sends JSON only; the runner never
   `eval`s worker-provided strings. Input literals flow runner→worker, parsed by
   `parse_input_literal` (AST-validated to literals + nan/inf, empty `__builtins__`). Reviewed:
   no `pickle`, no `eval` of foreign data anywhere in `packages/engine`.
2. **Repro scripts.** Generated from our own template with `repr()`-injected strings; they are
   artifacts the USER chooses to run inside their repo — same trust as the repo itself.
3. **Annotation strings** from user code are AST-validated (`_is_type_expression`) before
   evaluation against a fixed builtin-types namespace; dunder/call/attribute nodes are rejected
   (tested with `__import__('os')`-style payloads).
4. **Scratch mounts.** Worker/canonical/shims are copied INTO scratch before the sandbox starts;
   user code can overwrite its own scratch copy mid-run but that only affects its own process,
   which is already fully untrusted.
5. **ProcessSandbox residual risk (dev machines).** No filesystem isolation beyond cwd/env — this
   is exactly why it is fenced to first-party fixtures by marker+env (ADR-0003/0008) and
   unreachable for arbitrary repos. Verified by test:
   `test_prove_without_sandbox_is_unproven_never_unsandboxed`.
6. **Timing side-channels / resource abuse.** Wall-clock per-input kill + CPU rlimit +
   (container) memory/pids caps. OOM inside the container is observed as a crash, not a host
   event.

## Outstanding (tracked, not hidden)

- [ ] **Container-leg execution review on a Docker-equipped machine** (this dev host has no
      Docker — ADR-0003): verify the seccomp allowlist boots CPython 3.12 on aarch64+x86_64,
      probe `/proc` visibility, confirm no capability leaks (`capsh --print` inside).
- [ ] Container-leg path translation (argv + job-file host→`/repo`,`/scratch` mapping,
      `translate_command`/`translate_job`) implemented but not yet executed against a live
      daemon — unit-tested pure-functionally only.
- [ ] Escape-attempt corpus (fork bombs, fd exhaustion, `/proc/self/mem`, unix sockets) run in CI
      where Docker exists.
- [ ] Decide policy for record-mode egress on user repos (currently: none — no network in the
      sandbox, net calls fail honestly; see ADR-0010 §3).
