import { API_BASE } from "./api";
import { useEffect, useState } from "react";

type KeywordFrequency = {
  keyword: string;
  job_count: number;
  percentage: number;
  occurrences: number;
  jobs: { id: number; title: string; occurrences: number; evidence: string }[];
};

type KeywordProfile = {
  total_records: number;
  sample_count: number;
  excluded_duplicates: number;
  excluded_invalid: number;
  items: KeywordFrequency[];
};

export function KeywordFrequencyPanel({ jobsVersion, onOpenJob }: {
  jobsVersion: string;
  onOpenJob: (jobId: number) => void;
}) {
  const [profile, setProfile] = useState<KeywordProfile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [isExpanded, setIsExpanded] = useState(true);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setError("");
    setProfile(null);
    fetch(`${API_BASE}/api/market/keyword-frequency`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("统计读取失败");
        return response.json() as Promise<KeywordProfile>;
      })
      .then((result) => { if (!controller.signal.aborted) setProfile(result); })
      .catch(() => {
        if (!controller.signal.aborted) setError("暂时无法读取统计，请确认后端已启动后重试。");
      })
      .finally(() => { if (!controller.signal.aborted) setIsLoading(false); });
    return () => controller.abort();
  }, [jobsVersion, refresh]);

  return (
    <section className="market-panel" aria-labelledby="market-title">
      <div className="market-heading">
        <div>
          <p className="card-label">岗位样本画像 · 全部方向</p>
          <h2 id="market-title">关键词频率</h2>
        </div>
        <div className="market-actions">
          <button className="secondary-button" type="button" disabled={isLoading} onClick={() => setRefresh((value) => value + 1)}>刷新统计</button>
          <button className="secondary-button" type="button" aria-expanded={isExpanded} aria-controls="keyword-frequency-content" onClick={() => setIsExpanded((value) => !value)}>{isExpanded ? "收起统计" : "展开统计"}</button>
        </div>
      </div>
      <div id="keyword-frequency-content" hidden={!isExpanded}>
        {isLoading && <p className="market-note" role="status">正在统计已保存的 JD…</p>}
        {error && <p className="market-error" role="alert">{error}</p>}
        {profile && <>
          <p className="market-note">共 {profile.total_records} 条记录 · 纳入 {profile.sample_count} 份 JD · 排除重复 {profile.excluded_duplicates} 条、无效 {profile.excluded_invalid} 条</p>
          {profile.sample_count === 0 ? <p className="empty-jobs">暂无可统计的 JD，请先导入有效岗位样本。</p> : <>
            <div className="market-table-scroll">
              <table className="market-table">
                <caption>按提及 JD 数排序；点击关键词下的“查看岗位”可追溯正文。</caption>
                <thead><tr><th scope="col">关键词</th><th scope="col">提及 JD 数</th><th scope="col">样本占比</th><th scope="col">原文次数</th></tr></thead>
                <tbody>{profile.items.map((item) => <tr key={item.keyword}>
                  <th scope="row">
                    <span>{item.keyword}</span>
                    {item.jobs.length > 0 && <details className="market-evidence">
                      <summary>查看岗位（{item.job_count}）</summary>
                      <ul>{item.jobs.map((job) => <li key={job.id}>
                        <a href={`#job-${job.id}`} onClick={() => onOpenJob(job.id)}>#{job.id} {job.title}</a>
                        <small>本份 JD 出现 {job.occurrences} 次</small>
                        <p>{job.evidence}</p>
                      </li>)}</ul>
                    </details>}
                  </th>
                  <td>{item.job_count} 份</td><td>{item.percentage}%</td><td>{item.occurrences} 次</td>
                </tr>)}</tbody>
              </table>
            </div>
            <p className="market-note">同一份 JD 重复提及，JD 数只计 1 份；原文次数累计计算。占比以纳入的 {profile.sample_count} 份 JD 为分母。</p>
          </>}
          <details className="market-method">
            <summary>统计口径</summary>
            <p>仅统计 JD 正文，不统计岗位标题；英文不区分大小写。Agent 包含 Agent、Agents 和“智能体”；其余按关键词匹配。</p>
            <p>排除已标记重复、无效或空正文记录；忽略空格、换行、大小写和全半角后相同的正文只计一份。未确认的近似重复仍保留。</p>
            <p>“提及”包括职责、要求、加分项、举例与否定表述，不等于硬性要求。这是当前样本库的分布，不代表整个招聘市场。</p>
          </details>
        </>}
      </div>
    </section>
  );
}
