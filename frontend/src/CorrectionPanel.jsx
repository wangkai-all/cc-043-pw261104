import { useEffect, useMemo, useState } from "react";

import { api } from "./api";
import { fmtInterval, fmtStamp, makeRequestId } from "./format";

const defaultRange = () => ({ valid_from: "2026-03-01T00:00", valid_to: "2026-04-01T00:00", amount: "", customer: "" });

function toIso(value) {
  if (!value) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${value}T00:00:00Z`;
  const seconds = value.length === 16 ? `${value}:00` : value;
  return `${seconds}Z`;
}

/**
 * Correction form pinned to one open base version. The user picks the base
 * from the current open versions (that is "the version they opened"); the
 * request carries its id, so a concurrent correction closes it and the whole
 * batch is rejected as stale instead of silently stacking.
 */
export default function CorrectionPanel({ contractNo, detail, onApplied }) {
  const open = useMemo(
    () => (detail?.versions ?? []).filter((v) => v.current),
    [detail],
  );
  const [baseId, setBaseId] = useState(null);
  const [ranges, setRanges] = useState([defaultRange()]);
  const [note, setNote] = useState("");
  const [requestId, setRequestId] = useState(() => makeRequestId("CORR"));
  const [outcome, setOutcome] = useState(null);
  const [busy, setBusy] = useState(false);
  const [replayBody, setReplayBody] = useState(null);

  useEffect(() => {
    if (open.length === 0) {
      setBaseId(null);
      return;
    }
    if (!open.some((v) => v.id === baseId)) setBaseId(open[0].id);
  }, [open, baseId]);

  const base = open.find((v) => v.id === baseId) ?? null;

  const updateRange = (index, key, value) =>
    setRanges((current) => current.map((r, i) => (i === index ? { ...r, [key]: value } : r)));
  const removeRange = (index) =>
    setRanges((current) => (current.length === 1 ? current : current.filter((_, i) => i !== index)));

  const buildBody = (id = requestId) => ({
    request_id: id,
    base_version_id: baseId,
    ranges: sortedRanges().map((r) => ({
      valid_from: toIso(r.valid_from),
      valid_to: toIso(r.valid_to),
      amount: r.amount === "" ? null : Number(r.amount),
      customer: r.customer === "" ? null : r.customer,
    })),
    note: note || null,
  });

  /** The base's notional business interval, used to seed a new row. */
  function baseSpan() {
    if (!base) return ["2026-03-01T00:00", "2026-04-01T00:00"];
    return [base.valid_from.slice(0, 16), base.valid_to.slice(0, 16)];
  }

  function addRange() {
    const [start, end] = baseSpan();
    setRanges((current) => [
      ...current,
      { valid_from: start, valid_to: end, amount: "", customer: "" },
    ]);
  }

  /** Order by start so the API's overlap check sees a stably-sorted batch. */
  function sortedRanges() {
    return [...ranges].sort((a, b) =>
      a.valid_from === b.valid_from
        ? a.valid_to.localeCompare(b.valid_to)
        : a.valid_from.localeCompare(b.valid_from),
    );
  }

  async function submit(event) {
    event?.preventDefault();
    if (!baseId) return;
    const body = buildBody();
    setBusy(true);
    setOutcome(null);
    try {
      const response = await api.correct(contractNo, body);
      setOutcome({ ok: true, response, body });
      setReplayBody(body);
      setRequestId(makeRequestId("CORR"));
      onApplied?.();
    } catch (error) {
      setOutcome({ ok: false, error, body });
    } finally {
      setBusy(false);
    }
  }

  async function replaySame() {
    if (!replayBody) return;
    setBusy(true);
    try {
      const response = await api.correct(contractNo, replayBody);
      setOutcome({ ok: true, response, body: replayBody, replay: true });
    } catch (error) {
      setOutcome({ ok: false, error, body: replayBody });
    } finally {
      setBusy(false);
    }
  }

  async function replayChanged() {
    if (!replayBody) return;
    const body = {
      ...replayBody,
      ranges: replayBody.ranges.map((r, i) =>
        i === 0 ? { ...r, amount: (r.amount ?? 0) + 1000 } : r,
      ),
    };
    setBusy(true);
    try {
      const response = await api.correct(contractNo, body);
      setOutcome({ ok: false, error: { status: "unexpected", message: "意外成功", payload: response }, body });
    } catch (error) {
      setOutcome({ ok: false, error, body });
    } finally {
      setBusy(false);
    }
  }

  function restorePrevious() {
    if (!base) return;
    const previous = (detail?.versions ?? [])
      .filter((v) => !v.current)
      .sort((a, b) => b.id - a.id)
      .find((v) => v.valid_from <= base.valid_from && base.valid_from < v.valid_to);
    if (!previous) return;
    setRanges([
      {
        valid_from: base.valid_from.slice(0, 16),
        valid_to: base.valid_to.slice(0, 16),
        amount: String(previous.amount),
        customer: previous.customer,
      },
    ]);
    setNote(`恢复 #${previous.id} 的旧值（恢复本身是一条新更正，不删除历史）`);
  }

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3>提交更正</h3>
          <p className="card-sub">
            更正基于"打开时看到的当前版本"。提交时会检查该版本是否已被其他操作改过；已过期就整批拒绝，不会半途写入。
          </p>
        </div>
        <button type="button" className="ghost" onClick={() => setRequestId(makeRequestId("CORR"))}>
          换一个请求编号
        </button>
      </div>

      <form onSubmit={submit} className="correction-form">
        <div className="base-picker">
          <label className="field grow">
            <span>基准版本（打开时的当前版本）</span>
            <select
              value={baseId ?? ""}
              onChange={(event) => setBaseId(Number(event.target.value))}
              disabled={open.length === 0}
            >
              {open.length === 0 && <option value="">没有可更正的当前版本</option>}
              {open.map((v) => (
                <option key={v.id} value={v.id}>
                  #{v.id} · {fmtInterval(v.valid_from, v.valid_to)} · ¥{v.amount.toLocaleString("zh-CN")} · {v.customer}
                </option>
              ))}
            </select>
          </label>
          <label className="field grow">
            <span>请求编号（手动填写可演练重交）</span>
            <input className="mono" value={requestId} onChange={(e) => setRequestId(e.target.value)} />
          </label>
        </div>

        {base && (
          <div className="base-badge">
            <span className="badge badge-neutral">基准 #{base.id}</span>
            <span className="mono small">
              业务 {fmtInterval(base.valid_from, base.valid_to)} · 系统 {fmtInterval(base.recorded_from, base.recorded_to)}
            </span>
            <span className="muted small">来源 {base.source_request_id}</span>
          </div>
        )}

        <div className="ranges">
          <div className="ranges-head">
            <span>更正区间（同一请求内的区间不能重叠）</span>
            <button type="button" className="ghost" onClick={addRange}>
              + 再加一段
            </button>
          </div>
          {ranges.map((range, index) => (
            <div className="range-row" key={index}>
              <label className="field">
                <span>开始（含）</span>
                <input
                  type="datetime-local"
                  value={range.valid_from}
                  onChange={(e) => updateRange(index, "valid_from", e.target.value)}
                />
              </label>
              <label className="field">
                <span>结束（不含）</span>
                <input
                  type="datetime-local"
                  value={range.valid_to}
                  onChange={(e) => updateRange(index, "valid_to", e.target.value)}
                />
              </label>
              <label className="field">
                <span>新金额</span>
                <input
                  inputMode="decimal"
                  placeholder="留空=不变"
                  value={range.amount}
                  onChange={(e) => updateRange(index, "amount", e.target.value)}
                />
              </label>
              <label className="field">
                <span>新客户</span>
                <input
                  placeholder="留空=不变"
                  value={range.customer}
                  onChange={(e) => updateRange(index, "customer", e.target.value)}
                />
              </label>
              <button
                type="button"
                className="icon-button"
                aria-label="删除这一段"
                onClick={() => removeRange(index)}
                disabled={ranges.length === 1}
              >
                ×
              </button>
            </div>
          ))}
        </div>

        <label className="field">
          <span>说明</span>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="例如：追溯涨价、只改中间一段" />
        </label>

        <div className="form-actions">
          <button type="submit" className="primary" disabled={!baseId || busy}>
            {busy ? "提交中…" : "提交更正"}
          </button>
          <button type="button" className="ghost" onClick={restorePrevious} disabled={!base}>
            用上一版的值填充（恢复走新更正）
          </button>
          <button type="button" className="ghost" onClick={replaySame} disabled={!replayBody || busy}>
            重交上一次（同内容）
          </button>
          <button type="button" className="ghost" onClick={replayChanged} disabled={!replayBody || busy}>
            同编号 · 改内容重交
          </button>
        </div>
      </form>

      {outcome && <Outcome outcome={outcome} stamp={fmtStamp(new Date().toISOString())} />}
    </section>
  );
}

