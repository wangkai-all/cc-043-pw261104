"""Demo scenarios and a concurrency-conflict drill.

Scenario metadata lives in the ``demo_scenario`` table written by
``app.seed``. The conflict drill deliberately submits two corrections against
the *same* base version: the first wins, the second must be rejected whole
with 409. The frontend can also drive this manually through the public API.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .models import CorrectionItem, now_utc, parse_iso, to_iso
from .seed import load_scenarios, seed
from .store import Conflict, RequestIdReuse

from .main import get_store

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.get("/scenarios")
def scenarios() -> dict:
    store = get_store()
    return {"scenarios": load_scenarios(store)}


@router.post("/reset")
def reset_demo() -> dict:
    """Re-run the fixed seed so repeated drills start from the same state."""
    store = get_store()
    return {"scenarios": seed(store)}


class ConflictDrill(BaseModel):
    contract_no: str
    base_version_id: int


@router.post("/conflict")
def conflict_drill(body: ConflictDrill) -> dict:
    """Submit two corrections against the same base, then report both outcomes.

    The first request lands (and closes the base); the second is a genuine
    stale-base conflict. Nothing from the losing batch is written.
    """
    store = get_store()
    base = store.version(body.base_version_id)
    if base is None or base.contract_no != body.contract_no:
        raise HTTPException(status_code=404, detail={"code": "base_not_found"})
    if not base.is_current():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "base_stale",
                "reasons": [f"base version {base.id} is already closed; pick a current version"],
            },
        )

    # Each attempt needs a business slice with real width. A repeatedly
    # drilled base shrinks; refuse rather than emit an empty interval.
    span = base.valid_to - base.valid_from
    if span.total_seconds() < 3 * 60:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "base_too_short",
                "reasons": [
                    f"base version {base.id} spans only {int(span.total_seconds())}s;"
                    " reset the demo to drill again"
                ],
            },
        )

    stamp = to_iso(now_utc())
    lo, hi = base.valid_from, base.valid_to
    third = span / 3
    mid_a = lo + third
    mid_b = hi - third

    request_a = f"DRILL-A-{body.contract_no}-{uuid.uuid4().hex[:8]}"
    request_b = f"DRILL-B-{body.contract_no}-{uuid.uuid4().hex[:8]}"
    results = []

    def attempt(request_id: str, amount: float, start, end) -> dict:
        try:
            response, replayed = store.apply_correction(
                request_id=request_id,
                fingerprint=json.dumps([body.contract_no, body.base_version_id, request_id]),
                contract_no=body.contract_no,
                base_version_id=body.base_version_id,
                items=[CorrectionItem(valid_from=start, valid_to=end, amount=amount, customer=None)],
                note="并发冲突演练",
                recorded_at=stamp,
            )
            return {"request_id": request_id, "status": "applied", "response": response}
        except Conflict as exc:
            return {
                "request_id": request_id,
                "status": "conflict",
                "reasons": exc.reasons,
                "written": 0,
            }
        except RequestIdReuse as exc:
            return {"request_id": request_id, "status": "request_id_reused", "reasons": [str(exc)]}

    results.append(attempt(request_a, base.amount + 5000.0, lo, mid_a))
    results.append(attempt(request_b, base.amount + 9000.0, mid_b, hi))

    return {
        "contract_no": body.contract_no,
        "base_version_id": body.base_version_id,
        "recorded_at": stamp,
        "outcomes": results,
        "current": [v.to_dict() for v in store.open_versions(body.contract_no)],
        "requests": [r["request_id"] for r in store.contract_requests(body.contract_no)],
    }
