import { API_BASE } from "./api";
import { StrictMode, useEffect, useState, type ChangeEvent } from "react";
import { createRoot } from "react-dom/client";
import { KeywordFrequencyPanel } from "./KeywordFrequencyPanel";
import { RoleProfilePanel } from "./RoleProfilePanel";
import { MarketComparison } from "./MarketComparison";
import { ProjectFactPanel } from "./ProjectFactPanel";
import { SimilarJobSamples } from "./SimilarJobSamples";
import { AgentV1Panel } from "./AgentV1Panel";
import { CollectorStagingPanel } from "./CollectorStagingPanel";
import "./styles.css";

type JobSummary = {
  id: number;
  title: string;
  description_length: number;
  source: string;
  created_at: string;
  duplicate_count: number;
  role_family?: string | null;
  suggested_family?: string;
  classification_status?: string | null;
};

type JobDetail = JobSummary & {
  description: string;
  classification_suggestion?: { family: string; label: string; reasons: string[] };
  sample_card?: {
    raw: {
      company_raw: string | null;
      source: string | null;
      source_url: string | null;
      published_at: string | null;
      collected_at: string;
      city_raw: string | null;
      salary_raw: string | null;
      duplicate_of: number | null;
      sample_status: "active" | "duplicate" | "invalid";
    };
    analysis: unknown | null;
  };
};

const ROLE_FAMILY_OPTIONS = [
  ["ai_tool_automation", "AI 工具与自动化"],
  ["vibe_coding_fullstack", "Vibe Coding 全栈"],
  ["agent_application", "Agent 应用开发"],
  ["ai_product_operations", "AI 产品运营"],
  ["internal_intelligence", "内部智能化系统"],
  ["indie_ai_developer", "独立开发/一人公司"],
] as const;

function ClassificationSuggestion({ suggestion, onConfirm }: { suggestion: NonNullable<JobDetail["classification_suggestion"]>; onConfirm: (family: string) => void }) {
  const [selected, setSelected] = useState(suggestion.family === "unclassified" ? "" : suggestion.family);
  return <section className="classification-suggestion"><p className="card-label">岗位方向建议</p><p>系统建议：<strong>{suggestion.label}</strong></p><small>依据：{suggestion.reasons.join("、")}</small><div>{ROLE_FAMILY_OPTIONS.map(([family, label]) => <button className={selected === family ? "active" : ""} type="button" key={family} onClick={() => setSelected(family)}>{label}</button>)}</div><button className="primary-button" type="button" onClick={() => onConfirm(selected)} disabled={!selected}>确认这个分类</button></section>;
}

type JobKeywordResult = {
  keywords: string[];
  categories: Record<string, string[]>;
};

type JobHighlightsResult = {
  sections: Record<string, string[]>;
};

type BatchPreviewItem = {
  position: number;
  title: string;
  description_length: number;
};

type BatchPreviewResult = {
  status: string;
  count: number;
  items: BatchPreviewItem[];
  duplicates?: DuplicateCandidate[];
};

type DuplicateCandidate = {
  position: number;
  category: "exact" | "same_body" | "same_company" | "near";
  similarity: number;
  existing_id: number;
  existing_title: string;
};

type BatchSaveResult = {
  status: string;
  received: number;
  saved: number;
  duplicates: number;
};

const JOB_GROUPS = [
  ...ROLE_FAMILY_OPTIONS.map(([id, label]) => ({ id, label })),
  { id: "unclassified", label: "待确认方向" },
];

function getJobGroupId(job: JobSummary): string {
  return job.classification_status === "confirmed" && job.role_family
    ? job.role_family : job.suggested_family || "unclassified";
}

function decodeTxtFile(buffer: ArrayBuffer): string {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(buffer);
  } catch {
    return new TextDecoder("gb18030").decode(buffer);
  }
}

function parseCsvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let value = "";
  let quoted = false;
  const addRow = () => {
    row.push(value.trim());
    if (row.some(Boolean)) rows.push(row);
    row = [];
    value = "";
  };
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        value += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        value += character;
      }
    } else if (character === '"') {
      quoted = true;
    } else if (character === ",") {
      row.push(value.trim());
      value = "";
    } else if (character === "\r" || character === "\n") {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      addRow();
    } else {
      value += character;
    }
  }
  if (value || row.length > 0) addRow();
  return rows;
}

function parseCsvHeader(text: string): string[] {
  return (parseCsvRows(text.replace(/^\uFEFF/, ""))[0] || []).filter(Boolean);
}

type CsvFieldKey = "jobTitle" | "company" | "jobDescription" | "source" | "sourceUrl";

type CsvRowPreview = {
  position: number;
  title: string;
  company: string;
  descriptionLength: number;
  issues: string[];
};

type CsvImportJob = {
  title: string;
  description: string;
  company: string;
  source: string;
  source_url: string;
};

const CSV_FIELD_LABELS: Record<CsvFieldKey, string> = {
  jobTitle: "岗位名称",
  company: "公司",
  jobDescription: "JD",
  source: "来源",
  sourceUrl: "链接",
};

const CSV_HEADER_ALIASES: Record<CsvFieldKey, string[]> = {
  jobDescription: ["jd", "岗位描述", "职位描述", "jobdescription", "description"],
  jobTitle: ["岗位名称", "职位名称", "职位", "岗位", "jobtitle", "position", "title"],
  company: ["公司", "公司名称", "企业", "企业名称", "company", "organization"],
  source: ["来源", "来源平台", "平台", "source", "platform"],
  sourceUrl: ["链接", "原始链接", "职位链接", "网址", "url", "link", "joburl"],
};

const CSV_MAPPING_FIELDS: CsvFieldKey[] = ["jobDescription", "jobTitle", "company", "source", "sourceUrl"];

const DUPLICATE_LABELS: Record<DuplicateCandidate["category"], string> = {
  exact: "完全重复",
  same_body: "正文相同、标题不同",
  same_company: "同公司重复发布",
  near: "近似重复",
};

function duplicateHint(candidate: DuplicateCandidate): string {
  return `${DUPLICATE_LABELS[candidate.category]} · 与「${candidate.existing_title}」相似度 ${candidate.similarity}%`;
}

function normalizeCsvHeader(header: string): string {
  return header.toLowerCase().replace(/[\s_－—-]/g, "");
}

