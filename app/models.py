"""Domain model for pointwise (bitemporal) contract records.

Two independent time axes are stored for every fact:

* **Business validity** (``valid_from`` / ``valid_to``) — when the fact is
  true in the real world, half-open ``[valid_from, valid_to)``.
* **System time** (``recorded_from`` / ``recorded_to``) — when the system
  started / stopped believing that fact, half-open ``[recorded_from, recorded_to)``.

Corrections never mutate or delete a version's content; a corrected row is
closed on the system axis (``recorded_to`` set) and new version rows are
inserted. ``request_id`` is the request that wrote the row into the system;
``source_request_id`` is the request the row's *content* originates from.
For an untouched remainder produced by a split they differ, so provenance can
be shown honestly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
MAX_TIME = datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_iso(raw: str) -> datetime:
    """Parse an ISO-8601 instant; a bare date means midnight UTC."""
    value = raw.strip()
    if not value:
        raise ValueError("empty timestamp")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass(frozen=True)
class Version:
    """One row of the bitemporal store: a fact plus its two time ranges."""

    id: int
    contract_no: str
    amount: float
    customer: str
    valid_from: datetime
    valid_to: datetime
    recorded_from: datetime
    recorded_to: datetime
    request_id: str
    source_request_id: str
    supersedes_id: int | None
    note: str | None

    def business_overlap(self, lo: datetime, hi: datetime) -> bool:
        return self.valid_from < hi and lo < self.valid_to

    def is_current(self) -> bool:
        return self.recorded_to == MAX_TIME

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "contract_no": self.contract_no,
            "amount": self.amount,
            "customer": self.customer,
            "valid_from": to_iso(self.valid_from),
            "valid_to": to_iso(self.valid_to),
            "recorded_from": to_iso(self.recorded_from),
            "recorded_to": to_iso(self.recorded_to),
            "current": self.is_current(),
            "request_id": self.request_id,
            "source_request_id": self.source_request_id,
            "supersedes_id": self.supersedes_id,
            "note": self.note,
        }


@dataclass(frozen=True)
class CorrectionItem:
    valid_from: datetime
    valid_to: datetime
    amount: float | None
    customer: str | None


@dataclass
class ContractView:
    contract_no: str
    amount: float | None
    customer: str | None
    valid_from: datetime | None
    valid_to: datetime | None


def now_utc() -> datetime:
    return datetime.now(UTC)
