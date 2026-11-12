import { fmtDay, fmtInterval, fmtStamp } from "./format";

const KIND_LABEL = {
  same: "未变",
  changed: "内容不同",
  added: "新增",
  removed: "移除",
};

export default function DiffTable({ timeline }) {
  if (!timeline) return null;
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3>版本差异 · 逐段核对</h3>
          <p className="card-sub">
            按两个时点的共同切分逐段对照。每一段都带上来源请求与两组区间，可拿任意两个查询时点复核。
          </p>
        </div>
        <span className="tag">
          {timeline.diff?.filter((d) => d.kind !== "same").length ?? 0} 段不一致
        </span>
      </div>

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">业务区间</th>
              <th scope="col">状态</th>
              <th scope="col">时点 A · 金额 / 客户</th>
              <th scope="col">A 系统区间</th>
              <th scope="col">A 来源请求</th>
              <th scope="col">时点 B · 金额 / 客户</th>
              <th scope="col">B 系统区间</th>
              <th scope="col">B 来源请求</th>
            </tr>
          </thead>
          <tbody>
            {timeline.diff?.map((row) => {
              const badgeClass =
                row.kind === "same"
                  ? "badge badge-neutral"
                  : row.kind === "changed"
                    ? "badge badge-critical"
                    : row.kind === "removed"
                      ? "badge badge-serious"
                      : "badge badge-good";
              return (
                <tr key={`${row.valid_from}-${row.valid_to}`}>
                  <td className="mono nowrap">
                    [{fmtDay(row.valid_from)}, {fmtDay(row.valid_to)})
                  </td>
                  <td>
                    <span className={badgeClass}>
                      <span aria-hidden="true">{row.kind === "same" ? "=" : row.kind === "changed" ? "≠" : row.kind === "added" ? "+" : "−"}</span>
                      {KIND_LABEL[row.kind]}
                    </span>
                  </td>
                  <td>{renderSide(row.a)}</td>
                  <td className="mono small">{row.a ? fmtInterval(row.a.recorded_from, row.a.recorded_to) : "—"}</td>
                  <td className="mono small">{row.a?.source_request_id ?? "—"}</td>
                  <td>{renderSide(row.b)}</td>
                  <td className="mono small">{row.b ? fmtInterval(row.b.recorded_from, row.b.recorded_to) : "—"}</td>
                  <td className="mono small">{row.b?.source_request_id ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function renderSide(side) {
  if (!side) return <span className="muted">无</span>;
  return (
    <span>
      <span className="strong">{side.amount == null ? "—" : `¥${side.amount.toLocaleString("zh-CN")}`}</span>
      <span className="sep">·</span>
      <span>{side.customer}</span>
      <span className="version-chip">#{side.id}</span>
    </span>
  );
}
