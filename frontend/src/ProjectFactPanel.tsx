import { API_BASE } from "./api";
import { useEffect, useState } from "react";

const API = `${API_BASE}/api/project-facts`;
const EVIDENCE_STATUSES = ["已验证", "需要补充", "计划实现", "禁止写入简历"];

type FactItem = { content: string; evidence_status: string };
type Tool = { name: string; usage: string; level: string; evidence_status: string };
type Evidence = { type: string; reference: string; visibility: string; evidence_status: string };
type FactCard = {
  project_id: string; project_name: string; project_type: string; ownership: string; ownership_note: string; fact_status: string;
  real_problem: FactItem[]; completed_features: FactItem[]; technology_and_ai_tools: Tool[]; errors_and_failures: FactItem[]; debugging_methods: FactItem[];
  completion: { status: string; completed_scope: FactItem[]; remaining_scope: FactItem[]; last_verified_at: string };
  evidence: Evidence[]; do_not_exaggerate: FactItem[]; updated_at: string;
};
type FactListKey = "real_problem" | "completed_features" | "errors_and_failures" | "debugging_methods" | "do_not_exaggerate";

function StatusBadge({ status }: { status: string }) {
  const classes: Record<string, string> = { "已验证": "verified", "需要补充": "needs-proof", "计划实现": "planned", "禁止写入简历": "forbidden" };
  return <span className={`evidence-status ${classes[status] || ""}`}>{status}</span>;
}

function FactList({ title, items }: { title: string; items: FactItem[] }) {
  return <section className="fact-section"><h3>{title}</h3><ul>{items.map((item, index) => <li key={`${index}-${item.content}`}>{item.content} <StatusBadge status={item.evidence_status} /></li>)}</ul></section>;
}

function StatusSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <select value={value} onChange={(event) => onChange(event.target.value)}>{EVIDENCE_STATUSES.map((status) => <option key={status}>{status}</option>)}</select>;
}

