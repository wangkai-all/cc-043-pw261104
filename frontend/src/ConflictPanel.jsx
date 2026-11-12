import { useEffect, useMemo, useState } from "react";

import { api } from "./api";
import { fmtInterval, fmtMoney, fmtStamp } from "./format";

/**
 * Two corrections against the same base version. The first lands and closes
 * the base; the second must be rejected whole. The drill reports both outcomes
 * side by side with the resulting current state.
 */
export default function ConflictPanel({ contractNo, detail, onApplied, onReset }) {
  const open = useMemo(() => (detail?.versions ?? []).filter((v) => v.current), [detail]);
  const [baseId, setBaseId] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open.some((v) => v.id === baseId)) setBaseId(open[0]?.id ?? null);
  }, [open, baseId]);

  const base = open.find((v) => v.id === baseId) ?? null;

  async function run() {
    if (!baseId) return;
    setBusy(true);
    setError(null);
    try {
      const payload = await api.conflictDrill({ contract_no: contractNo, base_version_id: baseId });
      setResult(payload);
      onApplied?.();
    } catch (err) {
      setError(err.payload?.detail?.reasons?.join("；") ?? err.message);
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3>并发冲突演练</h3>
          <p className="card-sub">
            同一基准版本收到两条更正。先落地的一条生效并把基准置为"不再作为当前认知"，后到的一条整批返回
            409，不写入任何一行。
          </p>
        </div>
      </div>

      <div className="drill-controls">
        <label className="field grow">
          <span>共同基准版本</span>
          <select
            value={baseId ?? ""}
            onChange={(event) => setBaseId(Number(event.target.value))}
            disabled={open.length === 0}
          >
            {open.length === 0 && <option value="">没有当前版本</option>}
            {open.map((v) => (
              <option key={v.id} value={v.id}>
                #{v.id} · {fmtInterval(v.valid_from, v.valid_to)} · ¥{v.amount.toLocaleString("zh-CN")}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="primary" onClick={run} disabled={!baseId || busy}>
          {busy ? "提交中…" : "同时提交两条更正"}
        </button>
        <button type="button" className="ghost" onClick={onReset} disabled={busy}>
          重置演示数据
        </button>
      </div>

      {base && (
        <p className="muted small">
          两条请求都会切分 #{base.id} 的业务区间：A 改前三分之一，B 改后三分之一，金额各加 5,000 / 9,000。
        </p>
      )}
      {error && <div className="alert critical">{error}</div>}

      {result && (
        <div className="drill-result">
          <div className="drill-grid">
            {result.outcomes.map((outcome) => (
              <div
                key={outcome.request_id}
                className={`drill-card ${outcome.status === "applied" ? "ok" : "blocked"}`}
              >
                <div className="drill-head">
                  <span className="badge badge-neutral mono">{outcome.request_id}</span>
                  {outcome.status === "applied" ? (
                    <span className="badge badge-good">已落地</span>
                  ) : (
                    <span className="badge badge-critical">整批拒绝 · 写入 0 行</span>
                  )}
                </div>
                {outcome.status === "applied" ? (
                  <ul className="applied-list">
                    {outcome.response.applied.map((v) => (
                      <li key={v.id}>
                        <span className="mono strong">#{v.id}</span>
                        <span className="mono">{fmtInterval(v.valid_from, v.valid_to)}</span>
                        <span>¥{v.amount.toLocaleString("zh-CN")}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <ul className="reasons">
                    {outcome.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
          <div className="drill-foot">
            <span className="muted small">演练时刻 {fmtStamp(result.recorded_at)}</span>
            <span className="muted small">两条请求都基于 #{result.base_version_id}</span>
          </div>
          <div className="current-state">
            <h4>演练后的当前认知</h4>
            <ul className="segments">
              {result.current.map((v) => (
                <li key={v.id}>
                  <span className="mono">{fmtInterval(v.valid_from, v.valid_to)}</span>
                  <span>{fmtMoney(v.amount)}</span>
                  <span className="muted">{v.customer}</span>
                  <span className="version-chip">#{v.id}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}
