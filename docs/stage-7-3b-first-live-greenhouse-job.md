# 阶段 7.3-B：首条真实 Greenhouse 岗位

状态：真实请求验证通过，待用户确认

## 试点来源

- 公司：Anthropic
- 招聘板：<https://job-boards.greenhouse.io/anthropic>
- 读取方式：Greenhouse 官方 Job Board API
- 登录与密钥：均不需要
- 请求范围：一个公开岗位详情
- 试点岗位：Software Engineer, Research Tools

选择该岗位是为了验证与 AI 工具、工作流理解和全栈工程相关的公开 JD，
不是将它直接作为当前中文求职市场画像的训练样本。

## 安全限制

- 只允许代码中已审核的招聘板；
- 只允许数字岗位 ID；
- 请求固定发送到 `boards-api.greenhouse.io`；
- 只允许 GET，不发送 Authorization、Cookie 或候选人信息；
- 单条响应最大 2 MB，超限立即停止；
- 非预期重定向、无效 JSON 和网络错误均停止保存；
- 结果仅追加到 D 盘采集暂存区，状态保持 `pending`。

## 不影响主应用

该命令独立于 FastAPI 运行。请求失败不会影响岗位列表、岗位分析、个人事实库、
简历生成与导出功能。

## 首次验证结果

- 请求次数：1
- 暂存岗位数：1
- 岗位名称：Software Engineer, Research Tools
- 公司：Anthropic
- 清洗后 JD 长度：10,608 个字符
- 暂存状态：`pending`
- 暂存位置：`D:\AI\resume-tailor-data\collector-staging\pending-jobs.jsonl`
- 正式岗位数据库：未写入
- Git 仓库：未保存真实 JD

## 执行命令

```powershell
cd D:\AI\resume-tailor\backend
.\.venv\Scripts\python.exe -m collector.run_greenhouse_once `
  --board anthropic `
  --job-id 4981828008
```

官方 API 依据：<https://docs.greenhouse.io/job-board.html>
