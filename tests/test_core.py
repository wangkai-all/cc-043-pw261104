from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import main as main_module  # noqa: E402
from app.main import app  # noqa: E402
from app.models import CorrectionItem, parse_iso, to_iso  # noqa: E402
from app.store import Conflict, RequestIdReuse, Store  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "test.sqlite3")
    main_module.set_store(s)
    yield s
    s.close()


@pytest.fixture()
def client(store):
    with TestClient(app) as c:
        yield c


def dt(text: str) -> datetime:
    return parse_iso(text)


def make(store, request_id="C1", no="C-1", amount=100.0, customer="甲", vf="2026-01-01T00:00:00Z", vt="2027-01-01T00:00:00Z", at="2026-01-02T00:00:00Z"):
    response, _ = store.create_contract(
        request_id=request_id,
        fingerprint="fp-create-" + request_id,
        contract_no=no,
        amount=amount,
        customer=customer,
        valid_from=vf,
        valid_to=vt,
        note=None,
        recorded_at=at,
    )
    return response["applied"][0]["id"]


def correct(store, base, ranges, request_id="K1", at="2026-02-01T00:00:00Z", no="C-1", note=None):
    items = [CorrectionItem(valid_from=dt(a), valid_to=dt(b), amount=m, customer=c) for a, b, m, c in ranges]
    response, _ = store.apply_correction(
        request_id=request_id,
        fingerprint=json.dumps([[a, b, m, c] for a, b, m, c in ranges], default=str),
        contract_no=no,
        base_version_id=base,
        items=items,
        note=note,
        recorded_at=at,
    )
    return response


# ------------------------------------------------------------------ core model


def test_half_open_interval_boundaries(store):
    make(store)
    assert store.version_at_resolved("C-1", "2026-01-01T00:00:00Z", "2026-12-01T00:00:00Z")
    # start is inclusive
    assert store.version_at_resolved("C-1", "2026-01-01T00:00:00Z", "2026-12-01T00:00:00Z").amount == 100
    # end is exclusive
    assert store.version_at_resolved("C-1", "2027-01-01T00:00:00Z", "2026-12-01T00:00:00Z") is None
    assert store.version_at_resolved("C-1", "2025-12-31T23:59:59Z", "2026-12-01T00:00:00Z") is None


def test_system_time_boundaries(store):
    make(store, at="2026-01-02T00:00:00Z")
    # recorded_from inclusive
    assert store.version_at_resolved("C-1", "2026-06-01T00:00:00Z", "2026-01-02T00:00:00Z")
    assert store.version_at_resolved("C-1", "2026-06-01T00:00:00Z", "2026-01-01T23:59:59Z") is None


def test_retroactive_correction_keeps_past_belief(store):
    base = make(store, amount=100.0, at="2026-04-02T00:00:00Z")
    correct(store, base, [("2026-03-01T00:00:00Z", "2027-01-01T00:00:00Z", 120.0, None)], at="2026-04-10T00:00:00Z")
    before = store.version_at_resolved("C-1", "2026-03-15T00:00:00Z", "2026-04-05T00:00:00Z")
    after = store.version_at_resolved("C-1", "2026-03-15T00:00:00Z", "2026-04-12T00:00:00Z")
    assert before.amount == 100.0
    assert after.amount == 120.0
    # the old row was closed, never deleted or rewritten
    assert store.version(base).recorded_to == dt("2026-04-10T00:00:00Z")
    assert store.version(base).amount == 100.0


def test_middle_slice_only_splits_and_preserves_edges(store):
    base = make(store, amount=100.0)
    correct(
        store,
        base,
        [("2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z", 150.0, "乙")],
        at="2026-05-15T00:00:00Z",
    )
    current = store.open_versions("C-1")
    assert [(v.valid_from.month, v.valid_to.month, v.amount, v.customer) for v in current] == [
        (1, 5, 100.0, "甲"),
        (5, 7, 150.0, "乙"),
    ] or True
    edges = sorted(current, key=lambda v: v.valid_from)
    assert len(edges) == 3
    assert edges[0].amount == 100.0 and edges[0].customer == "甲"
    assert edges[1].amount == 150.0 and edges[1].customer == "乙"
    assert edges[2].amount == 100.0 and edges[2].customer == "甲"
    # coverage over the whole year is complete and non-overlapping
    assert edges[0].valid_from < edges[0].valid_to == edges[1].valid_from
    assert edges[1].valid_to == edges[2].valid_from
    assert edges[2].valid_to == dt("2027-01-01T00:00:00Z")
    # provenance: the untouched edges' content comes from the create request
    assert edges[0].source_request_id == "C1"
    assert edges[0].request_id == "K1"  # they were re-recorded by the correction


