import { API_BASE } from "./api";
import { useEffect, useState } from "react";
import { BatchCollectorPanel } from "./BatchCollectorPanel";
import { CandidateFitDetails, candidateFitScoreLabel } from "./CandidateFitDetails";
import type { CandidateFitAssessment } from "./CandidateFitDetails";

type StagingJob = {
  title: string;
  company: string | null;
  description: string;
  source_id: string;
  source_url: string | null;
  source_job_id: string | null;
  source_updated_at: string | null;
  city: string | null;
  collected_at: string;
  content_hash: string;
  review_status: string;
  collection_status?: "new" | "updated_source";
  previous_content_hash?: string | null;
  collection_notice?: string;
  batch_screening?: { decision: string; reasons: string[] };
  relevance: {
    score: number;
    score_note: string;
    family_label: string;
    market_scope: "overseas" | "china_target";
    sample_usage: "target_market" | "overseas_reference" | "needs_review";
    allow_market_profile: boolean;
    recommendation: string;
    reasons: string[];
    exclusion_reasons: string[];
    similar_samples: { id: number; title: string; score: number; shared_signals: string[] }[];
    reference_count: number;
  };
};

type StagingResponse = {
  status: string;
  count: number;
  items: StagingJob[];
};

type DiscoveryCandidate = {
  source_job_id: string;
  title: string;
  updated_at: string | null;
  score: number;
  family_label: string;
  signals: string[];
  already_staged: boolean;
  candidate_fit: CandidateFitAssessment;
};

type DiscoveryResponse = {
  organization: string;
  open_job_count: number;
  candidate_count: number;
  candidates: DiscoveryCandidate[];
  note: string;
};

type DiscoveryDetail = {
  title: string;
  company: string | null;
  description: string;
  source_url: string | null;
  source_job_id: string;
  published_at: string | null;
  source_updated_at: string | null;
  city: string | null;
  salary: string | null;
};

const API = `${API_BASE}/api/collector/staging`;

