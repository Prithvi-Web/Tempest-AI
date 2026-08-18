"""`POST /v1/ui-errors` — the webview's crash honesty (HANDOFF-WORLD-CLASS §1.1).

The frontend's window `error`/`unhandledrejection` handlers report here; the record is
scrubbed by the PRODUCTION redaction context before it is written (a UI error message can
embed anything the page was holding — L9 applies to it exactly as to a crash report), then
lands in the same obslog the LOGS view and `tempest diagnose` read. The UI must never fail
silently — and the reporter of failures must itself be unbreakable, so inputs are bounded
(a crash-looping view can spew megabytes) and obslog's never-raise contract absorbs disk
trouble.
"""

from fastapi import APIRouter

from tempest.obslog import get_logger
from tempest.redact import production_context, redact_text
from tempest_api.errors import error_responses
from tempest_api.schemas.uierrors import UiErrorRecorded, UiErrorReport

router = APIRouter(tags=["logs"])

# A generous ceiling for one error, far under the obslog rotation size: everything above it
# is noise from a crash loop, not evidence.
_MAX_FIELD_CHARS = 4000


def _bounded(text: str) -> str:
    if len(text) <= _MAX_FIELD_CHARS:
        return text
    return text[:_MAX_FIELD_CHARS] + " … [truncated]"


@router.post("/v1/ui-errors", operation_id="reportUiError", responses=error_responses(422))
async def report_ui_error(body: UiErrorReport) -> UiErrorRecorded:
    context = production_context()
    parts = [f"[{_bounded(body.source)}]", redact_text(_bounded(body.message), context)]
    if body.stack is not None:
        parts.append(redact_text(_bounded(body.stack), context))
    get_logger("ui").error(" · ".join(parts))
    return UiErrorRecorded(recorded=True)
