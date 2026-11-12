"""Seed the demo database with the traced scenarios.

Times are fixed so the two timelines are reproducible:

* business intervals are day-aligned, half-open ``[start, end)``;
* system instants are the moments each request was recorded.

Run ``python -m app.seed``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import CorrectionItem, parse_iso
from .store import Store

DB_PATH = Path(__file__).resolve().parent.parent / "contracts.sqlite3"


def T(text: str) -> datetime:
    return parse_iso(text)


def _create(store: Store, *, request_id, contract_no, amount, customer, vf, vt, at, note):
    response, _ = store.create_contract(
        request_id=request_id,
        fingerprint=json.dumps(
            [contract_no, amount, customer, vf, vt, note], separators=(",", ":")
        ),
        contract_no=contract_no,
        amount=amount,
        customer=customer,
        valid_from=vf,
        valid_to=vt,
        note=note,
        recorded_at=at,
    )
    return response["applied"][0]["id"]


def _correct(store: Store, *, request_id, contract_no, base_id, ranges, at, note):
    response, _ = store.apply_correction(
        request_id=request_id,
        fingerprint=json.dumps(
            [contract_no, base_id, ranges, note], separators=(",", ":"), default=str
        ),
        contract_no=contract_no,
        base_version_id=base_id,
        items=[
            CorrectionItem(
                valid_from=T(vf),
                valid_to=T(vt),
                amount=amount,
                customer=customer,
            )
            for vf, vt, amount, customer in ranges
        ],
        note=note,
        recorded_at=at,
    )
    return response


def seed(store: Store | None = None, *, reset: bool = True) -> list[dict]:
    store = store or Store(DB_PATH)
    if reset:
        store.conn.executescript(
            "DELETE FROM contract_version; DELETE FROM request_result;"
            " DELETE FROM sqlite_sequence;"
        )

    scenarios: list[dict] = []

    # -- 1. Retroactive price increase recorded a month after the term began ---
    no = "C-2026-001"
    v1 = _create(
        store,
        request_id="REQ-001-CREATE",
        contract_no=no,
        amount=100000.0,
        customer="北辰物流",
        vf="2026-03-01T00:00:00Z",
        vt="2026-09-01T00:00:00Z",
        at="2026-04-02T09:15:00Z",
        note="三月生效的年度仓储合同，四月补录",
    )
    _correct(
        store,
        request_id="REQ-001-RETRO-RAISE",
        contract_no=no,
        base_id=v1,
        ranges=[("2026-03-01T00:00:00Z", "2026-09-01T00:00:00Z", 120000.0, None)],
        at="2026-04-10T14:30:00Z",
        note="追溯涨价：三月起年费调整为 12 万",
    )
    scenarios.append(
        {
            "contract_no": no,
            "title": "追溯涨价",
            "story": "合同三月一日生效、四月二日补录为 10 万；四月十日追溯更正为 12 万。"
            "查三月十日：四月十日前看到 10 万，之后看到 12 万。",
            "as_of_early": "2026-04-05T00:00:00Z",
            "as_of_late": "2026-04-12T00:00:00Z",
            "business_date": "2026-03-10",
            "business_from": "2026-02-15T00:00:00Z",
            "business_to": "2026-09-15T00:00:00Z",
        }
    )

    # -- 2. Correction of only the middle slice of a year-long term -----------
    no = "C-2026-002"
    v1 = _create(
        store,
        request_id="REQ-002-CREATE",
        contract_no=no,
        amount=80000.0,
        customer="远望科技",
        vf="2026-01-01T00:00:00Z",
        vt="2027-01-01T00:00:00Z",
        at="2026-01-05T10:00:00Z",
        note="全年服务合同",
    )
    _correct(
        store,
        request_id="REQ-002-MIDDLE",
        contract_no=no,
        base_id=v1,
        ranges=[("2026-05-01T00:00:00Z", "2026-07-01T00:00:00Z", 95000.0, "远望科技（华东）")],
        at="2026-05-15T16:45:00Z",
        note="只改五月至六月这两个月：金额 9.5 万、客户主体变更；两侧保持 8 万",
    )
    scenarios.append(
        {
            "contract_no": no,
            "title": "只改中间一段",
            "story": "全年 8 万；五月十五日只更正五月一日至七月一日的两个月为 9.5 万，"
            "两侧的 8 万继续保留。",
            "as_of_early": "2026-05-10T00:00:00Z",
            "as_of_late": "2026-05-20T00:00:00Z",
            "business_date": "2026-06-01",
            "business_from": "2025-12-15T00:00:00Z",
            "business_to": "2027-01-15T00:00:00Z",
        }
    )

    # -- 3. Two corrections where the second overrides part of the first ------
    no = "C-2026-003"
    v1 = _create(
        store,
        request_id="REQ-003-CREATE",
        contract_no=no,
        amount=60000.0,
        customer="云栖零售",
        vf="2026-01-01T00:00:00Z",
        vt="2026-10-01T00:00:00Z",
        at="2026-01-03T08:20:00Z",
        note="九个月试点合同",
    )
    rails = _correct(
        store,
        request_id="REQ-003-CORR-A",
        contract_no=no,
        base_id=v1,
        ranges=[("2026-02-01T00:00:00Z", "2026-04-01T00:00:00Z", 72000.0, None)],
        at="2026-02-20T11:00:00Z",
        note="第一次更正：二月至三月上调至 7.2 万",
    )
    second_base = rails["applied"][0]["id"]
    rails2 = _correct(
        store,
        request_id="REQ-003-CORR-B",
        contract_no=no,
        base_id=second_base,
        ranges=[("2026-02-15T00:00:00Z", "2026-03-01T00:00:00Z", 75000.0, "云栖零售（直营）")],
        at="2026-03-05T09:30:00Z",
        note="第二次更正覆盖第一次的一半：二月中至三月初改为 7.5 万并变更客户",
    )
    scenarios.append(
        {
            "contract_no": no,
            "title": "先后覆盖的两次更正",
            "story": "第一次把二月整月改成 7.2 万；第二次只覆盖其中二月十五日至三月一日，"
            "改为 7.5 万。第一次未覆盖的部分（二月一日至十四日、三月整月）保持 7.2 万。",
            "as_of_early": "2026-02-25T00:00:00Z",
            "as_of_late": "2026-03-10T00:00:00Z",
            "business_date": "2026-02-20",
            "business_from": "2025-12-15T00:00:00Z",
            "business_to": "2026-10-15T00:00:00Z",
        }
    )

    # -- 4. Concurrent conflict playground: one untouched base -----------------
    no = "C-2026-004"
    _create(
        store,
        request_id="REQ-004-CREATE",
        contract_no=no,
        amount=50000.0,
        customer="青岚教育",
        vf="2026-01-01T00:00:00Z",
        vt="2026-07-01T00:00:00Z",
        at="2026-01-08T12:00:00Z",
        note="冲突演示用的干净基准版本",
    )
    scenarios.append(
        {
            "contract_no": no,
            "title": "同时提交的冲突请求",
            "story": "两条更正都基于同一个基准版本提交。先提交的一条生效并把基准置为过期，"
            "后提交的一条整批返回 409。",
            "as_of_early": "2026-01-10T00:00:00Z",
            "as_of_late": "2026-01-20T00:00:00Z",
            "business_date": "2026-04-01",
            "business_from": "2025-12-15T00:00:00Z",
            "business_to": "2026-07-15T00:00:00Z",
        }
    )

    store.conn.execute(
        "CREATE TABLE IF NOT EXISTS demo_scenario (contract_no TEXT PRIMARY KEY, payload TEXT NOT NULL)"
    )
    store.conn.execute("DELETE FROM demo_scenario")
    for item in scenarios:
        store.conn.execute(
            "INSERT INTO demo_scenario (contract_no, payload) VALUES (?, ?)",
            (item["contract_no"], json.dumps(item, ensure_ascii=False)),
        )
    return scenarios


def load_scenarios(store: Store) -> list[dict]:
    store.conn.execute(
        "CREATE TABLE IF NOT EXISTS demo_scenario (contract_no TEXT PRIMARY KEY, payload TEXT NOT NULL)"
    )
    return [
        json.loads(r["payload"])
        for r in store.conn.execute("SELECT payload FROM demo_scenario ORDER BY contract_no")
    ]


if __name__ == "__main__":
    store = Store(DB_PATH)
    for item in seed(store):
        print(item["contract_no"], item["title"])
    print(f"seeded {DB_PATH}")
