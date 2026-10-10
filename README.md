# Resume Tailor / AI 简历适配工作台

一个面向个人求职的本地优先工作流：收集并整理真实岗位 JD，形成岗位市场画像，把已确认的个人项目事实映射到当前岗位，再由用户确认是否应用到该岗位的简历草稿。

核心约束是：岗位可以变化，表达重点可以变化，个人事实不能变化。

本项目作为个人作品公开代码，使用者下载后在本机运行，并配置自己的 DeepSeek Key。先看 [本地启动说明](docs/local-startup.md) 和 [脱敏演示](docs/demo-guide.md)。

![同一项目面对两个岗位的表达对照](docs/demo/two-job-comparison.png)

## 演示视频：下载后播放

[下载 2 分 20 秒中文字幕演示（MP4，约 6.8 MB）](https://github.com/eazinyu-hub/resume-tailor-/raw/refs/heads/main/docs/demo/resume-tailor-demo.mp4)

点击上面的链接下载，用本机视频播放器打开即可；无需安装项目或配置 API Key。若浏览器直接播放，也可以右键“视频另存为”。

备用方式：打开[视频文件页面](docs/demo/resume-tailor-demo.mp4)，点击右上角 **Download raw file（下载）** 按钮。下载整个仓库 ZIP 后，也能在 `docs/demo/resume-tailor-demo.mp4` 找到同一视频。

演示包含真实页面、确认保存和文件导出，使用此前验收过的合成模型结果回放，本次录制未调用 API。[查看演示范围与复现说明](docs/demo-guide.md)。

## 当前能力

- 单条、批量文本、TXT 和 CSV 导入 JD，重复识别与人工分类。
- 按岗位方向统计关键词、职责、技术栈和交付能力，生成市场画像。
- 保存项目事实卡，并区分“已验证、需要补充、计划实现、禁止写入简历”。
- 综合当前 JD、相似岗位、市场画像、原始简历和项目事实进行岗位级分析。
- 使用 DeepSeek 为“AI 简历适配工作台”生成最多两个有事实引用的项目描述候选。
- 候选不会自动覆盖草稿；用户选择并再次确认后，才保存到当前岗位。
- 不同岗位分别保存草稿，旧稿在替换前备份；支持继续编辑并导出 Word / PDF。
- Greenhouse、Lever、Moka 等公开招聘页面的候选发现、暂存、人工确认和定时采集。

## 两个固定脱敏案例

仓库包含一对不使用真实公司、真实简历或私人 JD 的固定回归案例：

| 目标岗位 | 应突出内容 | 不应擅自出现 |
| --- | --- | --- |
| AI 工具与自动化专员 | 批量导入、重复识别、定时采集和人工确认 | 真实招聘客户、线上用户成果 |
| Vibe Coding 全栈工程师 | React 前端、FastAPI 接口、SQLite 存储、草稿编辑与导出 | 未验证的部署、用户和指标 |

测试要求两份项目描述和最终草稿确实不同，同时引用同一份已确认事实。运行：

    cd backend
    .\.venv\Scripts\python.exe -m unittest tests.test_deepseek_agent_demo

该测试使用固定的模拟模型输出，不消耗 API 额度。两个合成案例还完成过真实 DeepSeek 调用与确认应用，见 [验收记录](docs/live-demo-acceptance.md)；它只验证这两个案例，不能证明所有岗位的生成质量。

## 工作流

    岗位 JD
      ├─ 去重、分类、市场画像
      └─ 当前岗位 + 相似样本
                     │
    个人事实卡 ───────┼─> 事实约束候选 ─> 人工选择 ─> 二次确认
    原始简历 ─────────┘                                  │
                                                        └─> 当前岗位草稿 ─> 编辑 / Word / PDF

生成阶段只产生候选记录。应用阶段会重新核对岗位、事实卡和上下文摘要；内容已变化时拒绝应用旧候选。取消候选不会修改已有草稿。

## 技术栈

- 前端：React、TypeScript、Vite
- 后端：Python、FastAPI、SQLite
- 文档导出：ReportLab、DOCX XML
- AI：DeepSeek API（后端调用，密钥不进入浏览器）
- 工程验证：Python unittest、TypeScript 编译、Vite 构建

## 数据与密钥边界

仓库只保留代码、设计文档和脱敏示例。以下内容应位于仓库之外的 DATA_DIR：

- 原始简历、岗位数据库和采集暂存内容
- 项目事实卡和个人匹配资料
- DeepSeek 候选记录及旧草稿备份
- Word / PDF 等个人导出文件

真实 DeepSeek 密钥放在 backend/.env 或服务器环境变量中。.env 只是被 Git 忽略的本地明文配置，不是加密保险箱；不要将其提交、截图或放入前端 VITE_ 变量。

    DEEPSEEK_API_KEY=your_key_here
    DEEPSEEK_MODEL=deepseek-flash

DeepSeek 首版接收页面明确展示的当前 JD、一个项目的已确认事实、限制项和少量市场参考，不读取完整简历、照片或密钥。输入文本不会自动脱敏；若 JD、事实或参考标题中含有个人信息、公司或本地路径，这些文字也会被发送。调用前需要查看并清理发送预览。

## 本地启动

### Windows 11 / PowerShell

建议 Node.js 22.12+、Python 3.12。完整的首次安装、配置、停止、演示数据与常见报错见 [本地启动说明](docs/local-startup.md)。

    git clone <your-repository-url>
    cd resume-tailor

    cd backend
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    if (!(Test-Path .env)) { Copy-Item ..\.env.example .env }
    $env:DATA_DIR = "D:\AI\resume-tailor-data"
    .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

另开一个 PowerShell：

    cd resume-tailor\frontend
    npm ci
    npm run dev -- --host 127.0.0.1

打开 http://127.0.0.1:5173/。

### Linux

    git clone <your-repository-url>
    cd resume-tailor/backend
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
    export DATA_DIR="$HOME/.local/share/resume-tailor"
    .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

另开终端：

    cd resume-tailor/frontend
    npm ci
    npm run dev -- --host 127.0.0.1

生产部署还需要反向代理、HTTPS、访问鉴权、API 限额和持久化目录；当前仓库不能直接作为公开代付 AI 服务暴露到互联网。

## 测试

后端测试不会访问真实 DeepSeek：

    cd backend
    $env:PYTHONUTF8 = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

前端检查：

    cd frontend
    npm run build

## 采集合规边界

自动采集优先使用企业公开招聘页面和公开接口，并设置来源范围、冷却时间、单次上限、暂存审核与失败记录。Boss 直聘目前以手动复制、TXT 或 CSV 导入为主。

本项目不绕过登录、验证码、访问控制或平台风控，不承诺任何平台允许自动化采集。使用者需要自行检查目标网站的服务条款、robots.txt 和当地法律。

## 当前限制

- 这是个人本地项目，尚未证明拥有真实招聘客户、规模化用户或线上业务效果。
- DeepSeek 输出经过结构、事实 ID、JD 引文和明显夸大检查，但程序校验不能替代人工语义判断。
- 当前 AI 候选只处理“AI 简历适配工作台”一个项目；其他项目需要先建立并确认事实卡。
- 采集来源、岗位画像和匹配算法仍会随真实样本增加而迭代。
- 自动测试覆盖候选生成、确认应用、旧稿备份和岗位隔离；两个合成岗位完成过真实模型验收，真实求职效果尚未验证。
- PDF 上传只保存文件，尚未实现文本解析；DOCX 提取依赖章节标题，复杂表格简历可能需要手动整理。
- 首次使用需创建并填写事实卡；仓库示例不是使用者自己的经历。

## 仓库结构

    resume-tailor/
    ├─ frontend/        # React 前端
    ├─ backend/         # FastAPI、SQLite 与测试
    ├─ examples/        # 脱敏示例
    ├─ docs/            # 设计、边界与验收记录
    ├─ scripts/         # 辅助脚本
    ├─ .env.example     # 无真实密钥的配置示例
    └─ .gitignore

## 公开前状态

代码正在整理为可本地运行的公开版本。GitHub 远程地址确认并推送后会在这里补充仓库链接。发布准备包括：

1. 已完成的两个固定案例真实 DeepSeek 验收及脱敏结果。
2. 桌面与窄屏演示检查，确认无姓名、联系方式、公司和本地路径。
3. Word / PDF 一页排版复核。
4. Git 暂存区、历史和构建产物的密钥与个人数据扫描。
5. 发布到使用者指定的 GitHub 账号；许可证未指定时不擅自添加授权文件。

详细评价标准见 [Agent 评价标准](docs/agent-evaluation-rubric.md)，DeepSeek 接入边界见 [DeepSeek 接入方案](docs/agent-deepseek-v1-plan.md)。
