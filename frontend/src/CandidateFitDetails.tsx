type FitRequirement = {
  category: string;
  label: string;
  kind: "required" | "preferred" | "conditional" | "unrestricted";
  evidence: string;
  assessment: "matched" | "unmet" | "unknown" | "not_required";
  explanation: string;
};

export type CandidateFitAssessment = {
  status: "ready" | "profile_missing";
  score: number | null;
  level: "recommended" | "stretch" | "low_priority" | "unavailable" | "insufficient_information";
  label: string;
  score_note: string;
  strengths: string[];
  barriers: string[];
  requirements?: FitRequirement[];
  uncertainties?: string[];
};

export function candidateFitScoreLabel(fit: CandidateFitAssessment) {
  if (fit.score !== null) return `${fit.score} 分`;
  return fit.status === "profile_missing" ? "未配置" : "待核实";
}

const GROUPS = [
  ["required", "必须满足"],
  ["preferred", "优先条件"],
  ["conditional", "允许放宽或替代"],
  ["unrestricted", "明确不限制"],
] as const;

export function CandidateFitDetails({ fit }: { fit: CandidateFitAssessment }) {
  const requirements = fit.requirements || [];
  const uncertainties = fit.uncertainties || [];
  if (!requirements.length && !uncertainties.length) return null;

  return <details className="candidate-fit-evidence">
    <summary>查看条件判断与 JD 原文依据</summary>
    {GROUPS.map(([kind, label]) => {
      const group = requirements.filter((item) => item.kind === kind);
      if (!group.length) return null;
      return <section key={kind}>
        <h4>{label}</h4>
        <ul>{group.map((item, index) => <li key={`${item.category}-${index}`}>
          <strong>{item.label}</strong>
          <blockquote>{item.evidence}</blockquote>
          <p>{item.explanation}</p>
        </li>)}</ul>
      </section>;
    })}
    {uncertainties.length > 0 && <section>
      <h4>没有写明 / 需要核实</h4>
      <ul>{uncertainties.map((note) => <li key={note}>{note}</li>)}</ul>
    </section>}
  </details>;
}
