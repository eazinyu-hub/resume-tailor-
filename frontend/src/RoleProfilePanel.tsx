import { API_BASE } from "./api";
import { useEffect, useState } from "react";

type Item = { name: string; job_count: number; percentage: number; bonus_count: number; jobs: { id: number; title: string; evidence: string }[] };
type Portrait = { summary: string; resume_focus: string[]; barriers: string[] };
type Profile = { family: string; label: string; sample_count: number; portrait: Portrait; sections: { name: string; items: Item[] }[] };
type Result = { sample_count: number; excluded_duplicates: number; confirmed_count: number; suggested_count: number; profiles: Profile[] };

function PortraitReading({ portrait }: { portrait: Portrait }) {
  return <section className="portrait-reading"><p className="card-label">画像解读</p><p>{portrait.summary}</p>{portrait.resume_focus.length > 0 && <div><strong>简历优先展示</strong><ul>{portrait.resume_focus.map((focus) => <li key={focus}>{focus}</li>)}</ul></div>}{portrait.barriers.length > 0 && <div><strong>样本中常见门槛</strong><span>{portrait.barriers.join("、")}</span></div>}</section>;
}

export function RoleProfilePanel({ jobsVersion, onOpenJob }: { jobsVersion: string; onOpenJob: (jobId: number) => void }) {
  const [result, setResult] = useState<Result | null>(null);
  const [selectedFamily, setSelectedFamily] = useState("");
  const [expanded, setExpanded] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(""); setResult(null);
    fetch(`${API_BASE}/api/market/role-profiles`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error("request failed"); return response.json() as Promise<Result>; })
      .then((data) => { if (!controller.signal.aborted) { setResult(data); setSelectedFamily((current) => current || data.profiles.find((profile) => profile.sample_count > 0)?.family || ""); } })
      .catch(() => { if (!controller.signal.aborted) setError("暂时无法读取方向画像，请确认后端已启动后重试。"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [jobsVersion, refresh]);
  const selected = result?.profiles.find((profile) => profile.family === selectedFamily);
  return <section className="role-profile-panel" aria-labelledby="role-profile-title">
    <div className="market-heading"><div><p className="card-label">岗位样本画像 · 按方向</p><h2 id="role-profile-title">不同方向的要求差异</h2></div><div className="market-actions"><button className="secondary-button" type="button" disabled={loading} onClick={() => setRefresh((value) => value + 1)}>刷新统计</button><button className="secondary-button" type="button" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>{expanded ? "收起画像" : "展开画像"}</button></div></div>
    {expanded && <div>{loading && <p className="market-note">正在按岗位方向整理 JD…</p>}{error && <p className="market-error">{error}</p>}{result && <><p className="market-note">纳入 {result.sample_count} 份 JD · 已确认分类 {result.confirmed_count} 条 · 建议分类 {result.suggested_count} 条 · 排除重复 {result.excluded_duplicates} 条</p><div className="role-family-tabs" role="tablist">{result.profiles.map((profile) => <button key={profile.family} type="button" role="tab" aria-selected={selected?.family === profile.family} className={selected?.family === profile.family ? "active" : ""} onClick={() => setSelectedFamily(profile.family)}>{profile.label}<small>{profile.sample_count} 份</small></button>)}</div>{selected && <div className="role-profile-detail" role="tabpanel"><div className="role-profile-summary"><h3>{selected.label}</h3><span>{selected.sample_count} 份样本</span></div><PortraitReading portrait={selected.portrait} />{selected.sample_count === 0 ? <p className="empty-jobs">当前没有归入这个方向的样本。</p> : <div className="role-sections">{selected.sections.map((section) => <section className="role-section" key={section.name}><h4>{section.name}</h4>{section.items.length === 0 ? <p>暂未从这组 JD 中识别到。</p> : <div className="profile-item-list">{section.items.map((item) => <details key={item.name}><summary><strong>{item.name}</strong><span>{item.job_count}/{selected.sample_count} 份 · {item.percentage}%{item.bonus_count > 0 ? ` · ${item.bonus_count} 条仅为加分项` : ""}</span></summary><ul>{item.jobs.map((job) => <li key={job.id}><a href={`#job-${job.id}`} onClick={() => onOpenJob(job.id)}>#{job.id} {job.title}</a><p>{job.evidence}</p></li>)}</ul></details>)}</div>}</section>)}</div>}</div>}<details className="market-method"><summary>画像口径</summary><p>岗位方向优先使用你确认过的分类；未确认岗位使用可解释关键词建议分类。点击每项可查看原文证据。</p><p>按职责、任职要求、正文提及和加分项标注；过滤识别到的否定表述和福利介绍。加分项单独标记，不能等同于硬性门槛。画像共性至少需 2 份样本支持且占该方向 40%；少量样本仅作初步参考，规则识别仍需人工核对。</p></details></>}</div>}
  </section>;
}
