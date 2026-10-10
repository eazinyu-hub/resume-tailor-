import { API_BASE } from "./api";
import { useState } from "react";

type Item = { section: string; name: string; job_count?: number; percentage?: number };
type Comparison = {
  status: string;
  family_label?: string;
  baseline_count?: number;
  sample_note?: string;
  typical_requirements?: Item[];
  especially_emphasized?: Item[];
  common_but_not_mentioned?: Item[];
  possible_copywriting_noise?: string[];
};

function SignalList({ items, baselineCount }: { items?: Item[]; baselineCount?: number }) {
  if (!items?.length) return <p>暂未形成足够稳定的样本信号。</p>;
  return <ul>{items.map((item) => <li key={`${item.section}-${item.name}`}><strong>{item.name}</strong><span> · {item.section}{item.percentage !== undefined ? ` · ${item.job_count}/${baselineCount} 份` : ""}</span></li>)}</ul>;
}

export function MarketComparison({ jobId }: { jobId: number }) {
  const [result, setResult] = useState<Comparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function compare() {
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${jobId}/market-comparison`);
      if (!response.ok) throw new Error("request failed");
      setResult(await response.json());
    } catch {
      setError("暂时无法完成市场对比，请确认后端已启动后重试。");
    } finally { setLoading(false); }
  }
  return <section className="market-comparison">
    <div className="core-match-heading"><p className="card-label">当前 JD 与市场画像</p><button className="secondary-button" type="button" onClick={compare} disabled={loading}>{loading ? "对比中…" : "与市场画像对比"}</button></div>
    {error && <p className="market-error">{error}</p>}
    {result?.status === "ready" && <div className="market-comparison-result"><p>同类方向：<strong>{result.family_label}</strong> · 对比 {result.baseline_count} 份其他有效样本（排除当前 JD 及相同正文）</p>{result.sample_note && <p className="market-note">{result.sample_note}</p>}<section><h4>当前 JD 与同类市场共同提到</h4><SignalList items={result.typical_requirements} baselineCount={result.baseline_count} /></section><section><h4>本条提到、同类较少出现</h4><SignalList items={result.especially_emphasized} baselineCount={result.baseline_count} /></section><section><h4>当前未写，但同类常见 · 不视为本岗硬要求</h4><SignalList items={result.common_but_not_mentioned} baselineCount={result.baseline_count} /></section><section><h4>可能是招聘文案噪声</h4>{result.possible_copywriting_noise?.length ? <p>{result.possible_copywriting_noise.join("、")}。这是低信息通用表述，不会自动当作简历硬关键词。</p> : <p>未识别到明显的低信息通用表述。</p>}</section></div>}
  </section>;
}
