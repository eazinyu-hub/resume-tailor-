# JD 样本库 SQLite 结构与迁移方案（V1）

## 1. 目的

本设计将岗位样本卡映射为 SQLite 存储结构，并定义现有数据的无损迁移和失败回退方式。

本小步只写设计文档，不执行 SQL，不修改后端代码，也不接触 `D:\AI\resume-tailor-data\runtime\app.sqlite3`。

## 2. 当前数据库

当前数据库包含两张与本次设计相关的表：

### `jobs`

| 当前字段 | 用途 |
| --- | --- |
| `id` | 岗位本地编号 |
| `title` | 原始岗位名称 |
| `description` | 原始 JD |
| `source` | 来源或导入方式 |
| `created_at` | 首次录入时间 |

### `resume_drafts`

保存每个岗位对应的简历草稿。本阶段不修改这张表。

## 3. V1 存储决定

1. 保留现有 `jobs` 表作为原始岗位数据表。
2. 不重命名现有字段，避免破坏已经跑通的接口。
3. 在 `jobs` 上补充来源、地区、薪资、内容指纹和重复关系等元数据。
4. 新增 `job_analyses` 表，独立保存可重新生成的分析结果。
5. 同一岗位允许存在多个分析版本。
6. 真实数据库继续保存在 D 盘个人数据目录，不进入 Git。

## 4. `jobs` 表扩展

### 4.1 保留字段

| 数据库字段 | 样本卡含义 | 迁移处理 |
| --- | --- | --- |
| `id` | `id` | 原样保留 |
| `title` | `title_raw` | 原样保留 |
| `description` | `description_raw` | 原样保留 |
| `source` | `source` | 原样保留 |
| `created_at` | `collected_at` | 原样保留 |

数据库暂时保留现有简短字段名，API 或界面可以将它们解释为样本卡中的原始字段。

### 4.2 新增字段

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `company` | `TEXT` | `NULL` | 原始公司名称 |
| `source_url` | `TEXT` | `NULL` | 原始岗位链接 |
| `published_at` | `TEXT` | `NULL` | 岗位页面显示的发布时间 |
| `city` | `TEXT` | `NULL` | 地区原文 |
| `salary` | `TEXT` | `NULL` | 薪资原文 |
| `content_hash` | `TEXT` | `NULL` | 标准化 JD 正文的 SHA-256 指纹 |
| `duplicate_of` | `INTEGER` | `NULL` | 指向较早保存的主样本 |
| `sample_status` | `TEXT` | `active` | `active`、`duplicate` 或 `invalid` |
| `updated_at` | `TEXT` | `NULL` | 用户明确修正原始录入数据的时间 |

### 4.3 字段约束

- `title` 和 `description` 继续保持非空。
- `sample_status` 只允许 `active`、`duplicate`、`invalid`。
- `duplicate_of` 必须指向 `jobs.id`，且不能指向自身。
- `content_hash` 不设置唯一约束，因为重复样本仍需要保留来源和采集时间。
- 时间继续使用 SQLite 可排序的 ISO 风格文本，后续统一明确时区展示规则。

## 5. 新增 `job_analyses` 表

### 5.1 字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | 分析版本编号 |
| `job_id` | `INTEGER NOT NULL` | 对应的原始岗位 |
| `role_family` | `TEXT` | 六种标准岗位方向之一 |
| `content_json` | `TEXT NOT NULL` | 结构化分析正文 |
| `analysis_status` | `TEXT NOT NULL` | `pending`、`generated`、`confirmed`、`failed` |
| `analyzer_version` | `TEXT` | 规则、提示词或 Agent 版本 |
| `is_current` | `INTEGER NOT NULL` | `1` 表示当前采用版本，`0` 表示历史或候选版本 |
| `supersedes_analysis_id` | `INTEGER` | 新候选版本准备替代的旧版本 |
| `created_at` | `TEXT NOT NULL` | 分析记录创建时间 |
| `updated_at` | `TEXT NOT NULL` | 最近修改时间 |
| `confirmed_at` | `TEXT` | 用户确认时间 |

### 5.2 `content_json` 内容

```json
{
  "focus_summary": "强调 AI Coding、独立全栈交付和部署验证",
  "responsibilities": ["需求拆解", "前后端开发"],
  "must_have_requirements": ["能够独立完成小型功能"],
  "nice_to_have_requirements": ["有可演示 Demo"],
  "skills_and_tools": ["Codex", "React", "Python"],
  "experience_requirement": "1-3 年，优秀应届生可投",
  "education_requirement": null,
  "evidence_spans": [
    {
      "claim_type": "must_have_requirement",
      "claim": "能够独立完成小型功能",
      "quote": "独立完成小型功能或原型的前后端开发"
    }
  ],
  "error_message": null
}
```

V1 将常用筛选字段 `role_family` 单独保存，其余分析内容保存在 JSON 中。这样能保持结构简单，同时允许后续增加分析字段。

### 5.3 版本规则

- 每个岗位最多只有一个 `is_current = 1` 的分析版本。
- 首次创建的 `pending` 记录可以成为当前版本。
- 未人工确认的 `generated` 版本允许更新或重新生成。
- 当前版本为 `confirmed` 时，重新分析必须新增 `is_current = 0` 的候选版本。
- 用户确认候选版本时，在同一事务中将旧版本设为 `is_current = 0`，再将新版本设为 `is_current = 1`。
- 历史分析版本不修改 `jobs` 中的原始 JD。

## 6. 索引设计

V1 计划建立以下索引：