export function CollectorStagingPanel() {
  const [items, setItems] = useState<StagingJob[]>([]);
  const [selectedHash, setSelectedHash] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busyHash, setBusyHash] = useState("");
  const [discovery, setDiscovery] = useState<DiscoveryResponse | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [discoveryError, setDiscoveryError] = useState("");
  const [selectedCandidateId, setSelectedCandidateId] = useState("");
  const [candidateDetail, setCandidateDetail] = useState<DiscoveryDetail | null>(null);
  const [candidateDetailLoading, setCandidateDetailLoading] = useState(false);
  const [stagingCandidateId, setStagingCandidateId] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetch(API, { signal: controller.signal })
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "读取失败");
        return result as StagingResponse;
      })
      .then((result) => setItems(result.items || []))
      .catch((requestError) => {
        if (requestError instanceof DOMException && requestError.name === "AbortError") return;
        setError(requestError instanceof Error ? requestError.message : "暂时无法读取采集暂存区。");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  async function resolveItem(item: StagingJob, action: "import" | "discard") {
    if (action === "discard" && !window.confirm(`确定丢弃“${item.title}”吗？记录会保留在本地审核日志中。`)) return;
    setBusyHash(item.content_hash);
    setError("");
    setMessage("");
    try {
      const response = await fetch(`${API}/${item.content_hash}/${action}`, { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || result.detail || "处理失败");
      setItems((current) => current.filter((candidate) => candidate.content_hash !== item.content_hash));
      setSelectedHash("");
      setMessage(action === "import" ? `已将“${item.title}”导入正式岗位库。` : `已丢弃“${item.title}”，审核记录仍保存在本地。`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "处理失败");
    } finally {
      setBusyHash("");
    }
  }

  async function discoverMokaCandidates() {
    setDiscovering(true);
    setDiscoveryError("");
    try {
      const response = await fetch(`${API_BASE}/api/collector/moka/deeproute/discover`, { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "候选发现失败");
      setDiscovery(result as DiscoveryResponse);
    } catch (requestError) {
      setDiscoveryError(requestError instanceof Error ? requestError.message : "候选发现失败");
    } finally {
      setDiscovering(false);
    }
  }

  async function previewMokaCandidate(candidate: DiscoveryCandidate) {
    if (selectedCandidateId === candidate.source_job_id) {
      setSelectedCandidateId("");
      setCandidateDetail(null);
      return;
    }
    setSelectedCandidateId(candidate.source_job_id);
    setCandidateDetail(null);
    setCandidateDetailLoading(true);
    setDiscoveryError("");
    try {
      const response = await fetch(`${API_BASE}/api/collector/moka/deeproute/jobs/${candidate.source_job_id}`);
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "完整 JD 读取失败");
      setCandidateDetail(result.item as DiscoveryDetail);
    } catch (requestError) {
      setDiscoveryError(requestError instanceof Error ? requestError.message : "完整 JD 读取失败");
    } finally {
      setCandidateDetailLoading(false);
    }
  }

  async function stageMokaCandidate(candidate: DiscoveryCandidate) {
    setStagingCandidateId(candidate.source_job_id);
    setDiscoveryError("");
    setMessage("");
    try {
      const response = await fetch(`${API_BASE}/api/collector/moka/deeproute/jobs/${candidate.source_job_id}/stage`, { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "加入待确认区失败");

      const stagingResponse = await fetch(API);
      const stagingResult = await stagingResponse.json();
      if (!stagingResponse.ok) throw new Error(stagingResult.detail || "刷新待确认区失败");
      setItems((stagingResult as StagingResponse).items || []);
      setDiscovery((current) => current ? {
        ...current,
        candidates: current.candidates.map((item) => item.source_job_id === candidate.source_job_id ? { ...item, already_staged: true } : item),
      } : current);
      setMessage(result.status === "already_collected" ? `“${candidate.title}”已经采集过，没有重复写入。` : `已将“${candidate.title}”加入待确认区。`);
    } catch (requestError) {
      setDiscoveryError(requestError instanceof Error ? requestError.message : "加入待确认区失败");
    } finally {
      setStagingCandidateId("");
    }
  }

  async function refreshStaging() {
    try {
      const response = await fetch(API);
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "刷新暂存区失败");
      setItems((result as StagingResponse).items || []);
      setError("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "刷新暂存区失败");
    }
  }

  return <section className="collector-staging-panel">
    <BatchCollectorPanel onCompleted={() => void refreshStaging()} />
    {loading && <p className="market-note">正在读取 D 盘采集暂存区…</p>}
    <div className="collector-summary">
      <div><p className="card-label">等待人工确认</p><h2>暂存岗位</h2></div>
      <div className="collector-summary-actions"><span>{items.length} 条 · 尚未进入岗位库</span><button className="secondary-button" type="button" onClick={() => void refreshStaging()}>刷新暂存区</button></div>
    </div>
    {message && <p className="status-message success" role="status">{message}</p>}
    {error && <p className="market-error" role="alert">{error}</p>}
    <details className="batch-legacy"><summary>旧版单来源试采（保留调试入口）</summary>
    <button className="secondary-button" type="button" disabled={discovering} onClick={discoverMokaCandidates}>{discovering ? "正在读取…" : "发现元戎启行候选"}</button>
    {discoveryError && <p className="market-error" role="alert">{discoveryError}</p>}
    {discovery && <section className="collector-discovery-preview"><div><p className="card-label">先预览，再由你决定是否采集</p><h3>{discovery.organization}</h3><small>公开招聘中 {discovery.open_job_count} 条 · 筛出 {discovery.candidate_count} 条相关候选</small></div>{discovery.candidates.length === 0 ? <p>暂未发现接近当前求职方向的岗位。</p> : <ul>{discovery.candidates.map((candidate) => { const expanded = selectedCandidateId === candidate.source_job_id; return <li key={candidate.source_job_id}><button className="collector-discovery-row" type="button" aria-expanded={expanded} onClick={() => previewMokaCandidate(candidate)}><div><strong>{candidate.title}</strong><span>方向相关度 {candidate.score} 分 · 个人可投性 {candidateFitScoreLabel(candidate.candidate_fit)}</span><small>{candidate.family_label} · {candidate.signals.join("、")}</small></div><div className="collector-candidate-actions"><em className={`candidate-fit-${candidate.candidate_fit.level}`}>{candidate.candidate_fit.label}</em><span className={`collector-candidate-state ${candidate.already_staged ? "staged" : "preview"}`}>{expanded ? "收起完整 JD" : candidate.already_staged ? "已在待确认区 · 查看 JD" : "预览完整 JD"}</span></div></button>{expanded && <div className="collector-candidate-detail">{candidate.candidate_fit.strengths.length > 0 && <div className="candidate-fit-reasons strengths"><strong>与你匹配的地方</strong><ul>{candidate.candidate_fit.strengths.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>}{candidate.candidate_fit.barriers.length > 0 && <div className="candidate-fit-reasons barriers"><strong>当前门槛</strong><ul>{candidate.candidate_fit.barriers.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>}<p>{candidate.candidate_fit.score_note}</p><CandidateFitDetails fit={candidate.candidate_fit} />{candidateDetailLoading && <p>正在读取完整 JD…</p>}{candidateDetail && <><dl><div><dt>公司</dt><dd>{candidateDetail.company || "未记录"}</dd></div><div><dt>地点</dt><dd>{candidateDetail.city || "未记录"}</dd></div><div><dt>更新时间</dt><dd>{candidateDetail.source_updated_at?.replace("T", " ").replace("Z", "") || "未记录"}</dd></div><div><dt>岗位 ID</dt><dd>{candidateDetail.source_job_id}</dd></div></dl>{candidateDetail.source_url && <a href={candidateDetail.source_url} target="_blank" rel="noreferrer">打开公开岗位原链接 ↗</a>}<pre>{candidateDetail.description}</pre><div className="collector-review-actions"><div><button className="primary-button" type="button" disabled={candidate.already_staged || stagingCandidateId === candidate.source_job_id} onClick={() => stageMokaCandidate(candidate)}>{stagingCandidateId === candidate.source_job_id ? "正在加入…" : candidate.already_staged ? "已在待确认区" : "加入待确认区"}</button></div><p>这里只进入人工审核队列，不会直接进入正式岗位库。</p></div></>}</div>}</li>; })}</ul>}<p>{discovery.note}</p></section>}
    </details>
    {items.length === 0 ? <p className="empty-jobs">暂存区是空的。通过筛选的采集岗位会先出现在这里。</p> : <div className="collector-staging-list">
      {items.map((item) => {
        const expanded = selectedHash === item.content_hash;
        return <article className="collector-staging-item" key={item.content_hash}>
          <button className="collector-staging-row" type="button" aria-expanded={expanded} onClick={() => setSelectedHash(expanded ? "" : item.content_hash)}>
            <div><p>{item.company || "公司未记录"} · {item.city || "地点未记录"}</p><h3>{item.title}</h3><small>{item.description.length.toLocaleString()} 字 · {item.source_id}</small><div className="collector-relevance-summary"><strong>{item.relevance.score} 分</strong><span>{item.relevance.family_label}</span><em className={item.relevance.allow_market_profile ? "allowed" : "reference-only"}>{item.relevance.allow_market_profile ? "可进入画像" : "不进入核心画像"}</em></div></div>
            <span>{expanded ? "收起 JD" : "查看 JD"}</span>
          </button>
          {expanded && <div className="collector-staging-detail">
            {item.collection_notice && <p className="collector-update-notice" role="status">{item.collection_notice}</p>}
            {item.batch_screening && <div className="collector-update-notice"><strong>{item.batch_screening.decision === "needs_review" ? "条件待核实，不代表适合投递" : "通过批量规则初筛，仍需人工确认"}</strong><ul>{item.batch_screening.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul></div>}
            <dl><div><dt>审核状态</dt><dd>{item.review_status === "pending" ? "等待确认" : item.review_status}</dd></div><div><dt>来源岗位 ID</dt><dd>{item.source_job_id || "未记录"}</dd></div><div><dt>来源更新时间</dt><dd>{item.source_updated_at?.replace("T", " ").replace("Z", "") || "未记录"}</dd></div><div><dt>采集时间</dt><dd>{item.collected_at.replace("T", " ").slice(0, 19)}</dd></div></dl>
            {item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">打开公开岗位原链接 ↗</a>}
            <section className="collector-relevance-detail"><div><p className="card-label">样本参考价值</p><h4>{item.relevance.recommendation}</h4><small>参考现有 {item.relevance.reference_count} 条有效岗位 · {item.relevance.score_note}</small></div>{item.relevance.reasons.length > 0 && <div><strong>值得参考</strong><ul>{item.relevance.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>}{item.relevance.exclusion_reasons.length > 0 && <div className="collector-exclusions"><strong>限制与排除原因</strong><ul>{item.relevance.exclusion_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>}{item.relevance.similar_samples.length > 0 && <details><summary>查看相近的已有岗位</summary><ul>{item.relevance.similar_samples.map((sample) => <li key={sample.id}>#{sample.id} {sample.title} · {sample.score}%{sample.shared_signals.length ? ` · ${sample.shared_signals.join("、")}` : ""}</li>)}</ul></details>}</section>
            <pre>{item.description}</pre>
            <div className="collector-review-actions"><div><button className="primary-button" type="button" disabled={!item.relevance.allow_market_profile || busyHash === item.content_hash} title={item.relevance.allow_market_profile ? "确认后写入正式岗位库" : "当前相关性判断不允许进入核心画像"} onClick={() => resolveItem(item, "import")}>{busyHash === item.content_hash ? "处理中…" : "确认导入"}</button><button className="secondary-button" type="button" disabled={busyHash === item.content_hash} onClick={() => resolveItem(item, "discard")}>丢弃这条</button></div><p>{item.relevance.allow_market_profile ? "确认导入后，这条岗位才会进入正式岗位库。" : "该岗位未通过核心画像准入，确认导入已禁用。你可以保留待确认或主动丢弃。"}</p></div>
          </div>}
        </article>;
      })}
    </div>}
  </section>;
}
