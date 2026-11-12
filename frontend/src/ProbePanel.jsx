import { useEffect, useState } from "react";

import { api } from "./api";
import { fmtDay, fmtInterval, fmtMoney, fmtStamp } from "./format";

/**
 * Pointwise lookup: pick a *business date* and a *query instant* independently.
 * The pair answers "what did we believe at instant T was true on date D".
 */
export default function ProbePanel({ contractNo, asOfA, asOfB }) {
  const [businessDate, setBusinessDate] = useState("2026-03-10");
  const [asOf, setAsOf] = useState(asOfA);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => setAsOf(asOfA), [asOfA]);

  useEffect(() => {
    if (!contractNo || !businessDate || !asOf) {
      setResult(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .view(contractNo, businessDate, asOf)
      .then((payload) => {
        if (!cancelled) {
          setResult(payload);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message);
          setResult(null);
        }
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [contractNo, businessDate, asOf]);

  return (
    <section className="card probe">
      <div className="card-head">
        <div>
          <h3>点查 · 业务日期 × 查询时点</h3>
          <p className="card-sub">
            业务日期决定"看哪一天的事实"，查询时点决定"用哪一版认知回答"。两个时间轴独立选择。
          </p>
        </div>
        <div className="probe-actions">
          <button type="button" className="ghost" onClick={() => setAsOf(asOfA)}>
            用 A 时点
          </button>
          <button type="button" className="ghost" onClick={() => setAsOf(asOfB)}>
            用 B 时点
          </button>
        </div>
      </div>

      <div className="probe-controls">
        <label className="field">
          <span>业务日期</span>
          <input
            type="date"
            value={businessDate}
            onChange={(event) => setBusinessDate(event.target.value)}
          />
        </label>
        <label className="field grow">
          <span>查询时点（UTC）</span>
          <input
            type="text"
            className="mono"
            placeholder="2026-05-15T00:00:00Z"
            value={asOf}
            onChange={(event) => setAsOf(event.target.value)}
          />
        </label>
      </div>

      {error && <div className="alert critical">{error}</div>}

      {!error && (
        <div className={`probe-result ${loading ? "is-loading" : ""}`}>
          {result?.row ? (
            <>
              <div className="probe-hero">
                <div className="hero-label">当时的合同金额</div>
                <div className="hero-value">{fmtMoney(result.row.amount)}</div>
              </div>
              <dl className="probe-facts">
                <div>
                  <dt>客户</dt>
                  <dd>{result.row.customer}</dd>
                </div>
                <div>
                  <dt>生效区间</dt>
                  <dd className="mono">{fmtInterval(result.row.valid_from, result.row.valid_to)}</dd>
                </div>
                <div>
                  <dt>命中的版本</dt>
                  <dd className="mono">#{result.row.id}</dd>
                </div>
                <div>
                  <dt>来源请求</dt>
                  <dd className="mono">{result.row.source_request_id}</dd>
                </div>
                <div>
                  <dt>该版本的系统区间</dt>
                  <dd className="mono">
                    {fmtInterval(result.row.recorded_from, result.row.recorded_to)}
                  </dd>
                </div>
              </dl>
            </>
          ) : (
            <div className="probe-empty">
              {loading ? "查询中…" : `在 ${fmtDay(businessDate)} 这一天、按 ${fmtStamp(asOf)} 的认知，没有生效中的合同。`}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
