import { fmtDay, fmtInterval, fmtStamp } from "./format";

/** The full append-only version ledger, grouped by business interval. */
export default function VersionLedger({ detail }) {
  if (!detail) return null;
  const versions = detail.versions ?? [];
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3>版本账本</h3>
          <p className="card-sub">
            只追加、不删除。每条记录都带业务有效期与系统有效期两组区间；被更正的行只是被置为"不再作为当前认知"。
          </p>
        </div>
        <span className="tag">{versions.length} 行</span>
      </div>
      <div className="table-scroll">
        <table className="data-table ledger">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">业务区间</th>
              <th scope="col">金额 / 客户</th>
              <th scope="col">系统区间</th>
              <th scope="col">来源请求</th>
              <th scope="col">取代</th>
              <th scope="col">说明</th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.id} className={v.current ? "" : "row-closed"}>
                <td className="mono">{v.id}</td>
                <td className="mono nowrap">{fmtInterval(v.valid_from, v.valid_to)}</td>
                <td>
                  <span className="strong">¥{v.amount.toLocaleString("zh-CN")}</span>
                  <span className="sep">·</span>
                  {v.customer}
                </td>
                <td className="mono small nowrap">{fmtInterval(v.recorded_from, v.recorded_to)}</td>
                <td className="mono small">{v.source_request_id}</td>
                <td className="mono small">{v.supersedes_id == null ? "—" : `#${v.supersedes_id}`}</td>
                <td className="small">
                  {v.current ? (
                    <span className="badge badge-good">当前</span>
                  ) : (
                    <span className="badge badge-neutral">已被更正</span>
                  )}
                  <span className="ledger-note">{v.note ?? ""}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="card-foot">
        系统区间为 <span className="mono">[recorded_from, recorded_to)</span>；展示时保留原始
        UTC 时刻，避免本地时区把边界挪到相邻的日期。
      </p>
    </section>
  );
}

export function RequestList({ detail }) {
  if (!detail) return null;
  const requests = detail.requests ?? [];
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3>请求记录</h3>
          <p className="card-sub">同编号、同内容的重交返回已有结果；编号相同但内容不同会被拒绝。</p>
        </div>
      </div>
      <ol className="request-list">
        {requests.map((r) => (
          <li key={r.request_id}>
            <div className="request-line">
              <span className="mono strong">{r.request_id}</span>
              <span className="badge badge-neutral">{r.kind === "create" ? "补录" : "更正"}</span>
              {r.response.replayed && <span className="badge badge-good">重交命中</span>}
              <span className="muted small">{fmtStamp(r.recorded_at)}</span>
            </div>
            <div className="request-ranges">
              {(r.response.applied ?? []).map((v) => (
                <span className="range-chip mono" key={v.id}>
                  {fmtInterval(v.valid_from, v.valid_to)} → ¥{v.amount.toLocaleString("zh-CN")} · {v.customer}
                </span>
              ))}
            </div>
          </li>
        ))}
        {requests.length === 0 && <li className="muted">暂无请求</li>}
      </ol>
    </section>
  );
}
