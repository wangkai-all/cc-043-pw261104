import { useEffect, useMemo, useState } from "react";

import { api } from "./api";
import ConflictPanel from "./ConflictPanel";
import CorrectionPanel from "./CorrectionPanel";
import DiffTable from "./DiffTable";
import Ledger, { RequestList } from "./Ledger";
import ProbePanel from "./ProbePanel";
import Timeline from "./Timeline";
import { fmtInterval, fmtStamp } from "./format";

export default function App() {
  const [scenarios, setScenarios] = useState([]);
  const [contracts, setContracts] = useState([]);
  const [contractNo, setContractNo] = useState(null);
  const [detail, setDetail] = useState(null);
  const [scenario, setScenario] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState(null);
  const [tab, setTab] = useState("timeline");
  const [theme, setTheme] = useState("system");

  useEffect(() => {
    api
      .scenarios()
      .then((payload) => {
        setScenarios(payload.scenarios);
        if (payload.scenarios.length && !contractNo) {
          setContractNo(payload.scenarios[0].contract_no);
          setScenario(payload.scenarios[0]);
        }
      })
      .catch((error) => setBanner({ kind: "critical", text: error.message }));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!contractNo) return;
    refresh();
  }, [contractNo]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    document.documentElement.dataset.theme = theme === "system" ? "" : theme;
  }, [theme]);

  async function refresh() {
    if (!contractNo) return;
    setBusy(true);
    try {
      const [detailPayload, list] = await Promise.all([
        api.contract(contractNo),
        api.contracts(),
      ]);
      setDetail(detailPayload);
      setContracts(list.contracts);
      const meta =
        scenarios.find((s) => s.contract_no === contractNo) ??
        { contract_no: contractNo, title: contractNo, story: "", business_from: "2026-01-01T00:00:00Z", business_to: "2027-01-01T00:00:00Z", as_of_early: "2026-01-01T00:00:00Z", as_of_late: "2026-12-01T00:00:00Z" };
      setScenario(meta);
      const data = await api.timeline(contractNo, {
        business_from: meta.business_from,
        business_to: meta.business_to,
        as_of_a: meta.as_of_early,
        as_of_b: meta.as_of_late,
      });
      setTimeline(data);
    } catch (error) {
      setBanner({ kind: "critical", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  const currentSegments = useMemo(
    () => (detail?.versions ?? []).filter((v) => v.current),
    [detail],
  );

  async function resetDemo() {
    setBusy(true);
    try {
      const payload = await api.resetDemo();
      setScenarios(payload.scenarios);
      setTimeline(null);
      await refresh();
    } catch (error) {
      setBanner({ kind: "critical", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  function pickContract(no) {
    setContractNo(no);
    setBanner(null);
    setTab("timeline");
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <h1>合同双时态追溯</h1>
          <p>同一份合同，两个时间轴：业务何时生效，系统何时开始／不再这样认为。</p>
        </div>
        <div className="topbar-actions">
          <div className="theme-switch" role="group" aria-label="主题">
            {["system", "light", "dark"].map((mode) => (
              <button
                key={mode}
                type="button"
                className={theme === mode ? "is-active" : ""}
                onClick={() => setTheme(mode)}
              >
                {mode === "system" ? "跟随系统" : mode === "light" ? "浅色" : "深色"}
              </button>
            ))}
          </div>
          <button type="button" className="ghost" onClick={refresh} disabled={busy}>
            {busy ? "刷新中…" : "刷新"}
          </button>
        </div>
      </header>

      {banner && (
        <div className={`alert ${banner.kind}`} role="alert">
          <span>{banner.text}</span>
          <button type="button" className="icon-button" onClick={() => setBanner(null)}>
            ×
          </button>
        </div>
      )}

      <nav className="scenario-bar" aria-label="演示场景">
        {scenarios.map((item) => (
          <button
            key={item.contract_no}
            type="button"
            className={`scenario-chip ${item.contract_no === contractNo ? "is-active" : ""}`}
            onClick={() => pickContract(item.contract_no)}
          >
            <span className="scenario-title">{item.title}</span>
            <span className="scenario-no mono">{item.contract_no}</span>
          </button>
        ))}
        <div className="scenario-bar-spacer" />
        <div className="contract-select">
          <label className="field">
            <span>全部合同</span>
            <select value={contractNo ?? ""} onChange={(e) => pickContract(e.target.value)}>
              {contracts.map((c) => (
                <option key={c.contract_no} value={c.contract_no}>
                  {c.contract_no}
                </option>
              ))}
            </select>
          </label>
        </div>
      </nav>

      {scenario && (
        <section className="scenario-head">
          <div>
            <h2>{scenario.title}</h2>
            <p>{scenario.story}</p>
          </div>
          <div className="scenario-meta">
            <div>
              <dt>查询时点 A</dt>
              <dd className="mono">{fmtStamp(scenario.as_of_early)}</dd>
            </div>
            <div>
              <dt>查询时点 B</dt>
              <dd className="mono">{fmtStamp(scenario.as_of_late)}</dd>
            </div>
            <div>
              <dt>业务窗口</dt>
              <dd className="mono">
                {fmtInterval(scenario.business_from, scenario.business_to)}
              </dd>
            </div>
          </div>
        </section>
      )}

      <div className="segmented-tabs" role="tablist">
        {[
          ["timeline", "时间线与差异"],
          ["ledger", "版本账本"],
          ["probe", "点查核对"],
          ["write", "更正与冲突"],
        ].map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? "is-active" : ""}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "timeline" && (
        <div className="stack">
          <section className="card">
            <Timeline timeline={timeline} onProbe={() => setTab("probe")} />
          </section>
          <DiffTable timeline={timeline} />
        </div>
      )}

      {tab === "ledger" && (
        <div className="stack">
          <Ledger detail={detail} />
          <RequestList detail={detail} />
        </div>
      )}

      {tab === "probe" && (
        <div className="stack">
          <ProbePanel
            contractNo={contractNo}
            asOfA={scenario?.as_of_early}
            asOfB={scenario?.as_of_late}
          />
          <DiffTable timeline={timeline} />
        </div>
      )}

      {tab === "write" && (
        <div className="stack">
          <CorrectionPanel contractNo={contractNo} detail={detail} onApplied={refresh} />
          <ConflictPanel
            contractNo={contractNo}
            detail={detail}
            onApplied={refresh}
            onReset={resetDemo}
          />
          <section className="card">
            <h3>当前生效段</h3>
            <ul className="segments">
              {currentSegments.map((v) => (
                <li key={v.id}>
                  <span className="mono">{fmtInterval(v.valid_from, v.valid_to)}</span>
                  <span className="strong">¥{v.amount.toLocaleString("zh-CN")}</span>
                  <span className="muted">{v.customer}</span>
                  <span className="version-chip">#{v.id}</span>
                  <span className="muted small">{v.source_request_id}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}

      <footer className="foot">
        <span>FastAPI + SQLite + React</span>
        <span className="muted">
          所有区间按 [开始, 结束) 处理；系统时刻一律以 UTC 展示与提交。
        </span>
      </footer>
    </div>
  );
}