function Outcome({ outcome, stamp }) {
  if (outcome.error) {
    const reasons = outcome.error.payload?.detail?.reasons ?? [outcome.error.message];
    const code = outcome.error.payload?.detail?.code;
    return (
      <div className="outcome conflict" role="status">
        <div className="outcome-head">
          <span className="badge badge-critical">整批未写入</span>
          <span className="mono small">{code ?? outcome.error.status}</span>
          <span className="muted small">请求 {outcome.body?.request_id}</span>
        </div>
        <ul className="reasons">
          {reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
        <p className="muted small">
          同一请求内的任何一段不合法（区间重叠、越界、基准过期）都会让整批失败；已写入的行数为 0。
        </p>
      </div>
    );
  }

  const response = outcome.response;
  return (
    <div className="outcome success" role="status">
      <div className="outcome-head">
        <span className="badge badge-good">{response.replayed ? "重交命中已有结果" : "已写入"}</span>
        <span className="mono small">请求 {response.request_id}</span>
        <span className="muted small">{response.replayed ? "未新增任何行" : stamp}</span>
      </div>
      <ul className="applied-list">
        {response.applied.map((v) => (
          <li key={v.id}>
            <span className="mono strong">#{v.id}</span>
            <span className="mono">{fmtInterval(v.valid_from, v.valid_to)}</span>
            <span>→ ¥{v.amount.toLocaleString("zh-CN")} · {v.customer}</span>
            <span className="muted small">来源 {v.source_request_id}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
