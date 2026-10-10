import { API_BASE } from "./api";
import { useEffect, useRef, useState } from "react";
import { DeepSeekCandidatePanel, type AppliedDraft } from "./DeepSeekCandidatePanel";

type Fact = { fact_id: string; project_name: string; fact: string; evidence_status: string; write_reason: string };
type Match = {
  requirement: string; category: string; kind: string; jd_evidence: string; supported: boolean;
  gap: string; allowed_in_resume: boolean; matched_facts: Fact[];
};
type Report = {
  status: string; job_title: string; mode: string; target_family_label: string;
  market_sample_count: number; similar_samples: { id: number }[];
  evidence_coverage: { coverage: number | null; supported: number; total: number; note: string };
  formal_resume: { blocked: boolean; message: string };
  change_reasons: string[]; exaggeration_risks: string[]; interviewer_questions: string[];
  self_introduction_preview: string; self_introduction_ready: boolean; fact_match: Match[];
  market_comparison: { sample_note?: string; common_but_not_mentioned?: { section: string; name: string; job_count: number }[] };
};
type DeepSeekStatus = {
  provider: string; configured: boolean; model: string; config_error: string | null;
  key_exposed: boolean; test_sends_personal_data: boolean;
};

export function AgentV1Panel({ jobId, onDraftApplied }: { jobId: number; onDraftApplied: (draft: AppliedDraft) => void }) {
  const [report, setReport] = useState<Report | null>(null);
  const [expanded, setExpanded] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [deepSeek, setDeepSeek] = useState<DeepSeekStatus | null>(null);
  const [connectionMessage, setConnectionMessage] = useState("");
  const [testingConnection, setTestingConnection] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => {
    setReport(null); setError(""); setLoading(false);
    return () => pending.current?.abort();
  }, [jobId]);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/api/ai/deepseek/status`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error("status unavailable");
        return response.json() as Promise<DeepSeekStatus>;
      })
      .then(status => { if (!controller.signal.aborted) setDeepSeek(status); })
      .catch(() => { if (!controller.signal.aborted) setConnectionMessage("无法读取 DeepSeek 配置状态，请确认后端已更新并启动。"); });
    return () => controller.abort();
  }, []);

  async function testDeepSeek() {
    setTestingConnection(true); setConnectionMessage("");
    try {
      const response = await fetch(`${API_BASE}/api/ai/deepseek/test`, { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || "连接失败");
      setConnectionMessage(`${result.message} 模型：${result.model}。${result.usage?.total_tokens ? `本次共 ${result.usage.total_tokens} tokens。` : ""}`);
    } catch (reason) {
      setConnectionMessage(reason instanceof Error ? reason.message : "DeepSeek 连接测试失败。");
    } finally { setTestingConnection(false); }
  }

  async function run() {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true); setError(""); setReport(null); setExpanded(true);
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${jobId}/agent-v1`, { signal: controller.signal });
      if (!response.ok) throw new Error("request failed");
      const data: Report = await response.json();
      if (!["ready", "needs_confirmation"].includes(data.status)) throw new Error("job not found");
      if (!data.evidence_coverage || !Array.isArray(data.fact_match)) throw new Error("backend version mismatch");
      if (!controller.signal.aborted) setReport(data);
    } catch {
      if (!controller.signal.aborted) setError("暂时无法生成分析，请确认岗位仍存在、后端已更新并启动后重试。");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return <section className="agent-v1" aria-label="岗位级分析">
    <div className="section-heading">
      <div><p className="card-label">Agent V1 · 岗位级分析</p><span>当前 JD + 历史样本 + 项目事实 · 不自动覆盖简历</span></div>
      <div className="market-actions">
        {report && <button className="secondary-button" type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "收起分析" : "展开分析"}</button>}
        <button className="primary-button" type="button" onClick={run} disabled={loading}>{loading ? "分析中…" : report ? "重新分析" : "生成岗位级分析"}</button>
      </div>
    </div>
    <div className="ai-connection" aria-label="DeepSeek 连接">
      <div><strong>DeepSeek 生成能力</strong><span>{deepSeek ? deepSeek.configured ? `已配置 · ${deepSeek.model}` : "尚未配置" : "正在读取配置…"}</span></div>
      <button className="secondary-button" type="button" disabled={!deepSeek?.configured || testingConnection} onClick={testDeepSeek}>{testingConnection ? "测试中…" : "测试连接（调用 1 次）"}</button>
      {!deepSeek?.configured && deepSeek && <p>{deepSeek.config_error || "请在 backend/.env 填写 DEEPSEEK_API_KEY，然后重启后端。密钥不会发送到浏览器。"}</p>}
      {connectionMessage && <p role="status">{connectionMessage}</p>}
      <small>连接测试只发送固定文字，不发送简历、JD 或项目事实；不会自动重试。</small>
    </div>
    <DeepSeekCandidatePanel jobId={jobId} configured={!!deepSeek?.configured} onDraftApplied={onDraftApplied} />
    {error && <p className="market-error" role="alert">{error}</p>}
    {report && expanded && <div className="agent-report">
      <h3>{report.job_title}</h3>
      <p className="market-note">{report.mode} · {report.target_family_label} · {report.similar_samples.length} 条相似参考 / {report.market_sample_count} 条同方向历史样本</p>
      <div className="agent-coverage"><strong>{report.evidence_coverage.coverage === null ? "暂无可计分要求" : `${report.evidence_coverage.coverage}%`}</strong><span>直接项目事实覆盖 · {report.evidence_coverage.supported}/{report.evidence_coverage.total} 项</span></div>
      <p className="market-note">{report.evidence_coverage.note}</p>
      <p className={report.formal_resume.blocked ? "agent-blocked" : "agent-ready"}>{report.formal_resume.message}</p>
      <section><h3>调整建议与依据</h3><ul>{report.change_reasons.map(x => <li key={x}>{x}</li>)}</ul></section>
      <details className="agent-evidence"><summary>逐项查看 JD 原文、对应事实与缺口（{report.fact_match.length} 项）</summary>
        {report.fact_match.length === 0 && <p>本地规则暂未识别到具体要求，不能据此认定匹配或不匹配。</p>}
        {report.fact_match.map(x => <article key={`${x.category}-${x.requirement}`}>
          <h4>{x.requirement} <span>· {x.kind} · {x.supported ? "有直接事实" : "待补证据"} · {x.allowed_in_resume ? "可引用" : "暂不写入"}</span></h4>
          <blockquote>{x.jd_evidence}</blockquote><p>{x.gap}</p>
          {x.matched_facts.map(f => <div className="agent-source" key={f.fact_id}><p>{f.project_name} · {f.evidence_status}</p><p>{f.fact}</p><small>{f.write_reason}</small></div>)}
        </article>)}
      </details>
      <section><h3>同类市场补充 · 不是当前岗位硬要求</h3>
        {report.market_comparison.sample_note && <p>{report.market_comparison.sample_note}</p>}
        {report.market_comparison.common_but_not_mentioned?.length
          ? <ul>{report.market_comparison.common_but_not_mentioned.map(x => <li key={`${x.section}-${x.name}`}>{x.name} · 同类 {x.job_count}/{report.market_sample_count} 条提及；当前 JD 未明确写出，有真实经历时再考虑展示。</li>)}</ul>
          : <p>暂无足够稳定的额外共性要求。</p>}
      </section>
      <section><h3>夸大风险</h3><ul>{report.exaggeration_risks.map(x => <li key={x}>{x}</li>)}</ul></section>
      <details><summary>面试官可能追问（{report.interviewer_questions.length} 条）</summary><ul>{report.interviewer_questions.map(x => <li key={x}>{x}</li>)}</ul></details>
      <section><h3>岗位自我介绍预览{!report.self_introduction_ready && " · 事实待确认"}</h3><p>{report.self_introduction_preview}</p></section>
    </div>}
  </section>;
}