function mapCsvHeaders(headers: string[]): Record<CsvFieldKey, string | null> {
  const matchedHeaders = new Set<string>();
  return CSV_MAPPING_FIELDS.reduce<Record<CsvFieldKey, string | null>>((mapping, field) => {
    const header = headers.find((candidate) => {
      if (matchedHeaders.has(candidate)) return false;
      const normalized = normalizeCsvHeader(candidate);
      return CSV_HEADER_ALIASES[field].some((alias) => normalized === alias || normalized.includes(alias));
    });
    mapping[field] = header || null;
    if (header) matchedHeaders.add(header);
    return mapping;
  }, { jobTitle: null, company: null, jobDescription: null, source: null, sourceUrl: null });
}

function buildCsvImportJobs(rows: string[][], headers: string[], mapping: Record<CsvFieldKey, string | null>): CsvImportJob[] {
  const indexFor = (field: CsvFieldKey) => mapping[field] ? headers.indexOf(mapping[field]) : -1;
  const titleIndex = indexFor("jobTitle");
  const companyIndex = indexFor("company");
  const descriptionIndex = indexFor("jobDescription");
  const sourceIndex = indexFor("source");
  const sourceUrlIndex = indexFor("sourceUrl");
  return rows.map((row) => ({
    title: titleIndex >= 0 ? row[titleIndex] || "" : "",
    description: descriptionIndex >= 0 ? row[descriptionIndex] || "" : "",
    company: companyIndex >= 0 ? row[companyIndex] || "" : "",
    source: sourceIndex >= 0 ? row[sourceIndex] || "" : "",
    source_url: sourceUrlIndex >= 0 ? row[sourceUrlIndex] || "" : "",
  }));
}

function buildCsvRowPreviews(jobs: CsvImportJob[]): CsvRowPreview[] {
  return jobs.map((job, index) => {
    const issues = [!job.title && "缺少岗位名称", !job.description && "缺少 JD"].filter(Boolean) as string[];
    return { position: index + 1, title: job.title || `未命名岗位 #${index + 1}`, company: job.company, descriptionLength: job.description.length, issues };
  });
}

type KeywordMatchResult = {
  status: string;
  matched: string[];
  missing: string[];
  coverage: number | null;
  note?: string;
};

type CoreMatchItem = {
  requirement: string;
  matched: boolean;
  projects: string[];
  evidence: string[];
};

type RecommendationItem = {
  type: string;
  title: string;
  content: string;
  reason: string;
};

type ResumePreviewResult = {
  status: string;
  filename: string;
  sections: Record<string, string[]>;
};

type TailoredDraft = {
  jobTitle: string;
  sections: Record<string, string[]>;
  changes: string[];
  source?: string;
};

function buildRecommendations(keywordResult: KeywordMatchResult, coreItems: CoreMatchItem[]): RecommendationItem[] {
  const items: RecommendationItem[] = [];
  const matchedCore = coreItems.filter((item) => item.matched);
  const missingCore = coreItems.filter((item) => !item.matched);
  const projectNames = [...new Set(matchedCore.flatMap((item) => item.projects))];

  if (matchedCore.length > 0) {
    items.push({
      type: "突出",
      title: "把已有匹配项目提前",
      content: projectNames.length > 0 ? `优先展示与核心要求相关的项目：${projectNames.join("、")}。` : "优先展示已经出现核心要求证据的项目。",
      reason: "这些经历已经能证明岗位关注的能力，放在前面更容易被快速看见。",
    });
  }
  if (missingCore.length > 0) {
    items.push({
      type: "补充",
      title: "核实未匹配的核心要求",
      content: `请确认是否有真实经历可以补充：${missingCore.map((item) => item.requirement).join("、")}。`,
      reason: "当前简历没有找到直接证据，只建议补充真实经历，不建议直接写成已掌握。",
    });
  }
  if (keywordResult.missing.length > 0) {
    items.push({
      type: "补充",
      title: "自然补充岗位关键词",
      content: `如果项目确实涉及，可在项目描述或技术栈中补充：${keywordResult.missing.slice(0, 8).join("、")}。`,
      reason: "这些词出现在 JD 中，但当前简历未覆盖，补充真实上下文有助于提高检索命中。",
    });
  }
  items.push({
    type: "谨慎",
    title: "保留可验证的项目细节",
    content: "为每个重点项目补充真实的输入、输出、调试或验证过程；暂不填写没有依据的指标。",
    reason: "Vibe Coding 岗位通常会追问开发闭环，具体过程比泛泛而谈更可信。",
  });
  return items;
}

function TailoredDraftPanel({ jobId, draft, isDrafting, generateError, onGenerate }: { jobId: number; draft: TailoredDraft | null; isDrafting: boolean; generateError: string; onGenerate: () => void }) {
  const [editedDraft, setEditedDraft] = useState<TailoredDraft | null>(draft);
  const [isSaving, setIsSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState("");
  const [isExpanded, setIsExpanded] = useState(Boolean(draft));

  useEffect(() => {
    setEditedDraft(draft);
    setSaveStatus("");
    setIsExpanded(Boolean(draft));
  }, [draft, jobId]);

  function handleParagraphChange(section: string, index: number, value: string) {
    setEditedDraft((current) => current ? {
      ...current,
      sections: {
        ...current.sections,
        [section]: current.sections[section].map((paragraph, paragraphIndex) => paragraphIndex === index ? value : paragraph),
      },
    } : current);
    setSaveStatus("有未保存的修改");
  }

  async function handleSave() {
    if (!editedDraft) return;
    setIsSaving(true);
    setSaveStatus("正在保存……");
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${jobId}/draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_title: editedDraft.jobTitle, sections: editedDraft.sections, changes: editedDraft.changes, source: editedDraft.source || "agent-v1-confirmed-facts" }),
      });
      const result = await response.json();
      if (!response.ok || result.status !== "saved") throw new Error("save failed");
      setEditedDraft(result.draft);
      setSaveStatus("修改已保存");
    } catch {
      setSaveStatus("保存失败，请确认后端已启动");
    } finally {
      setIsSaving(false);
    }
  }

  return <section className="tailored-draft"><div className="section-heading"><div><p className="card-label">该岗位的事实约束简历草稿</p><span>仅使用原始简历与已确认事实 · 与当前岗位单独绑定</span></div><div className="draft-actions">{editedDraft && <button className="secondary-button" type="button" onClick={() => setIsExpanded((expanded) => !expanded)}>{isExpanded ? "收起草稿" : "展开草稿"}</button>}{editedDraft && <button className="secondary-button" type="button" onClick={handleSave} disabled={isSaving}>{isSaving ? "保存中…" : "保存修改"}</button>}{editedDraft && <a className="secondary-button draft-export" href={`${API_BASE}/api/jobs/${jobId}/draft.docx`}>导出 Word</a>}{editedDraft && <a className="secondary-button draft-export" href={`${API_BASE}/api/jobs/${jobId}/draft.pdf`}>导出 PDF</a>}<button className="primary-button" type="button" onClick={onGenerate} disabled={isDrafting}>{isDrafting ? "生成中…" : editedDraft ? "用本地规则重新生成" : "用本地规则生成草稿"}</button></div></div>{generateError && <p className="status-message error" role="alert">{generateError}</p>}{saveStatus && <p className="draft-save-status" role="status">{saveStatus}</p>}{editedDraft && isExpanded && <><div className="draft-changes"><p className="card-label">本次调整</p>{editedDraft.changes.map((change) => <p key={change}>{change}</p>)}</div><article className="draft-preview"><p className="card-label">草稿编辑 · {editedDraft.jobTitle}</p>{Object.entries(editedDraft.sections).map(([section, paragraphs]) => paragraphs.length > 0 && <div className="resume-section" key={section}><h3>{section}</h3>{paragraphs.map((paragraph, index) => <textarea className="draft-paragraph" key={`${section}-${index}`} value={paragraph} rows={Math.max(1, Math.ceil(paragraph.length / 48))} onChange={(event) => handleParagraphChange(section, index, event.target.value)} />)}</div>)}</article></>}</section>;
}

