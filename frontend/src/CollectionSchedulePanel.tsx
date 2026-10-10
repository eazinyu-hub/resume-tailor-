import { API_BASE } from "./api";
import { useEffect, useRef, useState } from "react";

export type CollectionSettings = { source_keys: string[]; directions: string[]; per_source_limit: number; staging_limit: number; include_uncertain: boolean };
type Schedule = {
  enabled: boolean; interval_minutes: number; options: CollectionSettings | null;
  next_run_at: string | null; last_run_id: string | null; runner_running: boolean; runtime_error: string | null;
  last_event: { kind: string; message: string; at: string } | null;
  last_result: { run_id: string; status: string; finished_at: string | null } | null;
};
const API = `${API_BASE}/api/collector/schedule`;
const formatTime = (value: string) => new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
const frequency = (minutes: number) => `每 ${minutes / 60} 小时`;

async function read(response: Response): Promise<Schedule> {
  const result = await response.json();
  if (response.status === 404 && result.detail === "Not Found") throw new Error("当前后端还没加载定时采集功能，请重启本项目后端后刷新。");
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "定时设置请求失败");
  return result;
}

export function CollectionSchedulePanel({ options, sourceNames, directionNames, onRunChanged }: {
  options: CollectionSettings; sourceNames: Record<string, string>; directionNames: Record<string, string>; onRunChanged: () => void;
}) {
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [interval, setIntervalMinutes] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [readError, setReadError] = useState("");
  const [message, setMessage] = useState("");
  const [clock, setClock] = useState(Date.now());
  const [refreshVersion, setRefreshVersion] = useState(0);
  const callback = useRef(onRunChanged);
  const signature = useRef("");
  const writeRevision = useRef(0);
  const writing = useRef(false);
  useEffect(() => { callback.current = onRunChanged; }, [onRunChanged]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      const revision = writeRevision.current;
      try {
        if (writing.current) return;
        const next = await read(await fetch(API, { signal: controller.signal }));
        if (controller.signal.aborted || revision !== writeRevision.current) return;
        setSchedule(next);
        setIntervalMinutes(current => current ?? next.interval_minutes);
        setReadError("");
        const nextSignature = `${next.last_run_id || ""}:${next.last_result?.finished_at || ""}`;
        if (signature.current && nextSignature !== signature.current) callback.current();
        signature.current = nextSignature;
      } catch (reason) {
        if (!controller.signal.aborted && revision === writeRevision.current) setReadError(reason instanceof Error ? reason.message : "无法读取定时状态");
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 10000);
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [refreshVersion]);
  useEffect(() => {
    if (!schedule?.enabled) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [schedule?.enabled]);

  async function save(pause: boolean) {
    if (writing.current) return;
    writing.current = true;
    writeRevision.current += 1;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const next = await read(await fetch(pause ? `${API}/pause` : API, pause ? { method: "POST" } : {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ interval_minutes: interval ?? 360, options }),
      }));
      setSchedule(next);
      setClock(Date.now());
      setMessage(pause ? "已暂停后续任务。已经开始的一轮仍会完成。" : "已保存并启用；按上方当前配置定时执行，不会立即采集。修改频率或配置会从现在重新计算下次时间。");
      setRefreshVersion(value => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存定时设置失败");
    } finally { writing.current = false; setSaving(false); }
  }

  const seconds = schedule?.next_run_at ? Math.max(0, Math.ceil((Date.parse(schedule.next_run_at) - clock) / 1000)) : 0;
  const countdown = seconds ? `${Math.floor(seconds / 3600)} 小时 ${Math.floor(seconds % 3600 / 60)} 分 ${seconds % 60} 秒` : "已到计划时间，等待执行器检查（约 15 秒内）";
  const saved = schedule?.options;
  const changed = schedule?.enabled && (schedule.interval_minutes !== interval || JSON.stringify(saved) !== JSON.stringify(options));
  return <section className="collection-schedule" aria-labelledby="schedule-heading">
    <div className="batch-result-title"><h3 id="schedule-heading">定时采集</h3><span className={schedule?.enabled ? "schedule-enabled" : "schedule-paused"}>{schedule ? schedule.enabled ? "已启用" : "已暂停" : "读取中"}</span></div>
    <p className="batch-note">后端运行时自动执行；关机、休眠或停服期间不运行。关闭网页不影响采集。重启不补跑积压任务，结果仍需你确认入库。</p>
    {(readError || error) && <p className="market-error" role="alert">{error || readError}</p>}
    {schedule?.runtime_error && <p className="market-error" role="alert">{schedule.runtime_error}</p>}
    {schedule?.enabled && !schedule.runner_running && <p className="market-error" role="alert">当前定时执行器没有运行，请检查或重启后端。</p>}
    {schedule && <>
      <div className="schedule-controls">
        <label>运行频率 <select value={interval ?? 360} disabled={saving} onChange={event => setIntervalMinutes(Number(event.target.value))}>{[60, 360, 720, 1440].map(value => <option key={value} value={value}>{frequency(value)}{value === 360 ? "（建议）" : ""}</option>)}</select></label>
        <button type="button" className="primary-button" disabled={saving || !!schedule.runtime_error || !options.source_keys.length || !options.directions.length} onClick={() => void save(false)}>{saving ? "保存中…" : schedule.enabled ? "保存定时设置" : "启用定时采集"}</button>
        {schedule.enabled && <button type="button" className="secondary-button" disabled={saving} onClick={() => void save(true)}>暂停定时采集</button>}
      </div>
      <p className="batch-note">启用 / 保存时，会固定使用上方的来源、方向、每源处理上限和每次暂存上限。之后修改手动采集配置，不会自动改动定时任务。</p>
      {changed && <p className="schedule-changed">上方配置或频率与已保存的定时设置不同，点击“保存定时设置”后才生效。</p>}
      {saved && <div className="schedule-snapshot"><strong>已保存的定时配置 · {frequency(schedule.interval_minutes)}</strong><p>来源：{saved.source_keys.map(key => sourceNames[key] || key).join("、")}</p><p>方向：{saved.directions.map(key => directionNames[key] || key).join("、")}</p><p>每源最多 {saved.per_source_limit} 条 · 每轮最多暂存 {saved.staging_limit} 条 · {saved.include_uncertain ? "也暂存条件待核实岗位" : "只暂存通过初筛岗位"}</p></div>}
      {schedule.enabled && schedule.next_run_at && <div className="schedule-next"><strong>下次运行（北京时间）</strong><p>{formatTime(schedule.next_run_at)}</p><small>还需等待：{countdown}</small></div>}
      {!schedule.enabled && <p className="batch-note">目前不会自动采集。你可以继续使用上方“开始采集”手动运行一轮。</p>}
      {schedule.last_event && <p className="batch-note">最近状态：{schedule.last_event.message}</p>}
    </>}
    {message && <p className="status-message success" role="status">{message}</p>}
  </section>;
}