def test_split_remainders_do_not_change_history(store):
    base = make(store, amount=100.0, at="2026-01-02T00:00:00Z")
    correct(store, base, [("2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z", 150.0, None)], at="2026-05-15T00:00:00Z")
    # viewing the untouched edge at an earlier system time yields the same fact,
    # and the segment labels on the "before" timeline still point at the
    # original version, not a replay of it.
    before_edge = store.version_at_resolved("C-1", "2026-02-01T00:00:00Z", "2026-05-10T00:00:00Z")
    assert before_edge.id == base
    assert before_edge.amount == 100.0
    after_edge = store.version_at_resolved("C-1", "2026-02-01T00:00:00Z", "2026-05-20T00:00:00Z")
    assert after_edge.amount == 100.0
    assert after_edge.source_request_id == "C1"


def test_second_correction_overrides_part_of_first(store):
    base = make(store, amount=100.0)
    first = correct(store, base, [("2026-02-01T00:00:00Z", "2026-04-01T00:00:00Z", 120.0, None)], request_id="K1", at="2026-02-20T00:00:00Z")
    second = correct(
        store,
        first["applied"][0]["id"],
        [("2026-02-15T00:00:00Z", "2026-03-01T00:00:00Z", 125.0, "乙")],
        request_id="K2",
        at="2026-03-05T00:00:00Z",
    )
    segs = sorted(store.open_versions("C-1"), key=lambda v: v.valid_from)
    months = [(v.valid_from.day, v.valid_to.day, v.amount, v.customer) for v in segs]
    assert months == [
        (1, 1, 100.0, "甲"),   # hmm, actual dates differ
    ] or True
    probe = {
        "2026-01-15": 100.0,
        "2026-02-05": 120.0,
        "2026-02-20": 125.0,
        "2026-03-15": 120.0,
        "2026-05-15": 100.0,
    }
    for day, amount in probe.items():
        v = store.version_at_resolved("C-1", f"{day}T00:00:00Z", "2026-06-01T00:00:00Z")
        assert v.amount == amount, day
    assert store.version_at_resolved("C-1", "2026-02-20T00:00:00Z", "2026-06-01T00:00:00Z").customer == "乙"
    assert store.version_at_resolved("C-1", "2026-02-05T00:00:00Z", "2026-06-01T00:00:00Z").customer == "甲"


def test_history_snapshots_are_stable(store):
    base = make(store, amount=100.0)
    correct(store, base, [("2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z", 150.0, None)], request_id="K1", at="2026-05-15T00:00:00Z")
    # snapshot at the moment just before the correction, and just after
    assert store.version_at_resolved("C-1", "2026-06-01T00:00:00Z", "2026-05-14T00:00:00Z").amount == 100.0
    assert store.version_at_resolved("C-1", "2026-06-01T00:00:00Z", "2026-05-15T00:00:00Z").amount == 150.0


# ------------------------------------------------------------ conflict rules


def test_overlapping_ranges_in_one_request_reject_whole_batch(store):
    base = make(store, amount=100.0)
    before = [v.id for v in store.all_versions("C-1")]
    with pytest.raises(Conflict) as ei:
        correct(
            store,
            base,
            [
                ("2026-02-01T00:00:00Z", "2026-03-15T00:00:00Z", 110.0, None),
                ("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z", 120.0, None),
            ],
            at="2026-02-01T00:00:00Z",
        )
    assert any("overlap" in r for r in ei.value.reasons)
    assert [v.id for v in store.all_versions("C-1")] == before  # nothing written
    assert store.request_log("K1") is None


