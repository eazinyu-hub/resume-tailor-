import { API_BASE } from "./api";
import { useState } from "react";

type Sample = { id: number; title: string; score: number; family_label: string; reasons: string[] };
type Result = { status: string; target_family_label?: string; available_candidates?: number; score_note?: string; sample_note?: string; items?: Sample[] };

export function SimilarJobSamples({ jobId, onOpenJob }: { jobId: number; onOpenJob: (jobId: number) => void }) {
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function loadSamples() {
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${jobId}/similar-samples`);
      if (!response.ok) throw new Error("request failed");
      setResult(await response.json());
    } catch {
      setError("暂时无法检索相似岗位，请确认后端已启动后重试。");
    } finally { setLoading(false); }
  }
  return <section className="similar-samples">
    <div className="core-match-heading"><p className="card-label">相似岗位参考</p><button className="secondary-button" type="button" onClick={loadSamples} disabled={loading}>{loading ? "检索中…" : "检索相似岗位"}</button></div>
    {error && <p className="market-error">{error}</p>}
    {result?.status === "ready" && <div className="similar-samples-result"><p>当前归入 <strong>{result.target_family_label}</strong> · 从 {result.available_candidates} 条可参考样本中返回最接近的 {result.items?.length || 0} 条。</p><p className="market-note">{result.score_note} {result.sample_note}</p>{result.items?.length ? <ol>{result.items.map((sample) => <li key={sample.id}><button type="button" onClick={() => onOpenJob(sample.id)}><strong>#{sample.id} {sample.title}</strong><span>JD 相似分 {sample.score}</span></button><p>{sample.reasons.join("；")}</p></li>)}</ol> : <p>没有找到足够相近的有效样本；后续导入更多同类 JD 后会更有参考价值。</p>}</div>}
  </section>;
}