| 索引 | 用途 |
| --- | --- |
| `jobs(content_hash)` | 查找完全重复 JD |
| `jobs(sample_status)` | 过滤有效、重复和无效样本 |
| `jobs(created_at)` | 按采集时间排序 |
| `job_analyses(job_id)` | 查询岗位的所有分析版本 |
| `job_analyses(role_family)` | 按岗位方向统计和检索 |
| `job_analyses(job_id, is_current)` | 获取当前采用的分析版本 |

后续实现时应使用部分唯一索引，保证同一岗位最多只有一个 `is_current = 1` 的分析版本。

## 7. 关系

```text
jobs
 ├─ resume_drafts       一个岗位最多一份当前简历草稿
 └─ job_analyses        一个岗位可以有多个分析版本
```

- `resume_drafts.job_id` 继续关联 `jobs.id`。
- `job_analyses.job_id` 关联 `jobs.id`。
- `jobs.duplicate_of` 关联另一条 `jobs.id`。
- `job_analyses.supersedes_analysis_id` 关联另一条分析版本。

V1 不自动级联删除岗位，防止误删简历草稿或分析历史。

## 8. 内容指纹规则

完全重复判断只使用标准化后的 JD 正文，不使用岗位名称：

```text
原始 description
→ 统一 Windows/Linux 换行
→ 去除每行首尾空白
→ 将连续空白压缩为一个空格
→ 去除首尾空白
→ 转为 UTF-8
→ 计算 SHA-256
```

这样可以识别“岗位名称略有不同、正文完全相同”的重复发布，同时保留未经处理的原始 `description`。

## 9. 迁移顺序

### 9.1 迁移前检查

1. 确认数据库路径为 `D:\AI\resume-tailor-data\runtime\app.sqlite3`。
2. 检查 SQLite `integrity_check`。
3. 记录 `jobs` 和 `resume_drafts` 的行数。
4. 使用 SQLite Backup API 在 D 盘数据目录创建带时间戳的备份。
5. 确认备份文件可以打开后再开始迁移。

### 9.2 结构迁移

1. 开启外键检查。
2. 开启一个数据库事务。
3. 检查 `jobs` 当前已有字段，缺少哪个字段才添加哪个字段。
4. 创建 `job_analyses` 表和索引。
5. 为现有岗位补充 `sample_status = active`。
6. 根据现有 `description` 计算并回填 `content_hash`。
7. 按 `id` 从小到大选择主样本，标记完全重复记录。
8. 更新数据库 schema 版本。
9. 提交事务。

### 9.3 迁移后验证

- `jobs` 行数与迁移前一致。
- `resume_drafts` 行数与迁移前一致。
- 每条现有岗位的 `id`、`title`、`description`、`source`、`created_at` 不变。
- 每条有效 JD 都有 `content_hash`。
- 重复记录只增加状态和关联，不删除数据。
- `foreign_key_check` 没有错误。
- `integrity_check` 返回正常。
- 原有岗位列表、岗位详情和简历草稿仍可读取。

## 10. 幂等迁移

迁移必须可以安全重复运行：

- 添加字段前先检查 `PRAGMA table_info(jobs)`。
- 建表和建索引使用存在性检查。
- 已有 `content_hash` 不重复改写，除非指纹算法版本明确升级。
- 已标记的重复关系不在每次启动时随意变化。
- 数据库 schema 版本用于判断是否需要迁移。

## 11. 失败回退

### 11.1 事务内失败

任何建表、加字段或回填步骤失败时回滚事务，原始岗位数据保持不变。

### 11.2 迁移后发现问题

1. 停止后端，避免继续写入。
2. 保留出问题的数据库用于排查，不直接覆盖。
3. 从迁移前的时间戳备份恢复一份数据库。
4. 对恢复文件运行完整性检查。
5. 重新启动旧版本代码并验证岗位数量和简历草稿。

回退不通过删除列完成，因为 SQLite 删除列和外键迁移风险更高；优先恢复已验证的完整备份。

## 12. Windows 与 Linux 兼容

- 数据库路径通过 `DATA_DIR` 配置，不在代码中写死盘符。
- Windows 当前使用 `D:\AI\resume-tailor-data`。
- Linux 部署时使用独立挂载目录，例如 `/data/resume-tailor`。
- 数据库存储 ISO 时间文本，不依赖 Windows 地区格式。
- 内容指纹统一基于 UTF-8 和标准化换行，确保跨系统结果一致。

## 13. Git 与个人数据边界

进入 Git：

- 建表和迁移代码
- 数据结构文档
- 自动化测试
- 脱敏示例数据库或示例 JSON

不进入 Git：

- `app.sqlite3`
- 数据库备份
- 真实公司名称和岗位链接
- 真实 JD 全文
- 个人简历和岗位级简历草稿

## 14. 下一实施阶段的最小拆分

设计确认后，真正实施仍分小步：

1. 只加入数据库 schema 版本和备份函数。
2. 只给 `jobs` 添加新字段，不回填内容指纹。
3. 只创建 `job_analyses` 表和索引。
4. 为现有岗位回填内容指纹并标记完全重复。
5. 验证现有接口和 8 条岗位数据。

每一步单独验证并提交 Git。

## 15. 本小步不做的内容

- 不执行数据库备份。
- 不修改真实数据库。
- 不新增或删除岗位。
- 不修改前后端代码。
- 不改变现有重复岗位显示逻辑。
- 不实现岗位分析持久化。
- 不实现批量导入和自动采集。

