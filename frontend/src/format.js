export function fmtAmount(value) {
  if (value == null) return "—";
  if (Math.abs(value) >= 10000) {
    const wan = value / 10000;
    return `${Number.isInteger(wan) ? wan : wan.toFixed(1)}万`;
  }
  return Number(value).toLocaleString("zh-CN");
}

export function fmtMoney(value) {
  if (value == null) return "—";
  return `¥${Number(value).toLocaleString("zh-CN")}`;
}

/** Render an ISO instant in UTC, no local-time guessing. */
export function fmtInstant(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
  );
}

export function fmtDay(iso) {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

export function fmtInterval(fromIso, toIso) {
  if (!fromIso || !toIso) return "—";
  const open = toIso.startsWith("9999");
  return `[${fmtDay(fromIso)}, ${open ? "至今" : fmtDay(toIso)})`;
}

export function fmtStamp(iso) {
  if (!iso) return "—";
  const day = fmtDay(iso);
  const time = fmtInstant(iso).slice(11);
  return `${day} ${time}Z`;
}

export function toInputValue(iso) {
  return iso ? iso.slice(0, 16) : "";
}

export function fromInputValue(value) {
  if (!value) return null;
  return value.length === 16 ? `${value}:00` : value;
}

export function makeRequestId(prefix = "UI") {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${prefix}-${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}` +
    `-${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}`
  );
}
