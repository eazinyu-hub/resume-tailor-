# 本地启动与停止

适用环境：Windows 11 / PowerShell，或 Linux。建议 Python 3.12、Node.js 22.12 或更新的 22.x 版本、Git。前端和后端各占用一个终端。

## Windows：首次安装

先把 GitHub 仓库克隆或解压到 `D:\AI\resume-tailor`。以下命令假定使用这个目录。

仓库地址：https://github.com/eazinyu-hub/resume-tailor-

    git clone https://github.com/eazinyu-hub/resume-tailor-.git D:/AI/resume-tailor

```powershell
Set-Location D:\AI\resume-tailor\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

在项目根目录复制配置。已有 `.env` 时保留原文件，避免覆盖自己的密钥：

```powershell
Set-Location D:\AI\resume-tailor
if (!(Test-Path backend\.env)) { Copy-Item .env.example backend\.env }
```

用文本编辑器打开 `backend/.env`，检查：

```dotenv
DATA_DIR=D:/AI/resume-tailor-data
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-flash
```

想使用 AI 候选时，在 `DEEPSEEK_API_KEY=` 后填自己的 Key。留空仍可导入岗位、查看本地分析和使用草稿功能。密钥只放后端；`frontend/.env` 只设置地址。

前端首次安装：

```powershell
Set-Location D:\AI\resume-tailor\frontend
npm ci
```

## Windows：每次启动

第一个终端启动后端，保持这个窗口运行：

```powershell
Set-Location D:\AI\resume-tailor\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

第二个终端启动前端：

```powershell
Set-Location D:\AI\resume-tailor\frontend
npm run dev
```

前端：<http://127.0.0.1:5173/>。后端接口说明：<http://127.0.0.1:8000/docs>。

前端默认通过 `/api` 代理访问后端。后端启动后会读取 `backend/.env`，系统环境变量优先于文件中的值。未配置 `DATA_DIR` 时使用项目旁边的 `resume-tailor-data` 文件夹；项目位于 `D:\AI\resume-tailor` 时，就是 `D:\AI\resume-tailor-data`。修改后端配置需要停止并重新启动后端。

## 第一次使用：自己的数据或演示数据

自己的工作台初始没有岗位、简历或事实卡。导入自己的 Word 简历和 JD；当前 PDF 上传只保存文件，尚不能提取内容用于分析。Word 内容提取也依赖“个人简介、教育背景、工作经历、项目经历、技术与工具”等章节标题。

在根目录执行下面的命令，创建一张待填写的事实卡。已有事实卡时不会覆盖：

```powershell
Set-Location D:\AI\resume-tailor
.\backend\.venv\Scripts\python.exe scripts\initialize_project_facts.py --data-dir D:\AI\resume-tailor-data
```

进入“查看项目事实素材”，填写实际做过的功能、技术、调试和证据，再确认。模板没有任何预先验证的个人经历。当前 DeepSeek 候选只处理 `project-resume-tailor` 这一张卡。

想先体验完整流程，可在另一个空目录创建两条脱敏合成岗位、示例简历和示例事实卡：

```powershell
Set-Location D:\AI\resume-tailor
.\backend\.venv\Scripts\python.exe scripts\prepare_demo_data.py --target D:\AI\resume-tailor-demo
Set-Location backend
$env:DATA_DIR = 'D:\AI\resume-tailor-demo'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

另开前端终端，用不同端口连接该演示后端：

```powershell
Set-Location D:\AI\resume-tailor\frontend
$env:BACKEND_PROXY_URL = 'http://127.0.0.1:8001'
npm run dev -- --port 5174
```

打开 <http://127.0.0.1:5174/>。演示目录是独立的；不能把示例经历当成自己的经历写进简历。创建脚本拒绝覆盖非空目录。真实生成按钮会调用使用者自己的 DeepSeek Key；仓库中的演示视频使用已验收结果回放。

## 停止与重新启动

分别在前端、后端终端按 `Ctrl+C`。数据保留，下次启动仍在。修改代码或 `.env` 后重新启动对应服务即可。无需删除数据库或安装卸载程序。

要从演示切回自己的数据，关闭演示服务后，新开终端按“每次启动”运行，或清除当前终端中临时设置的变量：

```powershell
Remove-Item Env:DATA_DIR -ErrorAction SilentlyContinue
Remove-Item Env:BACKEND_PROXY_URL -ErrorAction SilentlyContinue
```

## Linux

克隆后在项目根目录运行。使用当前用户可写的独立数据目录：

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
test -f backend/.env || cp .env.example backend/.env
```

编辑 `backend/.env`，把 Windows 的 `DATA_DIR` 改为自己的绝对目录，例如 `/home/example/resume-tailor-data`，填入自己的 Key（可留空）。然后：

```bash
cd backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端进入项目根目录：

```bash
cd frontend
npm ci
npm run dev
```

创建空事实卡的 Linux 命令：

```bash
backend/.venv/bin/python scripts/initialize_project_facts.py --data-dir /home/example/resume-tailor-data
```

替换示例用户名和目录。前后端仍使用上述两个地址，通过 `Ctrl+C` 停止。

## 常见问题

| 现象 | 处理方法 |
| --- | --- |
| `No module named uvicorn` | 确认安装过依赖，并用项目 `.venv` 中的 Python 启动，不用其他全局 Python。 |
| 找不到 `app` | 先进入 `backend`，再执行 `-m uvicorn app.main:app`。 |
| 端口被占用 | 先在原终端按 `Ctrl+C`；或同时调整后端端口和前端 `BACKEND_PROXY_URL`。不要结束未知进程。 |
| 前端没有岗位 | 检查后端运行状态及 `DATA_DIR`；一个新的数据目录本来就是空的。 |
| AI 按钮不可用 | 检查后端 `.env` 的 Key，重新启动后端；连接测试会调用一次 API。 |
| 没有事实卡或没有已验证事实 | 先创建模板，在页面填写并确认真实事实。 |
| 导入简历后不能分析 | 先使用带明确章节标题的 DOCX；PDF 解析尚未实现。 |
| 候选应用时提示内容变化 | 重新预览并生成；旧候选不能覆盖更新后的 JD 或事实。 |

## 验证代码

在后端目录运行，不访问真实 DeepSeek：

```powershell
Set-Location D:\AI\resume-tailor\backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'
```

前端目录运行 `npm run build`。Linux 把 Python 路径改为 `.venv/bin/python`。
