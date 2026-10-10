import { API_BASE } from "./api";
import { useEffect, useRef, useState } from "react";

type ContextPreview = {
  status: string; context_hash: string; disclosure: string;
  context: {
    job: { id: number; title: string; description: string };
    project: { project_name: string; project_type: string; ownership: string; ownership_note: string };
    allowed_facts: { fact_id: string; content: string; source_field: string }[];
    restrictions: string[];
    market_reference: { role_family: string; similar_jobs: { title: string; shared_signals: { section: string; name: string }[] }[] };
  };
};
type CandidateResult = {
  status: string; preview_id: string; model: string; note: string; usage?: { total_tokens?: number };
  candidates: { focus: string; bullets: { text: string; fact_ids: string[]; facts: string[]; jd_evidence: string; reason: string }[] }[];
  gaps: string[]; risks: string[];
};
export type AppliedDraft = { jobTitle: string; sections: Record<string, string[]>; changes: string[]; source?: string };

async function readJson(response: Response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || data.detail || "请求失败");
  return data;
}

export function DeepSeekCandidatePanel({ jobId, configured, onDraftApplied }: { jobId: number; configured: boolean; onDraftApplied: (draft: AppliedDraft) => void }) {
  const [preview, setPreview] = useState<ContextPreview | null>(null);
  const [result, setResult] = useState<CandidateResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [applying, setApplying] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [applyStatus, setApplyStatus] = useState("");
  const [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => {
    pending.current?.abort();
    setPreview(null); setResult(null); setError(""); setPreviewing(false); setGenerating(false);
    setApplying(false); setSelectedIndex(null); setApplyStatus("");
    return () => pending.current?.abort();
  }, [jobId]);

  async function loadPreview() {
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setPreviewing(true); setError(""); setResult(null); setSelectedIndex(null); setApplyStatus("");
    try {
      const data = await readJson(await fetch(`${API_BASE}/api/jobs/${jobId}/agent-v1/candidate-context`, { signal: controller.signal }));
      if (!controller.signal.aborted) setPreview(data);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "无法准备发送内容");
    } finally { if (!controller.signal.aborted) setPreviewing(false); }
  }

  async function applySelected() {
    if (!result || selectedIndex === null) return;
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setApplying(true); setError(""); setApplyStatus("");
    try {
      const data = await readJson(await fetch(`${API_BASE}/api/jobs/${jobId}/agent-v1/candidates/apply`, {
        method: "POST", signal: controller.signal, headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preview_id: result.preview_id, candidate_index: selectedIndex }),
      }));
      if (controller.signal.aborted) return;
      onDraftApplied(data.draft);
      setApplyStatus(data.backup_created ? "已应用到当前岗位草稿；旧草稿已备份。" : "已应用到当前岗位草稿。");
      setSelectedIndex(null);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "应用候选失败，请重新打开当前岗位核对草稿");
    } finally { if (!controller.signal.aborted) setApplying(false); }
  }

  function cancelCandidates() {
    if (applying) return;
    setResult(null); setSelectedIndex(null); setApplyStatus("");
  }

  async function generate() {
    if (!preview) return;
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setGenerating(true); setError(""); setResult(null);
    try {
      const data = await readJson(await fetch(`${API_BASE}/api/jobs/${jobId}/agent-v1/candidates`, {
        method: "POST", signal: controller.signal, headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ context_hash: preview.context_hash }),
      }));
      if (!controller.signal.aborted) setResult(data);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "生成候选失败");
    } finally { if (!controller.signal.aborted) setGenerating(false); }
  }

  return <section className="deepseek-candidates" aria-label="DeepSeek 项目描述候选">
    <div className="candidate-heading"><div><strong>AI 简历适配工作台 · 项目描述候选</strong><span>先预览发送内容，确认后才调用一次；本步不会保存或覆盖简历。</span></div>
      <button className="secondary-button" type="button" disabled={!configured || previewing || generating} onClick={loadPreview}>{previewing ? "准备中…" : preview ? "重新检查发送内容" : "查看将发送的内容"}</button>
    </div>
    {!configured && <p className="candidate-warning">请先完成 DeepSeek 配置和连接测试。</p>}
    {error && <div className="candidate-failure" role="alert"><strong>候选没有生成，因此草稿没有改变</strong><p>{error}</p><span>这是保护机制：失败时不会自动改用旧规则，也不会覆盖现有草稿。请先检查原因，再决定是否重新调用 DeepSeek。</span></div>}
    {preview && <div className="candidate-context">
      <p>{preview.disclosure}</p>
      <details><summary>当前 JD · {preview.context.job.title}</summary><pre>{preview.context.job.description}</pre></details>
      <details open><summary>允许模型引用的已验证事实（{preview.context.allowed_facts.length} 条）</summary><ul>{preview.context.allowed_facts.map(fact => <li key={fact.fact_id}><code>{fact.fact_id}</code><span>{fact.content}</span></li>)}</ul></details>
      <details open><summary>必须遵守的限制（{preview.context.restrictions.length} 条）</summary>{preview.context.restrictions.length ? <ul>{preview.context.restrictions.map(item => <li key={item}>{item}</li>)}</ul> : <p>当前没有额外限制项。</p>}</details>
      <details><summary>脱敏市场参考 · {preview.context.market_reference.role_family}（{preview.context.market_reference.similar_jobs.length} 条）</summary>{preview.context.market_reference.similar_jobs.length ? <ul>{preview.context.market_reference.similar_jobs.map((job, index) => <li key={`${index}-${job.title}`}>{job.title}：{job.shared_signals.map(signal => signal.name).join("、")}</li>)}</ul> : <p>没有足够相似样本，本次不凑数。</p>}</details>
      <div className="candidate-confirm"><p>点击后会把上面内容发送给 DeepSeek 并产生一次 API 调用。切换岗位或关闭等待不会保证取消供应商计费。</p><button className="primary-button" type="button" disabled={generating} onClick={generate}>{generating ? "生成中，请勿重复点击…" : "确认并生成候选（调用 1 次）"}</button></div>
    </div>}
    {result && <div className="candidate-results">
      <p className="agent-ready">{result.note} · {result.model}{result.usage?.total_tokens ? ` · ${result.usage.total_tokens} tokens` : ""}</p>
      {result.candidates.map((candidate, index) => <article key={`${index}-${candidate.focus}`} className={`candidate-version${selectedIndex === index ? " selected" : ""}`}><h3>候选 {index + 1} · {candidate.focus}</h3>
        {candidate.bullets.map((bullet, bulletIndex) => <section key={`${bulletIndex}-${bullet.text}`}><strong>{bullet.text}</strong><p><b>岗位依据：</b>{bullet.jd_evidence}</p><p><b>修改原因：</b>{bullet.reason}</p><details><summary>查看引用的原事实（{bullet.fact_ids.length} 条）</summary><ul>{bullet.facts.map((fact, factIndex) => <li key={`${bullet.fact_ids[factIndex]}-${factIndex}`}><code>{bullet.fact_ids[factIndex]}</code>{fact}</li>)}</ul></details></section>)}
        <button className="secondary-button" type="button" disabled={applying} onClick={() => setSelectedIndex(index)}>{selectedIndex === index ? "已选择这个版本" : "选择这个版本"}</button>
      </article>)}
      {(result.gaps.length > 0 || result.risks.length > 0) && <div className="candidate-cautions">{result.gaps.length > 0 && <section><h3>真实缺口</h3><ul>{result.gaps.map(item => <li key={item}>{item}</li>)}</ul></section>}{result.risks.length > 0 && <section><h3>仍需人工核对</h3><ul>{result.risks.map(item => <li key={item}>{item}</li>)}</ul></section>}</div>}
      {selectedIndex !== null && <div className="candidate-apply-confirm"><p>确认后只会替换当前岗位 #{jobId} 的草稿，其他岗位不变；旧草稿会先备份。仍可继续编辑并导出 Word / PDF。</p><button className="primary-button" type="button" disabled={applying} onClick={applySelected}>{applying ? "正在应用…" : `确认应用候选 ${selectedIndex + 1}`}</button></div>}
      <div className="candidate-result-actions"><button className="secondary-button" type="button" disabled={applying} onClick={cancelCandidates}>取消本次候选</button><span>取消只清除本次候选，不写数据库，旧草稿不变。</span></div>
      {applyStatus && <p className="agent-ready" role="status">{applyStatus}</p>}
    </div>}
  </section>;
}