type JobDetailPanelProps = {
  job: JobDetail;
  isLoading: boolean;
  analysisMessage: string;
  jobKeywords: string[];
  jobKeywordCategories: Record<string, string[]>;
  jobHighlights: Record<string, string[]>;
  keywordMatch: KeywordMatchResult | null;
  isMatching: boolean;
  onMatch: () => void;
  coreMatch: CoreMatchItem[];
  isCoreMatching: boolean;
  onCoreMatch: () => void;
  recommendations: RecommendationItem[];
  isRecommending: boolean;
  onRecommend: () => void;
  onClose: () => void;
  onOpenJob: (jobId: number) => void;
  onAnalyze: () => void;
  isAnalyzing: boolean;
};

function JobDetailPanel({ job, isLoading, analysisMessage, jobKeywords, jobKeywordCategories, jobHighlights, keywordMatch, isMatching, onClose, onOpenJob, onAnalyze, onMatch, coreMatch, isCoreMatching, onCoreMatch, recommendations, isRecommending, onRecommend, isAnalyzing }: JobDetailPanelProps) {
  const sample = job.sample_card?.raw;
  const sourceLabel = sample?.source === "manual" ? "手动导入" : sample?.source || "未录入";
  const statusLabels = { active: "正常样本", duplicate: "重复样本", invalid: "无效样本" };

  return (
    <>
      {isLoading && <p className="detail-loading">正在打开原始 JD……</p>}
      <article className="job-detail"><div className="detail-heading"><div><p className="card-label">原始岗位 JD</p><h3>{job.title}</h3></div><button type="button" onClick={onClose}>收起</button></div><p className="detail-meta">#{job.id} · {job.description.length} 字</p>{sample && <dl className="sample-meta"><div><dt>来源</dt><dd>{sourceLabel}</dd></div><div><dt>公司</dt><dd>{sample.company_raw || "未录入"}</dd></div><div><dt>地区</dt><dd>{sample.city_raw || "未录入"}</dd></div><div><dt>薪资</dt><dd>{sample.salary_raw || "未录入"}</dd></div><div><dt>采集时间</dt><dd>{sample.collected_at?.replace("T", " ").slice(0, 16) || "未记录"}</dd></div><div><dt>样本状态</dt><dd className={`sample-status ${sample.sample_status}`}>{statusLabels[sample.sample_status]}</dd></div></dl>}{sample?.duplicate_of && <p className="duplicate-reference">系统判断这是一条完全重复的 JD。<button type="button" onClick={() => onOpenJob(sample.duplicate_of!)}>查看原始样本 #{sample.duplicate_of}</button></p>}<pre>{job.description}</pre><div className="analysis-entry"><button className="primary-button" type="button" onClick={onAnalyze} disabled={isAnalyzing}>{isAnalyzing ? "提取中…" : "开始分析 JD"}</button>{analysisMessage && <p role="status">{analysisMessage}</p>}</div><SimilarJobSamples jobId={job.id} onOpenJob={onOpenJob} /><MarketComparison jobId={job.id} />{jobKeywords.length > 0 && <div className="keyword-result"><p className="card-label">识别到的关键词</p><div className="keyword-category-list">{Object.entries(jobKeywordCategories).map(([category, keywords]) => keywords.length > 0 && <div className="keyword-category" key={category}><span>{category}</span><div className="keyword-list">{keywords.map((keyword) => <span key={keyword}>{keyword}</span>)}</div></div>)}</div></div>}<div className="highlight-result"><p className="card-label">JD 重点识别</p><div className="highlight-list">{Object.entries(jobHighlights).map(([section, items]) => <div className="highlight-section" key={section}><span>{section}</span><p>{items.length > 0 ? items.join("、") : "暂未识别"}</p></div>)}</div></div><div className="match-entry"><button className="secondary-button" type="button" onClick={onMatch} disabled={isMatching}>{isMatching ? "匹配中…" : "计算关键词覆盖率"}</button>{keywordMatch?.status === "no_resume" && <p role="status">请先导入简历。</p>}{keywordMatch?.status === "ready" && <div className="match-result"><strong>{keywordMatch.coverage === null ? "暂无可计分关键词" : `${keywordMatch.coverage}%`}</strong><span>简历文字覆盖率</span><p>{keywordMatch.note}</p><p>已覆盖：{keywordMatch.matched.join("、") || "暂无"}</p><p>未覆盖：{keywordMatch.missing.join("、") || "暂无"}</p></div>}</div><div className="core-match"><div className="core-match-heading"><p className="card-label">核心要求匹配</p><button className="secondary-button" type="button" onClick={onCoreMatch} disabled={isCoreMatching}>{isCoreMatching ? "匹配中…" : "匹配核心要求"}</button></div>{coreMatch.length > 0 && <div className="core-match-list">{coreMatch.map((item) => <div className={item.matched ? "core-match-item matched" : "core-match-item missing"} key={item.requirement}><strong>{item.matched ? "已匹配" : "未找到"}</strong><span>{item.requirement}</span>{item.projects.length > 0 && <p>对应项目：{item.projects.join("、")}</p>}{item.evidence.map((evidence) => <p key={evidence}>{evidence}</p>)}</div>)}</div>}</div><div className="recommendation-result"><div className="core-match-heading"><p className="card-label">简历调整建议</p><button className="secondary-button" type="button" onClick={onRecommend} disabled={isRecommending}>{isRecommending ? "生成中…" : "生成建议"}</button></div>{recommendations.length > 0 && <div className="recommendation-list">{recommendations.map((item) => <div className="recommendation-item" key={item.title}><strong className={`recommendation-type ${item.type}`}>{item.type}</strong><div><h4>{item.title}</h4><p>{item.content}</p><small>原因：{item.reason}</small></div></div>)}</div>}</div></article>
    </>
  );
}

