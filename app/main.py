"""FastAPI application: bitemporal contract corrections.

Endpoints
---------
``GET  /api/contracts``                      contract numbers with current state
``GET  /api/contracts/{no}``                 full version log + request list
``GET  /api/contracts/{no}/view``            pointwise lookup (business + system time)
``POST /api/contracts``                      create initial version
``POST /api/contracts/{no}/corrections``     apply a correction batch
``GET  /api/health``                         liveness
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .models import MAX_TIME, CorrectionItem, now_utc, parse_iso, to_iso
from .store import Conflict, RequestIdReuse, Store

DB_PATH = Path(__file__).resolve().parent.parent / "contracts.sqlite3"

_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store(DB_PATH)
    return _store


def set_store(store: Store) -> None:
    """Swap the backing store (used by tests and by the seed script)."""
    global _store
    _store = store


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_store()
    yield


app = FastAPI(title="Bitemporal contracts", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from .demo import router as demo_router  # noqa: E402  (router needs get_store)

app.include_router(demo_router)


# --------------------------------------------------------------------- schemas


class RangeModel(BaseModel):
    valid_from: str
    valid_to: str
    amount: float | None = None
    customer: str | None = None

    @field_validator("valid_from", "valid_to")
    @classmethod
    def _instant(cls, value: str) -> str:
        try:
            return to_iso(parse_iso(value))
        except ValueError as exc:  # pragma: no cover - guard
            raise ValueError(f"invalid timestamp: {value!r}") from exc


class CreateBody(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    contract_no: str = Field(min_length=1, max_length=200)
    amount: float
    customer: str = Field(min_length=1, max_length=200)
    valid_from: str
    valid_to: str
    note: str | None = None

    @field_validator("valid_from", "valid_to")
    @classmethod
    def _instant(cls, value: str) -> str:
        try:
            return to_iso(parse_iso(value))
        except ValueError as exc:  # pragma: no cover - guard
            raise ValueError(f"invalid timestamp: {value!r}") from exc


class CorrectionBody(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    base_version_id: int
    ranges: list[RangeModel] = Field(min_length=1, max_length=50)
    note: str | None = None


# ------------------------------------------------------------------- helpers


def _fingerprint_create(body: CreateBody) -> str:
    return json.dumps(
        {
            "contract_no": body.contract_no,
            "amount": body.amount,
            "customer": body.customer,
            "valid_from": body.valid_from,
            "valid_to": body.valid_to,
            "note": body.note,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint_correction(contract_no: str, body: CorrectionBody) -> str:
    return json.dumps(
        {
            "contract_no": contract_no,
            "base_version_id": body.base_version_id,
            "ranges": sorted(
                (
                    {
                        "valid_from": r.valid_from,
                        "valid_to": r.valid_to,
                        "amount": r.amount,
                        "customer": r.customer,
                    }
                    for r in body.ranges
                ),
                key=lambda r: (r["valid_from"], r["valid_to"]),
            ),
            "note": body.note,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _conflict(exc: Conflict) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "conflict", "reasons": exc.reasons},
    )


def _reuse(exc: RequestIdReuse) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "request_id_reused", "reasons": [str(exc)]},
    )


# -------------------------------------------------------------------- routes


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/contracts")
def list_contracts() -> dict:
    store = get_store()
    out = []
    for no in store.contract_numbers():
        current = store.open_versions(no)
        out.append(
            {
                "contract_no": no,
                "current": [v.to_dict() for v in current],
                "requests": [r["request_id"] for r in store.contract_requests(no)],
            }
        )
    return {"contracts": out}


@app.get("/api/contracts/{contract_no}")
def contract_detail(contract_no: str) -> dict:
    store = get_store()
    versions = store.all_versions(contract_no)
    if not versions:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    return {
        "contract_no": contract_no,
        "versions": [v.to_dict() for v in versions],
        "requests": [
            {
                "request_id": r["request_id"],
                "kind": r["kind"],
                "recorded_at": r["recorded_at"],
                "response": json.loads(r["response"]),
            }
            for r in store.contract_requests(contract_no)
        ],
    }


@app.get("/api/contracts/{contract_no}/view")
def contract_view(
    contract_no: str,
    business_time: str = Query(alias="business_at"),
    system_time: str = Query(alias="as_of"),
) -> dict:
    store = get_store()
    try:
        business = to_iso(parse_iso(business_time))
        system = to_iso(parse_iso(system_time))
    except ValueError:
        raise HTTPException(
            status_code=422, detail={"code": "bad_time", "reasons": ["invalid timestamp"]}
        )
    version = store.version_at_resolved(contract_no, business, system)
    return {
        "contract_no": contract_no,
        "business_at": business,
        "as_of": system,
        "row": version.to_dict() if version else None,
    }


@app.get("/api/contracts/{contract_no}/timeline")
def contract_timeline(
    contract_no: str,
    business_from: str = Query(alias="business_from"),
    business_to: str = Query(alias="business_to"),
    as_of_a: str = Query(alias="as_of_a"),
    as_of_b: str = Query(alias="as_of_b"),
) -> dict:
    """Segments for two system-time snapshots over one business window."""
    store = get_store()
    try:
        b_from = to_iso(parse_iso(business_from))
        b_to = to_iso(parse_iso(business_to))
        s_a = to_iso(parse_iso(as_of_a))
        s_b = to_iso(parse_iso(as_of_b))
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "bad_time"})

    def segments(system_time: str):
        rows = store.believed_versions(contract_no, system_time, b_from, b_to)
        rows.sort(key=lambda v: (v.valid_from, v.recorded_from, v.id))
        out = []
        for v in rows:
            lo = max(v.valid_from, parse_iso(b_from))
            hi = min(v.valid_to, parse_iso(b_to))
            if lo >= hi:
                continue
            out.append(
                {
                    **v.to_dict(),
                    "clip_valid_from": to_iso(lo),
                    "clip_valid_to": to_iso(hi),
                }
            )
        return out

    a = segments(s_a)
    b = segments(s_b)
    return {
        "contract_no": contract_no,
        "business_from": b_from,
        "business_to": b_to,
        "as_of_a": s_a,
        "as_of_b": s_b,
        "snapshot_a": a,
        "snapshot_b": b,
        "diff": _diff(a, b, b_from, b_to),
        "current": [v.to_dict() for v in store.open_versions(contract_no)],
    }


def _diff(
    a: list[dict], b: list[dict], b_from: str, b_to: str
) -> list[dict]:
    """Segment-by-segment comparison on the common refinement of both snapshots.

    Every boundary from either snapshot becomes a cut point, so a segment that
    only changed in its middle shows as changed on the middle slice and
    unchanged on the two edges.
    """
    from datetime import datetime

    d_from = datetime.fromisoformat(b_from.replace("Z", "+00:00"))
    d_to = datetime.fromisoformat(b_to.replace("Z", "+00:00"))
    cuts = {d_from, d_to}
    for row in a + b:
        cuts.add(datetime.fromisoformat(row["clip_valid_from"].replace("Z", "+00:00")))
        cuts.add(datetime.fromisoformat(row["clip_valid_to"].replace("Z", "+00:00")))
    ordered = sorted(cuts)

    def lookup(rows: list[dict], lo: datetime) -> dict | None:
        for r in rows:
            rf = datetime.fromisoformat(r["clip_valid_from"].replace("Z", "+00:00"))
            rt = datetime.fromisoformat(r["clip_valid_to"].replace("Z", "+00:00"))
            if rf <= lo < rt:
                return r
        return None

    out = []
    for lo, hi in zip(ordered, ordered[1:]):
        if lo >= hi:
            continue
        ra, rb = lookup(a, lo), lookup(b, lo)
        if ra is None and rb is None:
            continue  # no contract on either snapshot: not a difference
        if ra and rb and ra["amount"] == rb["amount"] and ra["customer"] == rb["customer"]:
            kind = "same"
        elif ra is None:
            kind = "added"
        elif rb is None:
            kind = "removed"
        else:
            kind = "changed"
        out.append(
            {
                "valid_from": to_iso(lo),
                "valid_to": to_iso(hi),
                "kind": kind,
                "a": ra,
                "b": rb,
            }
        )
    return out


@app.post("/api/contracts", status_code=201)
def create_contract(body: CreateBody) -> dict:
    store = get_store()
    try:
        response, replayed = store.create_contract(
            request_id=body.request_id,
            fingerprint=_fingerprint_create(body),
            contract_no=body.contract_no,
            amount=body.amount,
            customer=body.customer,
            valid_from=body.valid_from,
            valid_to=body.valid_to,
            note=body.note,
            recorded_at=to_iso(now_utc()),
        )
    except Conflict as exc:
        raise _conflict(exc)
    except RequestIdReuse as exc:
        raise _reuse(exc)
    return response


@app.post("/api/contracts/{contract_no}/corrections", status_code=201)
def correct_contract(contract_no: str, body: CorrectionBody, request: Request) -> dict:
    store = get_store()
    items = [
        CorrectionItem(
            valid_from=parse_iso(r.valid_from),
            valid_to=parse_iso(r.valid_to),
            amount=r.amount,
            customer=r.customer,
        )
        for r in body.ranges
    ]
    # Optional fixed clock for deterministic demos/tests (X-Recorded-At).
    header = request.headers.get("x-recorded-at")
    recorded_at = to_iso(parse_iso(header)) if header else to_iso(now_utc())
    try:
        response, replayed = store.apply_correction(
            request_id=body.request_id,
            fingerprint=_fingerprint_correction(contract_no, body),
            contract_no=contract_no,
            base_version_id=body.base_version_id,
            items=items,
            note=body.note,
            recorded_at=recorded_at,
        )
    except Conflict as exc:
        raise _conflict(exc)
    except RequestIdReuse as exc:
        raise _reuse(exc)
    return response