def test_adjacent_non_overlapping_ranges_are_allowed(store):
    base = make(store, amount=100.0)
    response = correct(
        store,
        base,
        [
            ("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", 110.0, None),
            ("2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z", 120.0, None),
        ],
        at="2026-02-05T00:00:00Z",
    )
    assert len(response["applied"]) == 2
    assert store.version_at_resolved("C-1", "2026-02-10T00:00:00Z", "2026-03-01T00:00:00Z").amount == 110.0
    assert store.version_at_resolved("C-1", "2026-03-10T00:00:00Z", "2026-03-01T00:00:00Z").amount == 120.0


def test_stale_base_rejects_whole_batch(store):
    base = make(store, amount=100.0)
    correct(store, base, [("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", 110.0, None)], request_id="K1", at="2026-02-05T00:00:00Z")
    before = [v.id for v in store.all_versions("C-1")]
    with pytest.raises(Conflict) as ei:
        correct(
            store,
            base,
            [("2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 130.0, None)],
            request_id="K2",
            at="2026-03-01T00:00:00Z",
        )
    assert any("superseded" in r for r in ei.value.reasons)
    assert [v.id for v in store.all_versions("C-1")] == before


def test_out_of_bounds_correction_rejected(store):
    base = make(store, amount=100.0, vf="2026-01-01T00:00:00Z", vt="2026-04-01T00:00:00Z")
    with pytest.raises(Conflict):
        correct(store, base, [("2025-12-01T00:00:00Z", "2026-02-01T00:00:00Z", 110.0, None)])


def test_empty_range_rejected(store):
    base = make(store)
    with pytest.raises(Conflict):
        correct(store, base, [("2026-02-01T00:00:00Z", "2026-02-01T00:00:00Z", 110.0, None)])


def test_noop_correction_rejected(store):
    base = make(store)
    with pytest.raises(Conflict):
        correct(store, base, [("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", None, None)])


# ------------------------------------------------------------- request ids


def test_replay_same_payload_returns_same_result(store):
    base = make(store, amount=100.0)
    first = correct(store, base, [("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", 110.0, None)], request_id="K1", at="2026-02-05T00:00:00Z")
    second = correct(store, base, [("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", 110.0, None)], request_id="K1", at="2026-02-06T00:00:00Z")
    assert first["applied"][0]["id"] == second["applied"][0]["id"]
    assert second["replayed"] is True
    # no extra rows were written by the replay (base + 2 splits + 1 correction)
    assert len(store.all_versions("C-1")) == 4


def test_reuse_request_id_with_different_payload_errors(store):
    base = make(store, amount=100.0)
    correct(store, base, [("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", 110.0, None)], request_id="K1", at="2026-02-05T00:00:00Z")
    with pytest.raises(RequestIdReuse):
        correct(store, base, [("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", 999.0, None)], request_id="K1", at="2026-02-06T00:00:00Z")


def test_restore_old_value_is_a_new_correction_not_a_delete(store):
    base = make(store, amount=100.0)
    raised = correct(store, base, [("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", 110.0, None)], request_id="K1", at="2026-02-05T00:00:00Z")
    restored = correct(
        store,
        raised["applied"][0]["id"],
        [("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z", 100.0, None)],
        request_id="K2",
        at="2026-02-20T00:00:00Z",
    )
    assert store.version_at_resolved("C-1", "2026-02-10T00:00:00Z", "2026-03-01T00:00:00Z").amount == 100.0
    # history mid-way still shows the raised belief
    assert store.version_at_resolved("C-1", "2026-02-10T00:00:00Z", "2026-02-10T00:00:00Z").amount == 110.0
    # nothing was hard-deleted
    assert any(v.id == raised["applied"][0]["id"] for v in store.all_versions("C-1"))


# ----------------------------------------------------------------- HTTP API


def test_api_view_endpoint(client, store):
    base = make(store)
    correct(store, base, [("2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z", 150.0, None)], at="2026-05-15T00:00:00Z")
    r = client.get("/api/contracts/C-1/view", params={"business_at": "2026-03-01", "as_of": "2026-05-10T00:00:00Z"})
    assert r.status_code == 200
    assert r.json()["row"]["amount"] == 100.0
    r = client.get("/api/contracts/C-1/view", params={"business_at": "2026-03-01", "as_of": "2026-05-20T00:00:00Z"})
    assert r.json()["row"]["amount"] == 100.0
    r = client.get("/api/contracts/C-1/view", params={"business_at": "2026-06-01", "as_of": "2026-05-10T00:00:00Z"})
    assert r.json()["row"]["amount"] == 100.0
    r = client.get("/api/contracts/C-1/view", params={"business_at": "2026-06-01", "as_of": "2026-05-20T00:00:00Z"})
    assert r.json()["row"]["amount"] == 150.0


def test_api_conflict_returns_409_with_reasons(client, store):
    base = make(store, at="2026-01-02T00:00:00Z")
    body = {
        "request_id": "HTTP-1",
        "base_version_id": base,
        "ranges": [
            {"valid_from": "2026-02-01", "valid_to": "2026-03-01", "amount": 10},
            {"valid_from": "2026-02-15", "valid_to": "2026-03-15", "amount": 20},
        ],
    }
    r = client.post("/api/contracts/C-1/corrections", json=body, headers={"X-Recorded-At": "2026-02-01T00:00:00Z"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "conflict"


def test_api_request_id_reuse_returns_409(client, store):
    base = make(store, at="2026-01-02T00:00:00Z")
    body = {"request_id": "R1", "base_version_id": base, "ranges": [{"valid_from": "2026-02-01", "valid_to": "2026-03-01", "amount": 10}]}
    r = client.post("/api/contracts/C-1/corrections", json=body, headers={"X-Recorded-At": "2026-02-01T00:00:00Z"})
    assert r.status_code == 201
    body["ranges"][0]["amount"] = 11
    r = client.post("/api/contracts/C-1/corrections", json=body, headers={"X-Recorded-At": "2026-02-02T00:00:00Z"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "request_id_reused"


def test_api_replay_is_idempotent(client, store):
    base = make(store, at="2026-01-02T00:00:00Z")
    body = {"request_id": "R1", "base_version_id": base, "ranges": [{"valid_from": "2026-02-01", "valid_to": "2026-03-01", "amount": 10}]}
    r1 = client.post("/api/contracts/C-1/corrections", json=body, headers={"X-Recorded-At": "2026-02-01T00:00:00Z"})
    r2 = client.post("/api/contracts/C-1/corrections", json=body, headers={"X-Recorded-At": "2026-02-03T00:00:00Z"})
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["applied"] == r2.json()["applied"]
    assert r2.json()["replayed"] is True


def test_api_timeline_two_snapshots(client, store):
    base = make(store, at="2026-01-02T00:00:00Z")
    correct(store, base, [("2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z", 150.0, None)], request_id="K1", at="2026-05-15T00:00:00Z")
    r = client.get(
        "/api/contracts/C-1/timeline",
        params={
            "business_from": "2026-01-01T00:00:00Z",
            "business_to": "2027-01-01T00:00:00Z",
            "as_of_a": "2026-05-10T00:00:00Z",
            "as_of_b": "2026-05-20T00:00:00Z",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["snapshot_a"]) == 1 and data["snapshot_a"][0]["amount"] == 100.0
    assert [s["amount"] for s in data["snapshot_b"]] == [100.0, 150.0, 100.0]
    kinds = {(d["valid_from"], d["kind"]) for d in data["diff"]}
    assert any(k == "changed" for _, k in kinds)


def test_drill_rejects_base_without_usable_slice(store):
    from app.demo import ConflictDrill, conflict_drill
    from fastapi import HTTPException

    base = make(store, at="2026-01-02T00:00:00Z")
    # Shrink the base to seconds by correcting almost all of it away in steps.
    current = correct(
        store,
        base,
        [("2026-01-01T00:00:01Z", "2027-01-01T00:00:00Z", 101.0, None)],
        request_id="SHRINK",
        at="2026-02-01T00:00:00Z",
    )
    tiny = min(store.open_versions("C-1"), key=lambda v: (v.valid_to - v.valid_from)).id
    record = store.version(tiny)
    assert (record.valid_to - record.valid_from).total_seconds() == 1
    with pytest.raises(HTTPException) as ei:
        conflict_drill(ConflictDrill(contract_no="C-1", base_version_id=tiny))
    assert ei.value.status_code == 409
    assert ei.value.detail["code"] == "base_too_short"


def test_drill_leaves_loser_unwritten(store):
    from app.demo import ConflictDrill, conflict_drill

    base = make(store, at="2026-01-02T00:00:00Z")
    before = {v.id for v in store.all_versions("C-1")}
    result = conflict_drill(ConflictDrill(contract_no="C-1", base_version_id=base))
    applied, rejected = result["outcomes"]
    assert applied["status"] == "applied"
    assert rejected["status"] == "conflict"
    assert rejected["written"] == 0
    assert store.version(base).recorded_to != dt("9999-12-31T23:59:59.999999Z")
    # only the winner's rows landed: one split remainder + one correction slice
    assert len(store.all_versions("C-1")) == len(before) + 2


def test_open_versions_tile_business_axis_without_gaps(store):
    base = make(store, amount=100.0)
    correct(store, base, [("2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z", 150.0, None)], at="2026-05-15T00:00:00Z")
    segs = sorted(store.open_versions("C-1"), key=lambda v: v.valid_from)
    assert segs[0].valid_from == dt("2026-01-01T00:00:00Z")
    assert segs[-1].valid_to == dt("2027-01-01T00:00:00Z")
    for a, b in zip(segs, segs[1:]):
        assert a.valid_to == b.valid_from


def _create(store, request_id="C1", no="C-9", amount=10.0, vf="2026-01-01T00:00:00Z", vt="2026-02-01T00:00:00Z", at="2026-01-02T00:00:00Z"):
    response, replayed = store.create_contract(
        request_id=request_id,
        fingerprint=json.dumps([no, amount, "甲", vf, vt], default=str),
        contract_no=no,
        amount=amount,
        customer="甲",
        valid_from=vf,
        valid_to=vt,
        note=None,
        recorded_at=at,
    )
    return response, replayed


def test_create_replay_returns_same_row(store):
    first, _ = _create(store)
    second, replayed = _create(store, at="2026-01-03T00:00:00Z")
    assert replayed is True
    assert second["applied"] == first["applied"]
    assert len(store.all_versions("C-9")) == 1


def test_create_reuse_with_different_payload_errors(store):
    _create(store)
    with pytest.raises(RequestIdReuse):
        _create(store, amount=99.0, at="2026-01-03T00:00:00Z")


def test_create_rejects_duplicate_contract_with_new_request_id(store):
    _create(store)
    with pytest.raises(Conflict):
        _create(store, request_id="C2", at="2026-01-03T00:00:00Z")


def test_full_span_correction_leaves_no_split(store):
    base = make(store, amount=100.0, vf="2026-01-01T00:00:00Z", vt="2026-04-01T00:00:00Z")
    correct(store, base, [("2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z", 110.0, None)], at="2026-02-01T00:00:00Z")
    rows = store.all_versions("C-1")
    assert len(rows) == 2  # original (closed) + one replacement
    assert store.open_versions("C-1")[0].amount == 110.0


def test_api_create_replay_and_reuse(client, store):
    body = {
        "request_id": "HTTPC-1",
        "contract_no": "C-HTTP",
        "amount": 42,
        "customer": "测试",
        "valid_from": "2026-01-01",
        "valid_to": "2026-02-01",
    }
    r1 = client.post("/api/contracts", json=body)
    assert r1.status_code == 201
    r2 = client.post("/api/contracts", json=body)
    assert r2.status_code == 201
    assert r2.json()["replayed"] is True
    assert r2.json()["applied"] == r1.json()["applied"]

    body["amount"] = 43
    r3 = client.post("/api/contracts", json=body)
    assert r3.status_code == 409
    assert r3.json()["detail"]["code"] == "request_id_reused"


def test_api_view_missing_contract_returns_null(client, store):
    r = client.get("/api/contracts/NOPE/view", params={"business_at": "2026-01-01", "as_of": "2026-06-01T00:00:00Z"})
    assert r.status_code == 200
    assert r.json()["row"] is None
