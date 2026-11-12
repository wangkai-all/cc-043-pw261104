"""SQLite persistence for the bitemporal contract store.

Every write happens inside a single ``BEGIN IMMEDIATE`` transaction so the
optimistic-concurrency check (is the base version still open?), the idempotent
request-id check, and the inserts that close the base are all atomic. A batch
either lands completely or leaves no trace.

Rows are append-only in content: a correction closes the base row on the system
axis and inserts new rows. The untouched remainders of a base version are
re-inserted as new rows (``recorded_from`` = the correction instant) carrying
the base content unchanged, so the business picture is preserved on both sides
of the corrected slice and history before the correction is untouched.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .models import (
    MAX_TIME,
    ContractView,
    CorrectionItem,
    Version,
    parse_iso,
    to_iso,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS contract_version (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_no       TEXT NOT NULL,
    amount            REAL NOT NULL,
    customer          TEXT NOT NULL,
    valid_from        TEXT NOT NULL,
    valid_to          TEXT NOT NULL,
    recorded_from     TEXT NOT NULL,
    recorded_to       TEXT NOT NULL,
    request_id        TEXT NOT NULL,
    source_request_id TEXT NOT NULL,
    supersedes_id     INTEGER REFERENCES contract_version(id),
    note              TEXT
);
CREATE INDEX IF NOT EXISTS ix_cv_contract ON contract_version(contract_no);
CREATE INDEX IF NOT EXISTS ix_cv_business ON contract_version(valid_from, valid_to);

CREATE TABLE IF NOT EXISTS request_result (
    request_id   TEXT PRIMARY KEY,
    contract_no  TEXT NOT NULL,
    kind         TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,
    recorded_at  TEXT NOT NULL,
    response     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rr_contract ON request_result(contract_no);
"""


