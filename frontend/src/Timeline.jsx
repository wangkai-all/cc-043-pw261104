import { useMemo, useState } from "react";

import { useElementWidth } from "./useElementWidth";
import { fmtDay, fmtMoney, fmtStamp } from "./format";
import { ms, fmtTick } from "./time";

const ROW_H = 56;
const BAR_H = 22;
const LABEL_W = 168;
const PAD_R = 20;
const AXIS_H = 26;
const TOP = 10;
const LANE_GAP = 20;

/**
 * Two stacked lanes over one shared business-time axis:
 *   A = what the system believed at `as_of_a`
 *   B = what it believes at `as_of_b`
 * Each lane draws its version segments as thin bars (22px, 4px rounded ends),
 * split by a 2px surface gap. Hover/focus reads out the segment; the table
 * below is the non-hover path to every value.
 */
export default function Timeline({ timeline, onProbe }) {
  const [nodeRef, width] = useElementWidth();
  const [hover, setHover] = useState(null);
  const innerW = Math.max(width - LABEL_W - PAD_R, 240);

  const domain = useMemo(() => {
    if (!timeline) return null;
    const from = ms(timeline.business_from);
    const to = ms(timeline.business_to);
    return { from, to };
  }, [timeline]);

  const xOf = (iso) => {
    if (!domain) return 0;
    const t = ms(iso);
    return LABEL_W + ((t - domain.from) / (domain.to - domain.from)) * innerW;
  };

  const ticks = useMemo(() => {
    if (!domain) return [];
    const gap = 92;
    const span = domain.to - domain.from;
    const start = new Date(domain.from);
    const monthStep = [1, 2, 3, 6, 12, 24, 36, 60].find(
      (m) => ((m * 30.4 * 86400000) / span) * innerW >= gap,
    );
    const out = [];
    if (monthStep) {
      for (let i = 0; i < 200; i += 1) {
        const t = Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + i * monthStep, 1);
        if (t > domain.to) break;
        if (t >= domain.from) out.push(t);
      }
    } else {
      const dayStep =
        [7, 14, 30].find((d) => ((d * 86400000) / span) * innerW >= gap) ?? 30;
      for (
        let t = Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), start.getUTCDate());
        t <= domain.to;
        t += dayStep * 86400000
      ) {
        if (t >= domain.from) out.push(t);
      }
    }
    return out;
  }, [domain, innerW]);

  if (!timeline) {
    return (
      <div className="timeline-empty">
        <p>选择一个场景后，这里显示两条时间线。</p>
      </div>
    );
  }

  const lanes = [
    {
      key: "A",
      title: "查询时点 A · 当时所知",
      subtitle: fmtStamp(timeline.as_of_a),
      color: "var(--series-1)",
      rows: timeline.snapshot_a,
    },
    {
      key: "B",
      title: "查询时点 B · 更正后所知",
      subtitle: fmtStamp(timeline.as_of_b),
      color: "var(--series-2)",
      rows: timeline.snapshot_b,
    },
  ];

  const laneTop = (i) => TOP + i * (ROW_H + LANE_GAP);
  const height = laneTop(1) + ROW_H + AXIS_H + 6;

  const active = hover
    ? lanes
        .find((l) => l.key === hover.lane)
        ?.rows.find((r) => r.id === hover.id && r.recorded_from === hover.rf)
    : null;

  const tipX = hover ? xOf(hover.iso) : 0;

  return (
    <div className="timeline-block">
      <div className="chart-head">
        <div>
          <h3>业务时间 × 系统时间</h3>
          <p className="chart-sub">
            横轴是业务日期；上下两条泳道是同一合同在两个查询时点的认知。区间按
            <span className="mono"> [开始, 结束) </span>处理，相邻段之间留 2px 空隙。
          </p>
        </div>
        <div className="legend" aria-label="图例">
          {lanes.map((lane) => (
            <span className="legend-item" key={lane.key}>
              <span className="legend-swatch" style={{ background: lane.color }} />
              {lane.title}
            </span>
          ))}
        </div>
      </div>

      <div className="chart-wrap" ref={nodeRef}>
        {width > 0 && (
          <svg
            width={width}
            height={height}
            role="img"
            aria-label="两个查询时点的合同区间对照"
          >
            {ticks.map((t) => {
              const x = xOf(new Date(t).toISOString());
              return (
                <g key={t}>
                  <line
                    x1={x}
                    x2={x}
                    y1={TOP}
                    y2={height - AXIS_H}
                    stroke="var(--grid)"
                    strokeWidth={1}
                  />
                  <text x={x} y={height - AXIS_H + 15} className="tick" textAnchor="middle">
                    {fmtTick(t)}
                  </text>
                </g>
              );
            })}

            {timeline.diff
              ?.filter((d) => d.kind === "changed" || d.kind === "added" || d.kind === "removed")
              .map((d) => {
                const x1 = xOf(d.valid_from);
                const x2 = xOf(d.valid_to);
                return (
                  <rect
                    key={`diff-${d.valid_from}`}
                    x={x1}
                    y={TOP}
                    width={Math.max(x2 - x1, 1)}
                    height={height - AXIS_H - TOP}
                    fill={
                      d.kind === "changed"
                        ? "rgba(208,59,59,0.055)"
                        : "rgba(12,163,12,0.065)"
                    }
                  />
                );
              })}

            {lanes.map((lane, i) => {
              const barY = laneTop(i) + 30;
              return (
                <g key={lane.key}>
                  <text x={0} y={laneTop(i) + 12} className="lane-title">
                    {lane.title}
                  </text>
                  <text x={0} y={laneTop(i) + 26} className="lane-sub">
                    {lane.subtitle}
                  </text>
                  {lane.rows.map((row) => {
                    const x1 = xOf(row.clip_valid_from);
                    const x2 = xOf(row.clip_valid_to);
                    const w = Math.max(x2 - x1 - 2, 3);
                    const isHovered =
                      hover?.lane === lane.key &&
                      hover?.id === row.id &&
                      hover?.rf === row.recorded_from;
                    const labelFits = w > 92;
                    return (
                      <g
                        key={`${row.id}-${row.recorded_from}`}
                        tabIndex={0}
                        role="listitem"
                        aria-label={`${fmtDay(row.clip_valid_from)} 至 ${fmtDay(row.clip_valid_to)}，${row.customer}，${fmtMoney(row.amount)}`}
                        onMouseEnter={() =>
                          setHover({
                            lane: lane.key,
                            id: row.id,
                            rf: row.recorded_from,
                            iso: row.clip_valid_from,
                          })
                        }
                        onMouseLeave={() => setHover(null)}
                        onFocus={() =>
                          setHover({
                            lane: lane.key,
                            id: row.id,
                            rf: row.recorded_from,
                            iso: row.clip_valid_from,
                          })
                        }
                        onBlur={() => setHover(null)}
                        className="segment"
                      >
                        <rect
                          x={x1}
                          y={barY - 18}
                          width={Math.max(x2 - x1, 1)}
                          height={BAR_H + 24}
                          fill="transparent"
                        />
                        <rect
                          x={x1 + 1}
                          y={barY}
                          width={w}
                          height={BAR_H}
                          rx={4}
                          fill={lane.color}
                          opacity={isHovered ? 0.98 : 0.88}
                        />
                        {labelFits && (
                          <text
                            x={x1 + 9}
                            y={barY + BAR_H / 2 + 4}
                            className="bar-label"
                          >
                            ¥{row.amount.toLocaleString("zh-CN")}
                          </text>
                        )}
                      </g>
                    );
                  })}
                </g>
              );
            })}
          </svg>
        )}

        {hover && active && (
          <div
            className="chart-tip"
            style={{
              left: Math.min(Math.max(tipX, LABEL_W + 70), width - 160),
              top: laneTop(hover.lane === "A" ? 0 : 1) + 44,
            }}
          >
            <div className="tip-value">{fmtMoney(active.amount)}</div>
            <div className="tip-label">{active.customer}</div>
            <div className="tip-range">
              [{fmtDay(active.clip_valid_from)}, {fmtDay(active.clip_valid_to)})
            </div>
            <div className="tip-meta">
              来源 {active.source_request_id} · 版本 #{active.id}
            </div>
          </div>
        )}
      </div>

      <p className="chart-note">
        浅色底纹标出两个查询时点之间的差异段：红色表示同一业务段上内容不同，绿色表示新增或还原。段内标注金额；完整客户与来源见下方逐段核对表。
      </p>
    </div>
  );
}
