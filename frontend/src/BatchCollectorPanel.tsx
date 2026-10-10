import { API_BASE } from "./api";
import { useEffect, useRef, useState } from "react";
import { CollectionSchedulePanel } from "./CollectionSchedulePanel";
import type { CollectionSettings as Settings } from "./CollectionSchedulePanel";

const API = `${API_BASE}/api/collector/batch`;
type Source = { key: string; company: string; provider: string; url: string; note: string };
type Counts = { scanned: number; accepted: number; needs_review: number; excluded: number; added: number; updated: number; duplicates: number; limited: number; errors: number };
type Run = {
  id: string; status: string; trigger?: "manual" | "scheduled"; started_at: string; finished_at: string | null; counts: Counts; error: string | null;
  sources: { key: string; company: string; status: string; scanned: number; total: number | null; truncated: boolean; error: string | null; next_allowed_at: string | null }[];
  items: { title: string; company: string | null; source_url: string | null; decision: string; action: string; reasons: string[] }[];
};
type State = { sources: Source[]; directions: Record<string, string>; settings: Settings; latest: Run | null; history: Pick<Run, "id" | "status" | "started_at">[]; note: string };
const STATUS: Record<string, string> = { queued: "排队中", running: "采集中", completed: "已完成", partial_failure: "部分失败", failed: "失败", interrupted: "已中断" };
const DECISION: Record<string, string> = { accepted: "通过初筛", needs_review: "条件待核实", excluded: "明确排除", invalid: "数据异常" };
const ACTION: Record<string, string> = { staged: "已加入待确认区", updated: "已暂存更新版本", duplicate: "重复，已跳过", review_only: "未暂存", excluded: "未暂存", limit_reached: "达到暂存上限", invalid: "解析失败" };
const active = (run: Run | null | undefined) => !!run && ["queued", "running"].includes(run.status);
const timeLabel = (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false });

async function readJson(response: Response) {
  const data = await response.json();
  if (response.status === 404 && data.detail === "Not Found") throw new Error("当前后端尚未加载批量采集功能，请重启本项目后端后刷新。");
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "请求失败，请检查配置或后端状态");
  return data;
}