function App() {
  const [isInputting, setIsInputting] = useState(false);
  const [isViewingMarketProfile, setIsViewingMarketProfile] = useState(false);
  const [isViewingProjectFacts, setIsViewingProjectFacts] = useState(false);
  const [isViewingCollectorStaging, setIsViewingCollectorStaging] = useState(false);
  const [jobTitle, setJobTitle] = useState("");
  const [jobDescription, setJobDescription] = useState("");
  const [inputMode, setInputMode] = useState<"single" | "batch">("single");
  const [batchText, setBatchText] = useState("");
  const [batchFileName, setBatchFileName] = useState("");
  const [csvFileName, setCsvFileName] = useState("");
  const [csvHeaders, setCsvHeaders] = useState<string[]>([]);
  const [csvMapping, setCsvMapping] = useState<Record<CsvFieldKey, string | null> | null>(null);
  const [csvRowPreviews, setCsvRowPreviews] = useState<CsvRowPreview[]>([]);
  const [csvJobs, setCsvJobs] = useState<CsvImportJob[]>([]);
  const [csvDuplicates, setCsvDuplicates] = useState<DuplicateCandidate[]>([]);
  const [csvIncludedPositions, setCsvIncludedPositions] = useState<Set<number>>(new Set());
  const [batchIncludedPositions, setBatchIncludedPositions] = useState<Set<number>>(new Set());
  const [csvSaveResult, setCsvSaveResult] = useState<BatchSaveResult | null>(null);
  const [isCsvSaving, setIsCsvSaving] = useState(false);
  const [batchPreview, setBatchPreview] = useState<BatchPreviewResult | null>(null);
  const [batchSaveResult, setBatchSaveResult] = useState<BatchSaveResult | null>(null);
  const [batchError, setBatchError] = useState("");
  const [isBatchPreviewing, setIsBatchPreviewing] = useState(false);
  const [isBatchSaving, setIsBatchSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [selectedJob, setSelectedJob] = useState<JobDetail | null>(null);
  const [isLoadingJob, setIsLoadingJob] = useState(false);
  const [analysisMessage, setAnalysisMessage] = useState("");
  const [jobKeywords, setJobKeywords] = useState<string[]>([]);
  const [jobKeywordCategories, setJobKeywordCategories] = useState<Record<string, string[]>>({});
  const [jobHighlights, setJobHighlights] = useState<Record<string, string[]>>({});
  const [keywordMatch, setKeywordMatch] = useState<KeywordMatchResult | null>(null);
  const [isMatching, setIsMatching] = useState(false);
  const [coreMatch, setCoreMatch] = useState<CoreMatchItem[]>([]);
  const [isCoreMatching, setIsCoreMatching] = useState(false);
  const [recommendations, setRecommendations] = useState<RecommendationItem[]>([]);
  const [isRecommending, setIsRecommending] = useState(false);
  const [tailoredDraft, setTailoredDraft] = useState<TailoredDraft | null>(null);
  const [isDrafting, setIsDrafting] = useState(false);
  const [draftError, setDraftError] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [resumeStatus, setResumeStatus] = useState("");
  const [resumePreview, setResumePreview] = useState<string[]>([]);
  const [resumeSections, setResumeSections] = useState<Record<string, string[]>>({});
  const [resumeFileName, setResumeFileName] = useState("");
  const [isResumeExpanded, setIsResumeExpanded] = useState(false);
  const [isPreviewingResume, setIsPreviewingResume] = useState(false);

  async function handleOpenJob(jobId: number) {
    setIsLoadingJob(true);
    setKeywordMatch(null);
    setCoreMatch([]);
    setRecommendations([]);
    setTailoredDraft(null);
    setDraftError("");
    try {
      const [jobResponse, draftResponse] = await Promise.all([
        fetch(`${API_BASE}/api/jobs/${jobId}`),
        fetch(`${API_BASE}/api/jobs/${jobId}/draft`),
      ]);
      if (!jobResponse.ok) throw new Error("request failed");
      setSelectedJob(await jobResponse.json());
      if (draftResponse.ok) {
        const draftResult = await draftResponse.json();
        setTailoredDraft(draftResult.status === "ready" ? draftResult.draft : null);
      }
    } catch {
      setSelectedJob(null);
    } finally {
      setIsLoadingJob(false);
    }
  }

  function handleOpenJobFromMarket(jobId: number) {
    setIsViewingMarketProfile(false);
    handleOpenJob(jobId);
    window.setTimeout(() => document.getElementById(`job-${jobId}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 100);
  }

  async function handleConfirmClassification(roleFamily: string) {
    if (!selectedJob) return;
    const response = await fetch(`${API_BASE}/api/jobs/${selectedJob.id}/classification`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role_family: roleFamily }) });
    if (!response.ok) return;
    const jobsResponse = await fetch(`${API_BASE}/api/jobs`);
    if (jobsResponse.ok) setJobs((await jobsResponse.json()).items);
  }

  function handleStartAnalysis() {
    if (!selectedJob) return;
    setIsAnalyzing(true);
    setAnalysisMessage("");
    fetch(`${API_BASE}/api/jobs/${selectedJob.id}/keywords`)
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("request failed"))))
      .then((result: JobKeywordResult) => {
        setJobKeywords(result.keywords);
        setJobKeywordCategories(result.categories);
        setAnalysisMessage(`已识别 ${result.keywords.length} 个关键词`);
      })
      .catch(() => setAnalysisMessage("暂时无法完成关键词提取，请确认后端已启动。"))
      .finally(() => setIsAnalyzing(false));
    fetch(`${API_BASE}/api/jobs/${selectedJob.id}/highlights`)
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("request failed"))))
      .then((result: JobHighlightsResult) => setJobHighlights(result.sections))
      .catch(() => setJobHighlights({}));
  }

  async function handleKeywordMatch() {
    if (!selectedJob) return;
    setIsMatching(true);
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${selectedJob.id}/keyword-match`);
      if (!response.ok) throw new Error("request failed");
      setKeywordMatch(await response.json());
    } catch {
      setKeywordMatch({ status: "error", matched: [], missing: [], coverage: 0 });
    } finally {
      setIsMatching(false);
    }
  }

  async function handleCoreMatch() {
    if (!selectedJob) return;
    setIsCoreMatching(true);
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${selectedJob.id}/core-match`);
      if (!response.ok) throw new Error("request failed");
      const result = await response.json();
      setCoreMatch(result.items || []);
    } catch {
      setCoreMatch([]);
    } finally {
      setIsCoreMatching(false);
    }
  }

  async function handleRecommend() {
    if (!selectedJob) return;
    setIsRecommending(true);
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${selectedJob.id}/recommendations`);
      if (response.ok) {
        const result = await response.json();
        setRecommendations(result.items || []);
        return;
      }
      const [keywordResponse, coreResponse] = await Promise.all([
        fetch(`${API_BASE}/api/jobs/${selectedJob.id}/keyword-match`),
        fetch(`${API_BASE}/api/jobs/${selectedJob.id}/core-match`),
      ]);
      if (!keywordResponse.ok || !coreResponse.ok) throw new Error("request failed");
      const keywordResult: KeywordMatchResult = await keywordResponse.json();
      const coreResult = await coreResponse.json();
      const coreItems: CoreMatchItem[] = coreResult.items || [];
      setKeywordMatch(keywordResult);
      setCoreMatch(coreItems);
      setRecommendations(buildRecommendations(keywordResult, coreItems));
    } catch {
      setRecommendations([]);
    } finally {
      setIsRecommending(false);
    }
  }

  async function handleGenerateTailoredDraft() {
    if (!selectedJob) return;
    setIsDrafting(true);
    setDraftError("");
    try {
      const agentResponse = await fetch(`${API_BASE}/api/jobs/${selectedJob.id}/agent-v1`);
      if (!agentResponse.ok) throw new Error("暂时无法连接后端。");
      const agentResult = await agentResponse.json();
      if (agentResult.formal_resume?.blocked || !agentResult.formal_resume?.draft) throw new Error(agentResult.formal_resume?.message || "尚未满足生成条件。");
      const draft: TailoredDraft = agentResult.formal_resume.draft;
      const saveResponse = await fetch(`${API_BASE}/api/jobs/${selectedJob.id}/draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_title: draft.jobTitle, sections: draft.sections, changes: draft.changes, source: draft.source || "agent-v1-confirmed-facts" }),
      });
      if (!saveResponse.ok) throw new Error("save failed");
      const saveResult = await saveResponse.json();
      if (saveResult.status !== "saved") throw new Error("save failed");
      setTailoredDraft(saveResult.draft);
    } catch (requestError) {
      setTailoredDraft(null);
      setDraftError(requestError instanceof Error ? requestError.message : "生成失败，请稍后重试。");
    } finally {
      setIsDrafting(false);
    }
  }

  async function handleResumeUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setResumeStatus("正在保存简历……");
    try {
      const response = await fetch(`${API_BASE}/api/resumes`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream", "X-Filename": file.name },
        body: file,
      });
      const result = await response.json();
      if (!response.ok || result.status !== "saved") throw new Error(result.message);
      setResumeFileName(result.filename);
      setResumePreview([]);
      setResumeSections({});
      setIsResumeExpanded(false);
      setResumeStatus(`已保存：${result.filename}`);
    } catch (error) {
      setResumeStatus(error instanceof Error ? error.message : "简历保存失败，请确认后端已启动。");
    } finally {
      event.target.value = "";
    }
  }

  async function handlePreviewResume() {
    if (resumePreview.length > 0) {
      setIsResumeExpanded((expanded) => !expanded);
      return;
    }
    setIsPreviewingResume(true);
    try {
      const response = await fetch(`${API_BASE}/api/resumes/preview`);
      if (!response.ok) throw new Error("request failed");
      const result = await response.json();
      setResumeFileName(result.filename || "");
      setResumePreview(result.paragraphs || []);
      setResumeSections(result.sections || {});
      setIsResumeExpanded(true);
    } catch {
      setResumeStatus("暂时无法读取简历内容，请确认后端已启动。");
    } finally {
      setIsPreviewingResume(false);
    }
  }

  useEffect(() => {
    fetch(`${API_BASE}/api/jobs`)
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("request failed"))))
      .then((result) => setJobs(result.items))
      .catch(() => setJobs([]));

    fetch(`${API_BASE}/api/resumes/preview`)
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("request failed"))))
      .then((result) => {
        if (result.status === "ready") setResumeFileName(result.filename);
      })
      .catch(() => setResumeFileName(""));
  }, []);

  async function handlePreview() {
    setIsSubmitting(true);
    setStatusMessage("正在送往工作台……");
    try {
      const response = await fetch(`${API_BASE}/api/jobs/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: jobTitle, description: jobDescription }),
      });
      if (!response.ok) throw new Error("request failed");
      const result = await response.json();
      if (result.status === "exists") {
        setStatusMessage(`这份岗位已经保存过了 · ID #${result.id}`);
      } else {
        setStatusMessage(`已保存：${result.title} · ${result.description_length} 字`);
        setJobs((currentJobs) => [result, ...currentJobs]);
      }
    } catch {
      setStatusMessage("暂时无法连接工作台，请确认后端已启动。");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function previewBatchText(text: string) {
    setIsBatchPreviewing(true);
    setBatchPreview(null);
    setBatchSaveResult(null);
    setBatchError("");
    try {
      const response = await fetch(`${API_BASE}/api/jobs/batch-preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || "批量格式无法识别");
      setBatchPreview(result);
      setBatchIncludedPositions(new Set(result.items.map((item: BatchPreviewItem) => item.position).filter((position: number) => result.duplicates?.find((candidate: DuplicateCandidate) => candidate.position === position)?.category !== "exact")));
    } catch (error) {
      setBatchError(error instanceof Error ? error.message : "暂时无法完成批量预览，请确认后端已启动。");
    } finally {
      setIsBatchPreviewing(false);
    }
  }

  async function handleBatchPreview() {
    await previewBatchText(batchText);
  }

  async function handleBatchTxtChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBatchError("");
    setBatchPreview(null);
    setBatchSaveResult(null);
    if (!file.name.toLowerCase().endsWith(".txt")) {
      setBatchFileName("");
      setBatchError("请选择 .txt 文本文件。");
      return;
    }
    try {
      const text = decodeTxtFile(await file.arrayBuffer());
      setBatchText(text);
      setBatchFileName(file.name);
      await previewBatchText(text);
    } catch {
      setBatchFileName("");
      setBatchError("无法读取这个 TXT 文件，请检查文件编码。");
    }
  }

  async function handleBatchCsvChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBatchError("");
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setCsvFileName("");
      setCsvHeaders([]);
      setCsvMapping(null);
      setCsvRowPreviews([]);
      setCsvJobs([]);
      setCsvDuplicates([]);
      setCsvSaveResult(null);
      setBatchError("请选择 .csv 文件。");
      return;
    }
    try {
      const content = decodeTxtFile(await file.arrayBuffer());
      const headers = parseCsvHeader(content);
      if (headers.length === 0) throw new Error("empty");
      const mapping = mapCsvHeaders(headers);
      const jobs = buildCsvImportJobs(parseCsvRows(content.replace(/^\uFEFF/, "")).slice(1), headers, mapping);
      setCsvFileName(file.name);
      setCsvHeaders(headers);
      setCsvMapping(mapping);
      setCsvJobs(jobs);
      const duplicateResponse = await fetch(`${API_BASE}/api/jobs/duplicate-check`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jobs }) });
      const duplicates = duplicateResponse.ok ? (await duplicateResponse.json()).duplicates as DuplicateCandidate[] : [];
      setCsvDuplicates(duplicates);
      setCsvIncludedPositions(new Set(jobs.map((_, index) => index + 1).filter((position) => duplicates.find((candidate) => candidate.position === position)?.category !== "exact")));
      setCsvRowPreviews(buildCsvRowPreviews(jobs));
      setCsvSaveResult(null);
    } catch {
      setCsvFileName("");
      setCsvHeaders([]);
      setCsvMapping(null);
      setCsvRowPreviews([]);
      setCsvJobs([]);
      setCsvDuplicates([]);
      setCsvSaveResult(null);
      setBatchError("无法读取 CSV 表头，请检查文件内容和编码。");
    }
  }

  async function handleCsvSave() {
    const validJobs = csvJobs.filter((job, index) => csvIncludedPositions.has(index + 1) && job.title.trim() && job.description.trim());
    if (validJobs.length === 0) {
      setBatchError("没有可保存的 CSV 岗位，请检查岗位名称和 JD 列。");
      return;
    }
    setIsCsvSaving(true);
    setBatchError("");
    try {
      const response = await fetch(`${API_BASE}/api/jobs/csv`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jobs: validJobs }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || "CSV 保存失败");
      setCsvSaveResult(result);
      const jobsResponse = await fetch(`${API_BASE}/api/jobs`);
      if (jobsResponse.ok) setJobs((await jobsResponse.json()).items);
    } catch (error) {
      setBatchError(error instanceof Error ? error.message : "暂时无法保存 CSV，请确认后端已启动。");
    } finally {
      setIsCsvSaving(false);
    }
  }

  async function handleBatchSave() {
    if (!batchPreview) return;
    setIsBatchSaving(true);
    setBatchError("");
    try {
      const response = await fetch(`${API_BASE}/api/jobs/batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: batchText, positions: [...batchIncludedPositions] }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || "批量保存失败");
      setBatchSaveResult(result);
      const jobsResponse = await fetch(`${API_BASE}/api/jobs`);
      if (jobsResponse.ok) setJobs((await jobsResponse.json()).items);
    } catch (error) {
      setBatchError(error instanceof Error ? error.message : "暂时无法保存，请确认后端已启动。");
    } finally {
      setIsBatchSaving(false);
    }
  }

  const groupedJobs = JOB_GROUPS.map((group) => ({
    ...group,
    items: jobs.filter((job) => getJobGroupId(job) === group.id),
  })).filter((group) => group.items.length > 0);

  if (isInputting) {
    return (
      <main className="app-shell">
        <div className="ambient-glow glow-one" />
        <div className="ambient-glow glow-two" />
        <section className="jd-panel">
          <button className="back-button" type="button" onClick={() => setIsInputting(false)}>← 返回首页</button>
          <p className="eyebrow">NEW APPLICATION · STEP 01</p>
          <h1>先把岗位交给我</h1>
          <p className="intro">我们会从 JD 中寻找最值得被强调的能力与经历。</p>
          <div className="input-mode-switch" aria-label="岗位录入方式">
            <button className={inputMode === "single" ? "active" : ""} type="button" onClick={() => setInputMode("single")}>单条录入</button>
            <button className={inputMode === "batch" ? "active" : ""} type="button" onClick={() => setInputMode("batch")}>批量粘贴</button>
          </div>
          {inputMode === "single" ? <><div className="form-fields">
            <label>
              <span>岗位名称</span>
              <input value={jobTitle} onChange={(event) => setJobTitle(event.target.value)} placeholder="例如：Vibe Coding Engineer" />
            </label>
            <label>
              <span>岗位 JD</span>
              <textarea value={jobDescription} onChange={(event) => setJobDescription(event.target.value)} placeholder="把岗位描述粘贴到这里……" />
            </label>
          </div>
          <div className="form-footer">
            <span className="char-count">{jobDescription.length} 字</span>
            <button className="primary-button" type="button" onClick={handlePreview} disabled={!jobDescription.trim() || isSubmitting}>{isSubmitting ? "发送中…" : "准备分析"}</button>
          </div>
          {statusMessage && <p className={`status-message ${statusMessage.startsWith("已保存") ? "success" : statusMessage.startsWith("暂时") ? "error" : "pending"}`} role="status">{statusMessage}</p>}
          </> : <>
            <div className="batch-file-entry">
              <label className="batch-file-button"><span>选择 TXT 文件</span><input key="batch-txt-file" type="file" accept=".txt,text/plain" onChange={handleBatchTxtChange} /></label>
              <p>{batchFileName ? `已读取：${batchFileName}` : "文件只在浏览器中读取，选择文件不会保存岗位。"}</p>
            </div>
            <div className="batch-file-entry csv-file-entry">
              <label className="batch-file-button"><span>选择 CSV 文件</span><input key="batch-csv-file" type="file" accept=".csv,text/csv" onChange={handleBatchCsvChange} /></label>
              <p>{csvFileName ? `已读取：${csvFileName}` : "CSV 暂时只识别表头，不会保存岗位。"}</p>
            </div>
            {csvHeaders.length > 0 && <div className="csv-header-preview"><p>识别到 {csvHeaders.length} 列</p><div>{csvHeaders.map((header) => <span key={header}>{header}</span>)}</div></div>}
            {csvMapping && <section className="csv-mapping-preview"><p className="card-label">列名映射预览</p>{CSV_MAPPING_FIELDS.map((field) => <div key={field}><span>{CSV_FIELD_LABELS[field]}</span><strong>{csvMapping[field] || "未识别"}</strong></div>)}</section>}
            {csvRowPreviews.length > 0 && <section className="csv-row-preview"><div className="batch-preview-heading"><p className="card-label">CSV 岗位预览</p><span>读取到 {csvRowPreviews.length} 条岗位</span></div><div className="batch-preview-list">{csvRowPreviews.map((item) => { const duplicate = csvDuplicates.find((candidate) => candidate.position === item.position); const locked = duplicate?.category === "exact"; return <div key={item.position}><input type="checkbox" checked={csvIncludedPositions.has(item.position)} disabled={locked} onChange={() => setCsvIncludedPositions((current) => { const next = new Set(current); next.has(item.position) ? next.delete(item.position) : next.add(item.position); return next; })} /><strong>{item.title}</strong><small>{item.company || "公司未录入"} · {item.descriptionLength} 字</small>{item.issues.length > 0 && <em>{item.issues.join("、")}</em>}{duplicate && <em>{duplicateHint(duplicate)}</em>}</div>})}</div>{csvSaveResult ? <p className="batch-save-result" role="status">已新增 {csvSaveResult.saved} 条，跳过重复 {csvSaveResult.duplicates} 条。</p> : <div className="batch-preview-actions"><p className="batch-preview-note">完全重复不可保存；其余岗位可逐条勾选保留。</p><button className="primary-button" type="button" onClick={handleCsvSave} disabled={isCsvSaving || csvIncludedPositions.size === 0}>{isCsvSaving ? "保存中…" : `确认保存 ${csvIncludedPositions.size} 条`}</button></div>}</section>}
            <div className="form-fields batch-fields">
              <label><span>多份岗位 JD</span><textarea value={batchText} onChange={(event) => { setBatchText(event.target.value); setBatchFileName(""); setBatchPreview(null); setBatchSaveResult(null); setBatchError(""); }} placeholder={'岗位一：AI工具开发\n岗位职责：……\n岗位要求：……\n\n岗位二：Agent开发\n岗位职责：……'} /></label>
              <p className="batch-format-hint">每份 JD 以“岗位一：岗位名称”或“岗位2：岗位名称”开头。</p>
            </div>
            <div className="form-footer"><span className="char-count">{batchText.length} 字</span><button className="primary-button" type="button" onClick={handleBatchPreview} disabled={!batchText.trim() || isBatchPreviewing}>{isBatchPreviewing ? "拆分中…" : "预览拆分结果"}</button></div>
            {batchError && <p className="status-message error" role="alert">{batchError}</p>}
            {batchPreview && <section className="batch-preview"><div className="batch-preview-heading"><p className="card-label">拆分预览</p><span>识别到 {batchPreview.count} 条岗位</span></div><div className="batch-preview-list">{batchPreview.items.map((item) => { const duplicate = batchPreview.duplicates?.find((candidate) => candidate.position === item.position); const locked = duplicate?.category === "exact"; return <div key={`${item.position}-${item.title}`}><input type="checkbox" checked={batchIncludedPositions.has(item.position)} disabled={locked} onChange={() => setBatchIncludedPositions((current) => { const next = new Set(current); next.has(item.position) ? next.delete(item.position) : next.add(item.position); return next; })} /><strong>{item.title}</strong><small>{item.description_length} 字</small>{duplicate && <em>{duplicateHint(duplicate)}</em>}</div>})}</div>{batchSaveResult ? <p className="batch-save-result" role="status">已新增 {batchSaveResult.saved} 条，跳过重复 {batchSaveResult.duplicates} 条。</p> : <div className="batch-preview-actions"><p className="batch-preview-note">完全重复不可保存；其余岗位可逐条勾选保留。</p><button className="primary-button" type="button" onClick={handleBatchSave} disabled={isBatchSaving || batchIncludedPositions.size === 0}>{isBatchSaving ? "保存中…" : `确认保存 ${batchIncludedPositions.size} 条`}</button></div>}</section>}
          </>}
        </section>
        <footer className="footer-note">一步一步，把合适的经历召回身边。</footer>
      </main>
    );
  }

  if (isViewingMarketProfile) {
    const jobsVersion = jobs.map((job) => job.id).join(",");
    return (
      <main className="app-shell market-page-shell">
        <div className="ambient-glow glow-one" />
        <div className="ambient-glow glow-two" />
        <section className="market-page-header">
          <button className="back-button" type="button" onClick={() => setIsViewingMarketProfile(false)}>← 返回主界面</button>
          <p className="eyebrow">JOB MARKET LIBRARY · STEP 03</p>
          <h1>从岗位样本里，<br /><span>看见真实的要求差异</span></h1>
          <p className="intro">关键词频率告诉你整体趋势；方向画像告诉你，不同岗位分别在看什么。</p>
        </section>
        <KeywordFrequencyPanel jobsVersion={jobsVersion} onOpenJob={handleOpenJobFromMarket} />
        <RoleProfilePanel jobsVersion={jobsVersion} onOpenJob={handleOpenJobFromMarket} />
        <footer className="footer-note">岗位样本会在这里慢慢长成判断力。</footer>
      </main>
    );
  }

  if (isViewingProjectFacts) {
    return <main className="app-shell market-page-shell">
      <div className="ambient-glow glow-one" /><div className="ambient-glow glow-two" />
      <section className="market-page-header"><button className="back-button" type="button" onClick={() => setIsViewingProjectFacts(false)}>← 返回主界面</button><p className="eyebrow">PROJECT FACT LIBRARY · STEP 04</p><h1>先守住真实，<br /><span>再选择如何被看见</span></h1><p className="intro">在这里维护真实项目事实；修改后需再次确认，只有已确认且证据状态为“已验证”的内容才会进入 Agent。</p></section>
      <ProjectFactPanel />
      <footer className="footer-note">真实的细节，是最可靠的作品集。</footer>
    </main>;
  }

  if (isViewingCollectorStaging) {
    return <main className="app-shell market-page-shell">
      <div className="ambient-glow glow-one" /><div className="ambient-glow glow-two" />
      <section className="market-page-header"><button className="back-button" type="button" onClick={() => setIsViewingCollectorStaging(false)}>← 返回主界面</button><p className="eyebrow">COLLECTOR REVIEW · STEP 07</p><h1>让岗位自动汇集，<br /><span>由你决定哪些值得保留</span></h1><p className="intro">启动限量采集，查看筛选原因。结果先保存在 D 盘待确认区，只有你确认后才进入正式岗位库。</p></section>
      <CollectorStagingPanel />
      <footer className="footer-note">采集只是候选，确认之后才是样本。</footer>
    </main>;
  }

  return (
    <main className="app-shell">
      <div className="ambient-glow glow-one" />
      <div className="ambient-glow glow-two" />
      <section className="hero-panel">
        <p className="eyebrow">RESUME TAILOR · MAGIC OS</p>
        <h1>让每一份经历，<br /><span>找到它的魔法重点</span></h1>
        <p className="intro">根据岗位要求，唤醒你项目经历中最适合被看见的部分。</p>
        <div className="hero-actions">
          <button className="primary-button" type="button" onClick={() => setIsInputting(true)}>开始准备</button>
          <span className="hint">从一份 JD 开始</span>
        </div>
      </section>
      <section className="workspace-entry">
        <div className="entry-symbol">✦</div>
        <div className="entry-copy">
          <p className="card-label">新的岗位定制</p>
          <h2>开始寻找你经历中最匹配的重点</h2>
          <p>粘贴一份 JD，让我们一起为它准备一份更有针对性的简历。</p>
        </div>
        <button className="entry-button" type="button" onClick={() => setIsInputting(true)}>开始</button>
        <button className="market-entry-button" type="button" onClick={() => setIsViewingMarketProfile(true)}>查看岗位市场画像</button>
        <button className="market-entry-button" type="button" onClick={() => setIsViewingProjectFacts(true)}>查看项目事实素材</button>
        <button className="market-entry-button" type="button" onClick={() => setIsViewingCollectorStaging(true)}>岗位采集 / 待确认</button>
        <label className="resume-upload"><span>导入简历</span><input type="file" accept=".docx,.pdf,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={handleResumeUpload} /></label>
        {resumeStatus && <p className="resume-status" role="status">{resumeStatus}</p>}
        {resumeFileName && <button className="resume-preview-button" type="button" onClick={handlePreviewResume} disabled={isPreviewingResume}>{isPreviewingResume ? "读取中…" : isResumeExpanded ? "收起简历内容" : "查看简历内容"}</button>}
        {resumePreview.length > 0 && isResumeExpanded && <article className="resume-preview"><p className="card-label">简历内容预览 · {resumeFileName}</p>{Object.entries(resumeSections).map(([section, paragraphs]) => paragraphs.length > 0 && <div className="resume-section" key={section}><h3>{section}</h3>{paragraphs.map((paragraph, index) => <p key={`${index}-${paragraph}`}>{paragraph}</p>)}</div>)}</article>}
      </section>
      <section className="jobs-section">
        <div className="section-heading"><p className="card-label">已保存的岗位</p><span>{jobs.length} 条记录 · 已确认 {jobs.filter((job) => job.classification_status === "confirmed").length} · 待确认 {jobs.filter((job) => job.classification_status !== "confirmed").length}</span></div>
        {jobs.length === 0 ? <p className="empty-jobs">还没有岗位记录，从一份 JD 开始。</p> : <div className="job-category-list">{groupedJobs.map((group) => <section className="job-category" key={group.id}><div className="job-category-heading"><h3>{group.label}</h3><span>{group.items.length} 条</span></div><div className="jobs-list">{group.items.map((job) => <div className="job-group" id={`job-${job.id}`} key={job.id}><button className="job-row" type="button" onClick={() => handleOpenJob(job.id)}><div><h3>{job.title}</h3><p>{job.description_length} 字 · {job.source === "manual" ? "手动导入" : job.source}</p></div><div className="job-meta"><span className="job-id">#{job.id}</span>{job.duplicate_count > 1 && <span className="duplicate-badge">重复 {job.duplicate_count} 条</span>}</div></button>{selectedJob?.id === job.id && <><JobDetailPanel job={selectedJob} isLoading={isLoadingJob} analysisMessage={analysisMessage} jobKeywords={jobKeywords} jobKeywordCategories={jobKeywordCategories} jobHighlights={jobHighlights} keywordMatch={keywordMatch} isMatching={isMatching} onClose={() => { setSelectedJob(null); setAnalysisMessage(""); setJobKeywords([]); setJobKeywordCategories({}); setJobHighlights({}); setKeywordMatch(null); setCoreMatch([]); setRecommendations([]); setTailoredDraft(null); setDraftError(""); }} onOpenJob={(jobId) => { handleOpenJob(jobId); window.setTimeout(() => document.getElementById(`job-${jobId}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 100); }} onAnalyze={handleStartAnalysis} onMatch={handleKeywordMatch} coreMatch={coreMatch} isCoreMatching={isCoreMatching} onCoreMatch={handleCoreMatch} recommendations={recommendations} isRecommending={isRecommending} onRecommend={handleRecommend} isAnalyzing={isAnalyzing} /><AgentV1Panel key={job.id} jobId={job.id} onDraftApplied={setTailoredDraft} /><TailoredDraftPanel jobId={job.id} draft={tailoredDraft} isDrafting={isDrafting} generateError={draftError} onGenerate={handleGenerateTailoredDraft} /></>}</div>)}</div></section>)}</div>}
      {selectedJob?.classification_suggestion && <ClassificationSuggestion key={selectedJob.id} suggestion={selectedJob.classification_suggestion} onConfirm={handleConfirmClassification} />}
      </section>
      <footer className="footer-note">你的职业故事，值得被认真施法。</footer>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode><App /></StrictMode>,
);