function FactItemsEditor({ title, items, onChange }: { title: string; items: FactItem[]; onChange: (items: FactItem[]) => void }) {
  const update = (index: number, patch: Partial<FactItem>) => onChange(items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  return <section className="fact-edit-section"><h3>{title}</h3>{items.map((item, index) => <div className="fact-edit-row" key={index}>
    <textarea value={item.content} onChange={(event) => update(index, { content: event.target.value })} />
    <StatusSelect value={item.evidence_status} onChange={(value) => update(index, { evidence_status: value })} />
    <button type="button" onClick={() => onChange(items.filter((_, itemIndex) => itemIndex !== index))}>删除</button>
  </div>)}<button className="fact-add-button" type="button" onClick={() => onChange([...items, { content: "", evidence_status: "需要补充" }])}>＋ 添加一条</button></section>;
}

function FactCardView({ card, onEdit, onConfirm, busy }: { card: FactCard; onEdit: () => void; onConfirm: () => void; busy: boolean }) {
  return <article className="project-fact-card">
    <header><div><p className="card-label">{card.project_type} · {card.fact_status === "confirmed" ? "已确认" : "草稿待核实"}</p><h2>{card.project_name}</h2><p>{card.ownership}：{card.ownership_note}</p></div><span>{card.completion.status}</span></header>
    <div className="fact-card-actions"><button className="secondary-button" type="button" onClick={onEdit}>修改事实</button>{card.fact_status !== "confirmed" && <button className="primary-button" type="button" onClick={onConfirm} disabled={busy}>{busy ? "确认中…" : "确认事实卡"}</button>}</div>
    {card.fact_status !== "confirmed" && <p className="fact-confirm-note">确认代表你已核对整张事实卡；只有“已验证”的内容会被 Agent 作为可写入简历的证据。</p>}
    <FactList title="解决的真实问题" items={card.real_problem} />
    <FactList title="已完成功能" items={card.completed_features} />
    <section className="fact-section"><h3>技术与 AI 工具</h3><ul>{card.technology_and_ai_tools.map((tool, index) => <li key={`${index}-${tool.name}`}><strong>{tool.name}</strong> · {tool.usage} <small>（{tool.level}）</small> <StatusBadge status={tool.evidence_status} /></li>)}</ul></section>
    <FactList title="错误与失败" items={card.errors_and_failures} />
    <FactList title="调试与验证方法" items={card.debugging_methods} />
    <section className="fact-section"><h3>当前完成度</h3><p>已完成：</p><ul>{card.completion.completed_scope.map((item, index) => <li key={`${index}-${item.content}`}>{item.content} <StatusBadge status={item.evidence_status} /></li>)}</ul><p>待做：</p><ul>{card.completion.remaining_scope.map((item, index) => <li key={`${index}-${item.content}`}>{item.content} <StatusBadge status={item.evidence_status} /></li>)}</ul><small>最后核对：{card.completion.last_verified_at || "未记录"}</small></section>
    <section className="fact-section"><h3>展示证据</h3><ul>{card.evidence.map((evidence, index) => <li key={`${index}-${evidence.reference}`}><strong>{evidence.type}</strong> · {evidence.reference} <small>（{evidence.visibility}）</small> <StatusBadge status={evidence.evidence_status} /></li>)}</ul></section>
    <FactList title="禁止夸大" items={card.do_not_exaggerate} />
  </article>;
}

function FactCardEditor({ card, onChange, onCancel, onSave, busy }: { card: FactCard; onChange: (card: FactCard) => void; onCancel: () => void; onSave: () => void; busy: boolean }) {
  const set = <K extends keyof FactCard>(key: K, value: FactCard[K]) => onChange({ ...card, [key]: value });
  const setFactList = (key: FactListKey, items: FactItem[]) => set(key, items);
  const updateTool = (index: number, patch: Partial<Tool>) => set("technology_and_ai_tools", card.technology_and_ai_tools.map((tool, itemIndex) => itemIndex === index ? { ...tool, ...patch } : tool));
  const updateEvidence = (index: number, patch: Partial<Evidence>) => set("evidence", card.evidence.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  return <article className="project-fact-card fact-editor">
    <p className="card-label">正在修改 · 保存后自动转为草稿</p>
    <div className="fact-edit-grid">
      <label>项目名称<input value={card.project_name} onChange={(event) => set("project_name", event.target.value)} /></label>
      <label>项目类型<input value={card.project_type} onChange={(event) => set("project_type", event.target.value)} /></label>
      <label>负责方式<input value={card.ownership} onChange={(event) => set("ownership", event.target.value)} /></label>
      <label>负责内容<textarea value={card.ownership_note} onChange={(event) => set("ownership_note", event.target.value)} /></label>
    </div>
    <FactItemsEditor title="解决的真实问题" items={card.real_problem} onChange={(items) => setFactList("real_problem", items)} />
    <FactItemsEditor title="已完成功能" items={card.completed_features} onChange={(items) => setFactList("completed_features", items)} />
    <section className="fact-edit-section"><h3>技术与 AI 工具</h3>{card.technology_and_ai_tools.map((tool, index) => <div className="fact-tool-row" key={index}>
      <input aria-label="工具名称" value={tool.name} onChange={(event) => updateTool(index, { name: event.target.value })} /><textarea aria-label="工具用途" value={tool.usage} onChange={(event) => updateTool(index, { usage: event.target.value })} /><input aria-label="使用程度" value={tool.level} onChange={(event) => updateTool(index, { level: event.target.value })} /><StatusSelect value={tool.evidence_status} onChange={(value) => updateTool(index, { evidence_status: value })} /><button type="button" onClick={() => set("technology_and_ai_tools", card.technology_and_ai_tools.filter((_, itemIndex) => itemIndex !== index))}>删除</button>
    </div>)}<button className="fact-add-button" type="button" onClick={() => set("technology_and_ai_tools", [...card.technology_and_ai_tools, { name: "", usage: "", level: "实际使用", evidence_status: "需要补充" }])}>＋ 添加工具</button></section>
    <FactItemsEditor title="错误与失败" items={card.errors_and_failures} onChange={(items) => setFactList("errors_and_failures", items)} />
    <FactItemsEditor title="调试与验证方法" items={card.debugging_methods} onChange={(items) => setFactList("debugging_methods", items)} />
    <section className="fact-edit-section"><h3>当前完成度</h3><div className="fact-edit-grid"><label>当前状态<input value={card.completion.status} onChange={(event) => set("completion", { ...card.completion, status: event.target.value })} /></label><label>最后核对日期<input type="date" value={card.completion.last_verified_at} onChange={(event) => set("completion", { ...card.completion, last_verified_at: event.target.value })} /></label></div><FactItemsEditor title="已完成" items={card.completion.completed_scope} onChange={(items) => set("completion", { ...card.completion, completed_scope: items })} /><FactItemsEditor title="待做" items={card.completion.remaining_scope} onChange={(items) => set("completion", { ...card.completion, remaining_scope: items })} /></section>
    <section className="fact-edit-section"><h3>展示证据</h3>{card.evidence.map((item, index) => <div className="fact-evidence-row" key={index}>
      <input aria-label="证据类型" value={item.type} onChange={(event) => updateEvidence(index, { type: event.target.value })} /><textarea aria-label="证据内容" value={item.reference} onChange={(event) => updateEvidence(index, { reference: event.target.value })} /><input aria-label="可见性" value={item.visibility} onChange={(event) => updateEvidence(index, { visibility: event.target.value })} /><StatusSelect value={item.evidence_status} onChange={(value) => updateEvidence(index, { evidence_status: value })} /><button type="button" onClick={() => set("evidence", card.evidence.filter((_, itemIndex) => itemIndex !== index))}>删除</button>
    </div>)}<button className="fact-add-button" type="button" onClick={() => set("evidence", [...card.evidence, { type: "", reference: "", visibility: "private", evidence_status: "需要补充" }])}>＋ 添加证据</button></section>
    <FactItemsEditor title="禁止夸大" items={card.do_not_exaggerate} onChange={(items) => setFactList("do_not_exaggerate", items)} />
    <div className="fact-editor-actions"><button className="secondary-button" type="button" onClick={onCancel} disabled={busy}>取消</button><button className="primary-button" type="button" onClick={onSave} disabled={busy}>{busy ? "保存中…" : "保存修改"}</button></div>
  </article>;
}

export function ProjectFactPanel() {
  const [cards, setCards] = useState<FactCard[]>([]); const [editing, setEditing] = useState<FactCard | null>(null);
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [message, setMessage] = useState("");
  useEffect(() => { fetch(API).then((response) => { if (!response.ok) throw new Error("request failed"); return response.json(); }).then((result) => setCards(result.items || [])).catch(() => setError("暂时无法读取本地项目事实卡，请确认后端已启动。")).finally(() => setLoading(false)); }, []);
  const replaceCard = (card: FactCard) => setCards((current) => current.map((item) => item.project_id === card.project_id ? card : item));
  async function save() { if (!editing) return; setBusy(true); setError(""); setMessage(""); try { const response = await fetch(`${API}/${editing.project_id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(editing) }); const result = await response.json(); if (!response.ok) throw new Error(result.detail || "保存失败"); replaceCard(result.item); setEditing(null); setMessage("修改已保存，事实卡已回到草稿状态，请核对后再确认。"); } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "保存失败。"); } finally { setBusy(false); } }
  async function confirm(card: FactCard) { setBusy(true); setError(""); setMessage(""); try { const response = await fetch(`${API}/${card.project_id}/confirm`, { method: "POST" }); const result = await response.json(); if (!response.ok) throw new Error(result.detail || "确认失败"); replaceCard(result.item); setMessage("事实卡已确认；其中标记为“已验证”的内容现在可以参与 Agent 匹配。"); } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "确认失败。"); } finally { setBusy(false); } }
  if (loading) return <p className="market-note">正在读取本地项目事实卡…</p>;
  if (!cards.length && !error) return <p className="empty-jobs">还没有本地项目事实卡。</p>;
  return <div className="project-fact-list">{message && <p className="status-message success" role="status">{message}</p>}{error && <p className="status-message error" role="alert">{error}</p>}{cards.map((card) => editing?.project_id === card.project_id ? <FactCardEditor key={card.project_id} card={editing} onChange={setEditing} onCancel={() => setEditing(null)} onSave={save} busy={busy} /> : <FactCardView key={card.project_id} card={card} onEdit={() => { setEditing(JSON.parse(JSON.stringify(card))); setError(""); setMessage(""); }} onConfirm={() => confirm(card)} busy={busy} />)}</div>;
}