export function BatchCollectorPanel({ onCompleted }: { onCompleted: () => void }) {
  const [state, setState] = useState<State | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [historyRun, setHistoryRun] = useState<Run | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const callback = useRef(onCompleted);
  const previousRun = useRef<Run | null>(null);
  const historyRequest = useRef(0);
  useEffect(() => { callback.current = onCompleted; }, [onCompleted]);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const next: State = await readJson(await fetch(API, { signal: controller.signal }));
        if (controller.signal.aborted) return;
        setState(next);
        setSettings(current => current || next.settings);
        setError("");
        if (next.latest && !active(next.latest) && (active(previousRun.current) || previousRun.current?.id !== next.latest.id)) callback.current();
        previousRun.current = next.latest;
        if (active(next.latest)) timer = setTimeout(refresh, 1500);
      } catch (reason) {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : "读取采集状态失败");
        if (active(previousRun.current)) timer = setTimeout(refresh, 5000);
      }
    };
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [retry]);

  async function start() {
    if (!settings) return;
    setStarting(true);
    setError("");
    historyRequest.current += 1;
    setHistoryRun(null);
    try {
      const run: Run = await readJson(await fetch(`${API}/runs`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings),
      }));
      previousRun.current = run;
      setState(current => current ? { ...current, latest: run } : current);
      setRetry(current => current + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "启动失败");
    } finally { setStarting(false); }
  }

  async function selectHistory(id: string) {
    const requestId = ++historyRequest.current;
    setHistoryRun(null);
    if (!id) return;
    try {
      const run: Run = await readJson(await fetch(`${API}/runs/${id}`));
      if (requestId === historyRequest.current) setHistoryRun(run);
    } catch (reason) {
      if (requestId === historyRequest.current) setError(reason instanceof Error ? reason.message : "历史记录读取失败");
    }
  }

  function toggle(key: "source_keys" | "directions", value: string) {
    setSettings(current => current ? { ...current, [key]: current[key].includes(value)
      ? current[key].filter(item => item !== value) : [...current[key], value] } : current);
  }

  const busy = starting || active(state?.latest);
  const run = historyRun || state?.latest;
  return <section className="batch-collector" aria-labelledby="batch-heading">
    <div className="batch-heading"><div><p className="card-label">在工作台里完成采集</p><h2 id="batch-heading">一键批量采集</h2></div><span>V1 · 手动 / 定时</span></div>
    <p className="batch-note">选择来源后，系统自动读取 → 检查门槛 → 去重 → 暂存。不会自动写入正式岗位库，也不会自动投递。</p>
    {error && <div className="market-error" role="alert">{error} <button type="button" className="secondary-button" onClick={() => setRetry(current => current + 1)}>刷新状态</button></div>}
    {!state || !settings ? <p className="batch-note">正在读取采集配置…</p> : <>
      <fieldset disabled={busy} className="batch-options">
        <legend>采集配置</legend>
        <div className="batch-sources"><strong>已审核来源</strong>{state.sources.map(source => <label key={source.key}>
          <input type="checkbox" checked={settings.source_keys.includes(source.key)} onChange={() => toggle("source_keys", source.key)} />
          <span>{source.company} <small>{source.provider}</small><small>{source.note}</small></span>
        </label>)}</div>
        <div className="batch-directions"><strong>目标方向</strong>{Object.entries(state.directions).map(([key, label]) => <label key={key}>
          <input type="checkbox" checked={settings.directions.includes(key)} onChange={() => toggle("directions", key)} />{label}
        </label>)}</div>
        <div className="batch-limits">
          <label>每个来源最多处理 <select value={settings.per_source_limit} onChange={event => setSettings({ ...settings, per_source_limit: Number(event.target.value) })}>{[10, 30, 50, 100].map(n => <option key={n} value={n}>{n} 条</option>)}</select></label>
          <label>本次最多暂存 <select value={settings.staging_limit} onChange={event => setSettings({ ...settings, staging_limit: Number(event.target.value) })}>{[5, 10, 20].map(n => <option key={n} value={n}>{n} 条</option>)}</select></label>
        </div>
        <label className="batch-uncertain"><input type="checkbox" checked={settings.include_uncertain} onChange={event => setSettings({ ...settings, include_uncertain: event.target.checked })} />也暂存“条件待核实”的岗位（不代表适合投递）</label>
      </fieldset>
      <p className="batch-note">{state.note}</p>
      <p className="batch-note">默认优先工具与自动化。明确的年限、专业、学历冲突会排除；条件未写清楚的单独标记。只读取一页，不自动翻页；每个来源至少间隔 10 分钟，遇到 403 / 429 暂停。</p>
      <div className="batch-start"><button className="primary-button" type="button" disabled={busy || !settings.source_keys.length || !settings.directions.length} onClick={start}>{busy ? "正在自动采集…" : "开始采集"}</button><span>{busy ? "可切换页面，回来后继续查看任务；请保持后端运行。" : "手动采集只执行一次；下方可另行启用定时采集。"}</span></div>
      <CollectionSchedulePanel options={settings} sourceNames={Object.fromEntries(state.sources.map(source => [source.key, source.company]))} directionNames={state.directions} onRunChanged={() => setRetry(value => value + 1)} />
      {state.history.length > 1 && <label className="batch-history">查看记录 <select value={historyRun?.id || ""} onChange={event => void selectHistory(event.target.value)}><option value="">最近一次</option>{state.history.filter(item => item.id !== state.latest?.id).map(item => <option key={item.id} value={item.id}>{timeLabel(item.started_at)} · {STATUS[item.status] || item.status}</option>)}</select></label>}
    </>}
    {run && <section className="batch-result" aria-label="采集结果">
      <div className="batch-result-title"><h3>{historyRun ? "历史任务" : "最近任务"} · {STATUS[run.status] || run.status}</h3><small>{run.trigger === "scheduled" ? "定时触发" : "手动触发"} · {timeLabel(run.started_at)}</small></div>
      {run.error && <p className="market-error" role="alert">{run.error}</p>}
      <div className="batch-counts" role="status" aria-live="polite">{[
        ["已处理", run.counts.scanned], ["通过初筛", run.counts.accepted], ["待核实", run.counts.needs_review],
        ["已排除", run.counts.excluded], ["新增暂存", run.counts.added], ["更新", run.counts.updated], ["重复", run.counts.duplicates], ["失败", run.counts.errors],
      ].map(([label, value]) => <div key={label}><strong>{value}</strong><span>{label}</span></div>)}</div>
      {!active(run) && run.counts.added + run.counts.updated === 0 && <p className="batch-empty">本次没有新增待确认岗位。请查看排除、待核实、重复或失败原因；零条不代表整个招聘市场没有机会。</p>}
      {run.counts.limited > 0 && <p className="batch-note">另有 {run.counts.limited} 条达到暂存上限，未写入。</p>}
      <ul className="batch-source-results">{run.sources.map(source => <li key={source.key}><span>{source.company} · {STATUS[source.status] || source.status} · 处理 {source.scanned} 条</span>
        {source.truncated && <small>已达本次处理范围，未自动翻页，不代表该来源全部岗位。</small>}
        {source.error && <small className="market-error">{source.error}</small>}
        {source.next_allowed_at && <small>下次可采集：{timeLabel(source.next_allowed_at)}</small>}
      </li>)}</ul>
      {run.items.length > 0 && <details className="batch-details"><summary>查看本次筛选明细（{run.items.length} 条）</summary><div>{run.items.map((item, index) => <details key={`${index}-${item.title}`} className={`batch-item batch-${item.decision}`}>
        <summary><span>{item.title}</span><small>{DECISION[item.decision]} · {ACTION[item.action]}</small></summary>
        <p>{item.company || "公司未记录"}</p><ul>{item.reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul>
        {item.source_url?.startsWith("https://") && <a href={item.source_url} target="_blank" rel="noreferrer">查看原始岗位 ↗</a>}
      </details>)}</div></details>}
    </section>}
  </section>;
}