class Conflict(Exception):
    """A request cannot be applied against the supplied base / payload."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("; ".join(reasons))


class RequestIdReuse(Exception):
    """Same request id replayed with a different payload."""


def _row_to_version(row: sqlite3.Row) -> Version:
    return Version(
        id=row["id"],
        contract_no=row["contract_no"],
        amount=row["amount"],
        customer=row["customer"],
        valid_from=parse_iso(row["valid_from"]),
        valid_to=parse_iso(row["valid_to"]),
        recorded_from=parse_iso(row["recorded_from"]),
        recorded_to=parse_iso(row["recorded_to"]),
        request_id=row["request_id"],
        source_request_id=row["source_request_id"],
        supersedes_id=row["supersedes_id"],
        note=row["note"],
    )


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    # ---------------------------------------------------------------- reads

    def all_versions(self, contract_no: str | None = None) -> list[Version]:
        sql = "SELECT * FROM contract_version"
        args: tuple = ()
        if contract_no is not None:
            sql += " WHERE contract_no = ?"
            args = (contract_no,)
        sql += " ORDER BY contract_no, valid_from, recorded_from, id"
        return [_row_to_version(r) for r in self.conn.execute(sql, args)]

    def version(self, version_id: int) -> Version | None:
        row = self.conn.execute(
            "SELECT * FROM contract_version WHERE id = ?", (version_id,)
        ).fetchone()
        return _row_to_version(row) if row else None

    def open_versions(self, contract_no: str) -> list[Version]:
        rows = self.conn.execute(
            "SELECT * FROM contract_version WHERE contract_no = ? AND recorded_to = ?"
            " ORDER BY valid_from, id",
            (contract_no, MAX_TIME),
        )
        return [_row_to_version(r) for r in rows]

    def contract_numbers(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT contract_no FROM contract_version ORDER BY contract_no"
        )
        return [r["contract_no"] for r in rows]

    def request_log(self, request_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM request_result WHERE request_id = ?", (request_id,)
        ).fetchone()

    def contract_requests(self, contract_no: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM request_result WHERE contract_no = ? ORDER BY recorded_at",
                (contract_no,),
            )
        )

    # --------------------------------------------------------- pointwise view

    def as_of(self, business_time: str, system_time: str) -> list[Version]:
        """Versions believed at ``system_time`` whose validity covers ``business_time``."""
        rows = self.conn.execute(
            "SELECT * FROM contract_version"
            " WHERE valid_from <= ? AND valid_to > ?"
            "   AND recorded_from <= ? AND recorded_to > ?"
            " ORDER BY contract_no, valid_from, id",
            (business_time, business_time, system_time, system_time),
        )
        return [_row_to_version(r) for r in rows]

    def version_at_resolved(
        self, contract_no: str, business_time: str, system_time: str
    ) -> Version | None:
        hits = [
            v for v in self.as_of(business_time, system_time) if v.contract_no == contract_no
        ]
        if not hits:
            return None
        hits.sort(key=lambda v: (v.recorded_from, v.id))
        return hits[-1]

    def view_at(
        self, contract_no: str, business_time: str, system_time: str
    ) -> ContractView | None:
        v = self.version_at_resolved(contract_no, business_time, system_time)
        if v is None:
            return None
        return ContractView(
            contract_no=v.contract_no,
            amount=v.amount,
            customer=v.customer,
            valid_from=v.valid_from,
            valid_to=v.valid_to,
        )

    def believed_versions(
        self, contract_no: str, system_time: str, business_from: str, business_to: str
    ) -> list[Version]:
        """Segments believed at ``system_time`` clipped to a business window."""
        rows = self.conn.execute(
            "SELECT * FROM contract_version"
            " WHERE contract_no = ?"
            "   AND valid_from < ? AND valid_to > ?"
            "   AND recorded_from <= ? AND recorded_to > ?"
            " ORDER BY valid_from, id",
            (contract_no, business_to, business_from, system_time, system_time),
        )
        return [_row_to_version(r) for r in rows]

    def current_business(self, contract_no: str) -> list[Version]:
        return self.open_versions(contract_no)

    # -------------------------------------------------------------- writes

    def create_contract(
        self,
        *,
        request_id: str,
        fingerprint: str,
        contract_no: str,
        amount: float,
        customer: str,
        valid_from: str,
        valid_to: str,
        note: str | None,
        recorded_at: str,
    ) -> tuple[dict, bool]:
        """Insert the first version of a contract, idempotently by request id."""
        with self.tx() as conn:
            replay = self._saved_response(request_id, fingerprint)
            if replay is not None:
                return replay, True

            if valid_from >= valid_to:
                raise Conflict(["validity must be non-empty (start inclusive, end exclusive)"])
            if self.open_versions(contract_no):
                raise Conflict([f"contract {contract_no} already exists"])

            version_id = self._insert_version(
                conn,
                contract_no=contract_no,
                amount=amount,
                customer=customer,
                valid_from=valid_from,
                valid_to=valid_to,
                recorded_from=recorded_at,
                recorded_to=MAX_TIME,
                request_id=request_id,
                source_request_id=request_id,
                supersedes_id=None,
                note=note,
            )
            version = self.version(version_id)
            assert version is not None
            response = {
                "request_id": request_id,
                "kind": "create",
                "contract_no": contract_no,
                "recorded_at": recorded_at,
                "replayed": False,
                "applied": [version.to_dict()],
                "replaced": [],
            }
            self._save_response(conn, request_id, contract_no, "create", fingerprint, recorded_at, response)
            return response, False

    def apply_correction(
        self,
        *,
        request_id: str,
        fingerprint: str,
        contract_no: str,
        base_version_id: int,
        items: list[CorrectionItem],
        note: str | None,
        recorded_at: str,
    ) -> tuple[dict, bool]:
        """Apply a correction batch atomically against one open base version.

        Raises :class:`Conflict` — and writes nothing — if the base is stale,
        if ranges overlap each other, or if any range is not contained in the
        base's still-current business interval.
        """
        with self.tx() as conn:
            replay = self._saved_response(request_id, fingerprint)
            if replay is not None:
                return replay, True

            problems: list[str] = []
            base = self.version(base_version_id)
            if base is None:
                problems.append(f"base version {base_version_id} does not exist")
            else:
                if base.recorded_to != MAX_TIME:
                    problems.append(
                        f"base version {base_version_id} was already superseded"
                        f" at {to_iso(base.recorded_to)} — reload and rebase"
                    )
                if base.contract_no != contract_no:
                    problems.append(
                        f"base version {base_version_id} belongs to {base.contract_no}"
                    )

            ordered = sorted(items, key=lambda i: (i.valid_from, i.valid_to))
            if any(i.valid_from >= i.valid_to for i in ordered):
                problems.append(
                    "every range must be non-empty (start inclusive, end exclusive)"
                )
            if not ordered:
                problems.append("the request contains no correction ranges")
            if any(
                a.valid_from < b.valid_to and b.valid_from < a.valid_to
                for i, a in enumerate(ordered) for b in ordered[i + 1:]
            ):
                problems.append(
                    "ranges within the request overlap each other;"
                    " submit one range per disputed slice"
                )
            if any(i.amount is None and i.customer is None for i in ordered):
                problems.append("every range must change amount, customer, or both")

            if base is not None and not problems:
                lo, hi = ordered[0].valid_from, ordered[-1].valid_to
                if not (base.valid_from <= lo and hi <= base.valid_to):
                    problems.append(
                        "corrected range lies outside the base version's business interval"
                        f" [{to_iso(base.valid_from)}, {to_iso(base.valid_to)})"
                    )

            if problems or base is None:
                raise Conflict(problems or ["invalid request"])

            # Remainders are re-inserted from the correction instant onward,
            # with the base content untouched. The base row itself is closed,
            # so queries before this instant still see exactly the old belief.
            remainder_lo = base.valid_from
            replaced_splits: list[int] = []
            for item in ordered:
                if remainder_lo < item.valid_from:
                    replaced_splits.append(
                        self._insert_split(conn, base, remainder_lo, item.valid_from, request_id, recorded_at)
                    )
                remainder_lo = item.valid_to
            if remainder_lo < base.valid_to:
                replaced_splits.append(
                    self._insert_split(conn, base, remainder_lo, base.valid_to, request_id, recorded_at)
                )

            applied_ids = [
                self._insert_correction(conn, base, item, request_id, recorded_at, note)
                for item in ordered
            ]

            conn.execute(
                "UPDATE contract_version SET recorded_to = ? WHERE id = ?",
                (recorded_at, base.id),
            )

            applied = [self.version(i).to_dict() for i in applied_ids]
            response = {
                "request_id": request_id,
                "kind": "correction",
                "contract_no": contract_no,
                "recorded_at": recorded_at,
                "base_version_id": base_version_id,
                "replayed": False,
                "applied": applied,
                "replaced": [
                    {
                        "version_id": base.id,
                        "amount": base.amount,
                        "customer": base.customer,
                        "valid_from": to_iso(base.valid_from),
                        "valid_to": to_iso(base.valid_to),
                        "recorded_to": recorded_at,
                    }
                ],
            }
            self._save_response(
                conn, request_id, contract_no, "correction", fingerprint, recorded_at, response
            )
            return response, False

    # ------------------------------------------------------------- internals

    def _saved_response(self, request_id: str, fingerprint: str) -> dict | None:
        row = self.request_log(request_id)
        if row is None:
            return None
        if row["fingerprint"] != fingerprint:
            raise RequestIdReuse(
                f"request id {request_id} was already used with a different payload"
            )
        saved = json.loads(row["response"])
        saved["replayed"] = True
        return saved

    def _save_response(
        self,
        conn: sqlite3.Connection,
        request_id: str,
        contract_no: str,
        kind: str,
        fingerprint: str,
        recorded_at: str,
        response: dict,
    ) -> None:
        conn.execute(
            "INSERT INTO request_result"
            " (request_id, contract_no, kind, fingerprint, recorded_at, response)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (request_id, contract_no, kind, fingerprint, recorded_at, json.dumps(response)),
        )

    def _insert_version(
        self,
        conn: sqlite3.Connection,
        *,
        contract_no: str,
        amount: float,
        customer: str,
        valid_from: str,
        valid_to: str,
        recorded_from: str,
        recorded_to: str,
        request_id: str,
        source_request_id: str,
        supersedes_id: int | None,
        note: str | None,
    ) -> int:
        cur = conn.execute(
            "INSERT INTO contract_version"
            " (contract_no, amount, customer, valid_from, valid_to, recorded_from,"
            "  recorded_to, request_id, source_request_id, supersedes_id, note)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                contract_no, amount, customer, valid_from, valid_to, recorded_from,
                recorded_to, request_id, source_request_id, supersedes_id, note,
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]

    def _insert_split(
        self,
        conn: sqlite3.Connection,
        base: Version,
        valid_from,
        valid_to,
        request_id: str,
        recorded_at: str,
    ) -> int:
        return self._insert_version(
            conn,
            contract_no=base.contract_no,
            amount=base.amount,
            customer=base.customer,
            valid_from=to_iso(valid_from),
            valid_to=to_iso(valid_to),
            recorded_from=recorded_at,
            recorded_to=MAX_TIME,
            request_id=request_id,
            source_request_id=base.source_request_id,
            supersedes_id=base.id,
            note="split",
        )

    def _insert_correction(
        self,
        conn: sqlite3.Connection,
        base: Version,
        item: CorrectionItem,
        request_id: str,
        recorded_at: str,
        note: str | None,
    ) -> int:
        amount = item.amount if item.amount is not None else base.amount
        customer = item.customer if item.customer is not None else base.customer
        return self._insert_version(
            conn,
            contract_no=base.contract_no,
            amount=amount,
            customer=customer,
            valid_from=to_iso(item.valid_from),
            valid_to=to_iso(item.valid_to),
            recorded_from=recorded_at,
            recorded_to=MAX_TIME,
            request_id=request_id,
            source_request_id=request_id,
            supersedes_id=base.id,
            note=note,
        )
