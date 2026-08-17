"""Bundle ingestion: `.tempest.zip` → rows (master spec §7/§8).

One producer, many renderers: the zip is parsed with the engine's own `read_bundle` semantics and
fanned out verbatim. The API never re-derives verdicts (Law L2). Integrity (BUNDLE_SCHEMA.md) is
enforced before any row is written, and the whole fan-out shares one transaction — a rejected
bundle writes nothing.
"""

import io
import json
import tempfile
import zipfile
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from tempest.bundle.bundle import RunBundle, read_bundle
from tempest.model import BUNDLE_SCHEMA_VERSION
from tempest_api.bundlestore import bundle_store, prune_over_budget
from tempest_api.db.models import Divergence, Run, Target
from tempest_api.errors import ApiError
from tempest_api.ledger import append_run_event
from tempest_api.schemas.enums import ErrorCode, RunStatus

# Review m7: bounded extraction — a hostile sync peer must not exhaust a team server.
# Real bundles are a few MB; the caps are two orders of magnitude above any legitimate one.
_MAX_DECLARED_BYTES = 200 * 1024 * 1024
_MAX_MEMBERS = 10_000


def parse_bundle_zip(data: bytes) -> RunBundle:
    """Extract a `.tempest.zip` to a temp dir and read it with the engine's reader."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ApiError(
            400,
            ErrorCode.BUNDLE_INVALID,
            f"upload is not a readable zip archive: {exc}",
        ) from exc
    members = archive.infolist()
    declared = sum(member.file_size for member in members)
    if len(members) > _MAX_MEMBERS or declared > _MAX_DECLARED_BYTES:
        raise ApiError(
            400,
            ErrorCode.BUNDLE_INVALID,
            f"bundle declares {len(members)} members / {declared} bytes decompressed — "
            "beyond any legitimate bundle; refusing before extraction",
            {"members": len(members), "declared_bytes": declared},
        )
    with tempfile.TemporaryDirectory(prefix="tempest-bundle-") as tmp:
        dest = Path(tmp)
        _safe_extract(archive, dest)
        _check_schema_version(dest)
        try:
            return read_bundle(dest)
        except (KeyError, ValueError, TypeError, OSError) as exc:
            raise ApiError(
                400,
                ErrorCode.BUNDLE_INVALID,
                f"bundle does not match schema v{BUNDLE_SCHEMA_VERSION} "
                f"(docs/BUNDLE_SCHEMA.md): {exc}",
            ) from exc


def _safe_extract(archive: zipfile.ZipFile, dest: Path) -> None:
    resolved_dest = dest.resolve()
    for member in archive.infolist():
        target = (dest / member.filename).resolve()
        if not target.is_relative_to(resolved_dest):
            raise ApiError(
                400,
                ErrorCode.BUNDLE_INVALID,
                f"bundle zip contains an unsafe path: {member.filename!r}",
            )
    archive.extractall(dest)


def _check_schema_version(bundle_dir: Path) -> None:
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ApiError(400, ErrorCode.BUNDLE_INVALID, "bundle zip has no manifest.json at its root")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        schema_version = int(manifest["schema_version"])
    except (ValueError, TypeError, KeyError, UnicodeDecodeError) as exc:
        raise ApiError(
            400, ErrorCode.BUNDLE_INVALID, f"manifest.json is unreadable: {exc}"
        ) from exc
    if schema_version > BUNDLE_SCHEMA_VERSION:
        raise ApiError(
            400,
            ErrorCode.BUNDLE_SCHEMA_UNSUPPORTED,
            f"bundle schema v{schema_version} is newer than this API understands "
            f"(v{BUNDLE_SCHEMA_VERSION}) — upgrade the server before uploading",
        )


def check_bundle_integrity(bundle: RunBundle) -> None:
    """Mirror of the writer's §7 rules for hand-corrupted uploads: every divergence must carry a
    minimized input and an existing repro script."""
    for target in bundle.targets:
        where = f"{target.module}.{target.qualname}"
        for d in target.divergences:
            if d.minimized_args is None or d.minimized_kwargs is None:
                raise ApiError(
                    400,
                    ErrorCode.BUNDLE_INVALID,
                    f"divergence in {where} has no minimized input — "
                    "a divergence without its evidence is not ingestible (BUNDLE_SCHEMA.md rule 1)",
                    {"target": where},
                )
            if d.repro_filename is None:
                raise ApiError(
                    400,
                    ErrorCode.BUNDLE_INVALID,
                    f"divergence in {where} has no repro script (BUNDLE_SCHEMA.md rule 1)",
                    {"target": where},
                )
            if d.repro_filename not in bundle.repro_scripts:
                raise ApiError(
                    400,
                    ErrorCode.BUNDLE_INVALID,
                    f"repro script {d.repro_filename!r} referenced by {where} "
                    "is missing from the bundle (BUNDLE_SCHEMA.md rule 2)",
                    {"target": where, "repro_filename": d.repro_filename},
                )


def check_bundle_matches_run(bundle: RunBundle, run: Run) -> None:
    manifest = bundle.manifest
    mismatches = {
        field: {"run": run_value, "bundle": bundle_value}
        for field, run_value, bundle_value in (
            ("repo", run.repo.name, manifest.repo),
            ("base_sha", run.base_sha, manifest.base_sha),
            ("head_sha", run.head_sha, manifest.head_sha),
        )
        if run_value != bundle_value
    }
    if mismatches:
        raise ApiError(
            400,
            ErrorCode.BUNDLE_MISMATCH,
            "bundle manifest does not describe this run — upload it to the run created for "
            f"these revisions (mismatched: {', '.join(sorted(mismatches))})",
            {"mismatches": mismatches},
        )


async def ingest_bundle(session: AsyncSession, run: Run, bundle: RunBundle) -> None:
    """Fan a validated bundle out into runs/targets/divergences (+ one run_event). The caller
    commits; anything raised before that leaves the database untouched."""
    if run.status is not RunStatus.PENDING:
        raise ApiError(
            409,
            ErrorCode.RUN_NOT_PENDING,
            f"run {run.id} already has an ingested bundle (status {run.status}) — "
            "create a new run for a new bundle",
        )
    check_bundle_integrity(bundle)
    check_bundle_matches_run(bundle, run)

    manifest = bundle.manifest
    run.status = RunStatus.COMPLETE
    run.verdict = manifest.verdict
    run.schema_version = manifest.schema_version
    run.engine_version = manifest.engine_version
    run.bundle_created_at = manifest.created_at
    run.base_deps = manifest.base_deps
    run.head_deps = manifest.head_deps
    run.budget_max_inputs = manifest.budget_max_inputs
    run.sandbox_tier = manifest.sandbox_tier
    run.sandbox_assurance = manifest.sandbox_assurance

    divergence_total = 0
    for position, record in enumerate(bundle.targets):
        target = Target(
            run_id=run.id,
            position=position,
            file_path=record.file_path,
            module=record.module,
            qualname=record.qualname,
            lang=record.lang,
            classification=record.classification,
            verdict=record.verdict,
            reason_code=record.reason_code,
            reason_detail=record.reason_detail,
            inputs_run=record.inputs_run,
            equivalent_inputs=record.equivalent_inputs,
            unprovable_inputs=record.unprovable_inputs,
            changed_line_coverage=record.changed_line_coverage,
        )
        session.add(target)
        await session.flush()
        for d_position, d in enumerate(record.divergences):
            # check_bundle_integrity established all three; assertions narrow the Optional types.
            assert d.minimized_args is not None and d.minimized_kwargs is not None
            assert d.repro_filename is not None
            divergence_total += 1
            session.add(
                Divergence(
                    target_id=target.id,
                    position=d_position,
                    divergence_class=d.divergence_class,
                    severity=d.severity,
                    detail=d.detail,
                    args_literal=d.args_literal,
                    kwargs_literal=d.kwargs_literal,
                    minimized_args=d.minimized_args,
                    minimized_kwargs=d.minimized_kwargs,
                    shrink_path=list(d.shrink_path),
                    base_summary=d.base_summary,
                    head_summary=d.head_summary,
                    repro_filename=d.repro_filename,
                    repro_script=bundle.repro_scripts[d.repro_filename],
                    ai_narrative=d.ai_narrative,
                )
            )

    await append_run_event(
        session,
        run.id,
        "bundle.ingested",
        stage="ingested",
        message=(
            f"bundle ingested: verdict {manifest.verdict.value}, "
            f"{len(bundle.targets)} targets, {divergence_total} divergences"
        ),
        extra={
            "verdict": manifest.verdict.value,
            "targets": len(bundle.targets),
            "divergences": divergence_total,
        },
    )


async def ingest_zip_bytes(session: AsyncSession, run: Run, data: bytes) -> RunBundle:
    """THE ingestion code path — parse, integrity, run-match, fan-out, then blob storage +
    budget pruning (ADR-0017) — shared verbatim by the upload endpoint and the local prove
    worker. Pruning deletes ROWS in this transaction only; the pruned digests are stashed in
    `session.info["pruned_digests"]` for the caller to garbage-collect AFTER commit against
    committed truth (review C1). Returns the parsed bundle for reporting."""
    bundle = parse_bundle_zip(data)
    await ingest_bundle(session, run, bundle)
    store = bundle_store()
    run.bundle_digest = store.put(data)
    await session.flush()
    session.info["pruned_digests"] = await prune_over_budget(session, store, protect_run_id=run.id)
    return bundle
