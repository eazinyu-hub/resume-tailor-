# JD 岗位样本卡（V1）

## 1. 目的

岗位样本卡用于长期积累真实 JD，并为后续的岗位分类、市场画像、相似岗位检索和简历匹配 Agent 提供可靠数据。

V1 只定义数据内容，不修改数据库、接口或前端，也不实现自动采集。

## 2. 设计原则

1. **原文优先**：始终保存招聘方原始 JD，分析结果不能覆盖原文。
2. **分析可重跑**：岗位分类、关键词和要求识别单独保存，算法升级后可以重新生成。
3. **结果可追溯**：每项分析结论应尽量保留对应的 JD 原文片段。
4. **重复可识别**：通过内容指纹识别完全重复，并为近似重复预留能力。
5. **隐私与仓库分离**：真实岗位数据保存在 `D:\AI\resume-tailor-data`，Git 仓库只保留脱敏示例。
6. **先支持人工确认**：系统可以建议岗位分类，但最终允许用户确认或修改。

## 3. 样本卡结构

一张岗位样本卡由两部分组成：原始岗位数据和派生分析结果。

### 3.1 原始岗位数据

| 字段 | 是否必填 | 说明 | 示例 |
| --- | --- | --- | --- |
| `id` | 自动生成 | 本地唯一编号 | `sample-0001` |
| `title_raw` | 是 | 招聘方填写的原始岗位名称 | `Vibe Coding 全栈工程师` |
| `company_raw` | 否 | 原始公司名称；公开示例需要脱敏 | `某 AI 应用公司` |
| `description_raw` | 是 | 完整原始 JD，不做改写 | `负责 AI 应用……` |
| `source` | 是 | 来源平台或导入方式 | `BOSS直聘`、`手动导入` |
| `source_url` | 否 | 原始岗位链接 | `https://example.invalid/job/1` |
| `published_at` | 否 | 岗位页面显示的发布时间 | `2026-08-20` |
| `collected_at` | 自动生成 | 本地录入或采集时间 | `2026-09-04T10:00:00+08:00` |
| `city_raw` | 否 | 页面中的地区原文 | `杭州` |
| `salary_raw` | 否 | 页面中的薪资原文 | `15-25K` |
| `content_hash` | 自动生成 | 根据标准化后的 JD 正文生成，用于完全重复判断 | `sha256:…` |
| `duplicate_of` | 否 | 若确认为重复，记录主样本 ID | `sample-0001` |
| `sample_status` | 是 | 样本是否可用于分析 | `active`、`duplicate`、`invalid` |

### 3.2 派生分析结果

这些内容由规则或 Agent 产生，可以删除并重新分析。

| 字段 | 说明 | 示例 |
| --- | --- | --- |
| `role_family` | 标准岗位方向 | `vibe_coding_fullstack` |
| `focus_summary` | 一句话概括岗位侧重点 | `强调 AI Coding、独立全栈交付和部署验证` |
| `responsibilities` | 拆分后的主要职责 | `需求拆解`、`前后端开发`、`部署验证` |
| `must_have_requirements` | 硬性要求 | `能够独立完成前后端开发` |
| `nice_to_have_requirements` | 加分项 | `有可访问 Demo` |
| `skills_and_tools` | 技术、框架和 AI 工具 | `React`、`Python`、`Codex` |
| `experience_requirement` | 工作或项目经验要求 | `1-3 年，优秀应届生可投` |
| `education_requirement` | 学历和专业要求 | `本科及以上` |
| `evidence_spans` | 支撑分析结论的 JD 原文片段 | `独立完成小型功能或原型……` |
| `analysis_status` | 分析状态 | `pending`、`generated`、`confirmed`、`failed` |
| `analyzer_version` | 生成该结果的规则或提示词版本 | `jd-analyzer-v1` |
| `analyzed_at` | 最近分析时间 | `2026-09-04T10:05:00+08:00` |

## 4. V1 岗位方向

首版只设置六个方向，避免分类过细：

| 标识 | 中文名称 | 主要判断依据 |
| --- | --- | --- |
| `ai_tool_automation` | AI 工具与自动化开发 | 内部工具、脚本、数据处理、流程自动化 |
| `vibe_coding_fullstack` | Vibe Coding 全栈开发 | AI Coding、前后端、接口联调、部署和完整交付 |
| `agent_application` | Agent 应用开发 | Agent 架构、工具调用、工作流、智能体配置与调试 |
| `ai_product_operations` | AI 产品与运营 | 产品配置、客户交付、运营、培训和反馈闭环 |
| `internal_intelligence` | 内部智能化系统 | 管理后台、数据看板、内部数据和业务提效 |
| `indie_ai_developer` | 独立开发与一人公司 | App 独立开发、上线、维护和持续迭代 |

如果一个岗位跨多个方向，V1 先保存一个主要方向；多标签能力留到后续验证确有需要时再增加。

## 5. 分析证据规则

为了避免 Agent 凭空判断，派生结果需要遵守以下规则：

- 硬性要求和加分项必须能定位到 JD 原文。
- 原文没有提及的技术不能标记为该岗位明确要求。
- 市场高频能力只能作为“同类岗位常见要求”，不能伪装成当前 JD 原文。
- 人工确认后的分析结果需要保留确认状态。
- 重新分析时保留原始 JD，不直接覆盖人工确认结果。

## 6. 脱敏示例

```json
{
  "raw": {
    "id": "sample-0001",
    "title_raw": "Vibe Coding 全栈工程师",
    "company_raw": "某 AI 应用公司",
    "description_raw": "使用 AI Coding 工具完成需求拆解、前后端开发、接口联调和部署验证。要求有真实个人项目或可演示 Demo。",
    "source": "手动导入",
    "source_url": null,
    "published_at": null,
    "collected_at": "2026-09-04T10:00:00+08:00",
    "city_raw": "杭州",
    "salary_raw": null,
    "content_hash": "sha256:example",
    "duplicate_of": null,
    "sample_status": "active"
  },
  "analysis": {
    "role_family": "vibe_coding_fullstack",
    "focus_summary": "强调 AI Coding 和独立全栈交付",
    "responsibilities": ["需求拆解", "前后端开发", "接口联调", "部署验证"],
    "must_have_requirements": ["使用 AI Coding 工具完成开发闭环"],
    "nice_to_have_requirements": ["有真实个人项目或可演示 Demo"],
    "skills_and_tools": ["AI Coding"],
    "experience_requirement": null,
    "education_requirement": null,
    "evidence_spans": [
      "使用 AI Coding 工具完成需求拆解、前后端开发、接口联调和部署验证",
      "要求有真实个人项目或可演示 Demo"
    ],
    "analysis_status": "generated",
    "analyzer_version": "jd-analyzer-v1",
    "analyzed_at": "2026-09-04T10:05:00+08:00"
  }
}
```

## 7. 第一阶段验收标准

- 能完整保存原始 JD 和基本来源信息。
- 原始数据与分析结果边界清楚。
- 可以识别完全重复的 JD。
- 分析结果能够追溯到原文证据。
- 现有 8 条岗位未来可以无损迁移。
- 真实岗位数据不会进入 GitHub。

## 8. 本小步不做的内容

- 不修改 SQLite。
- 不迁移现有岗位。
- 不增加前端页面。
- 不增加后端接口。
- 不实现批量导入。
- 不实现 BOSS 直聘爬虫。
- 不接入或训练 Agent。

