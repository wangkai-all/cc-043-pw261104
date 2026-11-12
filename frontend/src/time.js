/** UTC date helpers for the timelines. All instants are ISO strings in UTC. */

export function parseInstant(iso) {
  return new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
}

export function ms(iso) {
  return parseInstant(iso).getTime();
}

export function isoFromMs(value) {
  return new Date(value).toISOString().replace(".000Z", "Z");
}

export const DAY = 86_400_000;

/** Candidate tick instants (UTC midnight of the first of each month/quarter). */
export function monthTicks(fromMs, toMs) {
  const start = new Date(fromMs);
  const out = [];
  const y0 = start.getUTCFullYear();
  const m0 = start.getUTCMonth();
  for (let i = -1; i <= 60; i += 1) {
    const d = Date.UTC(y0, m0 + i, 1);
    if (d >= fromMs - 0 && d <= toMs) out.push(d);
    if (d > toMs) break;
  }
  return out;
}

export function niceTicks(fromMs, toMs, minGapPx, width) {
  const span = toMs - fromMs || 1;
  const candidates = [1, 2, 3, 6, 12, 24, 36, 60].map((m) => m * 30 * DAY);
  let step = candidates.find((s) => (s / span) * width >= minGapPx) ?? candidates.at(-1);
  if (span < 45 * DAY) step = 0; // short ranges: day ticks handled by caller
  const ticks = [];
  if (step === 0) {
    const d0 = new Date(fromMs);
    const first = Date.UTC(d0.getUTCFullYear(), d0.getUTCMonth(), d0.getUTCDate());
    const dayStep = [7, 14, 30].map((d) => d * DAY).find((s) => (s / span) * width >= minGapPx) ?? 30 * DAY;
    for (let t = first; t <= toMs; t += dayStep) ticks.push(t);
  } else {
    const d0 = new Date(fromMs);
    const months = step / (30 * DAY);
    const anchor = new Date(Date.UTC(d0.getUTCFullYear(), Math.floor(d0.getUTCMonth() / months) * months, 1));
    for (let t = anchor.getTime(); t <= toMs; t = addMonths(t, months)) {
      if (t >= fromMs) ticks.push(t);
    }
  }
  return ticks;
}

function addMonths(msValue, months) {
  const d = new Date(msValue);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + Math.round(months), 1);
}

export function fmtTick(value) {
  const d = new Date(value);
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth() + 1;
  const day = d.getUTCDate();
  return `${y}-${String(m).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export function fmtTickShort(value) {
  const d = new Date(value);
  const y = String(d.getUTCFullYear()).slice(2);
  return `${y}.${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}
