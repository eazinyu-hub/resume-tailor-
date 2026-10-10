// Record the real local UI. Only model output/status use the explicitly labelled replay.
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

const args = Object.fromEntries(process.argv.slice(2).reduce((items, item, i, all) => {
  if (item.startsWith("--")) items.push([item.slice(2), all[i + 1]]);
  return items;
}, []));
if (!args.manifest || !args.output) throw new Error("Use --manifest <synthetic replay manifest> --output <directory>.");
const manifest = JSON.parse(await fs.readFile(args.manifest, "utf8"));
if (!manifest.replay || manifest.cases.length !== 2) throw new Error("Expected the two synthetic replay cases.");
const output = path.resolve(args.output);
await fs.mkdir(output, { recursive: true });
const library = args["playwright-module"] ? pathToFileURL(path.resolve(args["playwright-module"])).href : "playwright";
const { chromium } = await import(library);
let bridge;
let bridgeRequest;
if (args["static-root"]) {
  if (!args["backend-python"] || !args["data-dir"]) throw new Error("Static recording requires --backend-python and --data-dir.");
  bridge = spawn(args["backend-python"], [path.resolve("scripts/demo_asgi_bridge.py"), "--data-dir", path.resolve(args["data-dir"])], { stdio: ["pipe", "pipe", "inherit"] });
  const pending = new Map(); let nextId = 0;
  createInterface({ input: bridge.stdout }).on("line", line => {
    const reply = JSON.parse(line); const waiter = pending.get(reply.id); if (!waiter) return;
    pending.delete(reply.id); if (reply.error) waiter.reject(new Error(reply.error)); else waiter.resolve(reply);
  });
  bridge.on("exit", code => { for (const waiter of pending.values()) waiter.reject(new Error(`Backend bridge exited: ${code}`)); pending.clear(); });
  bridgeRequest = request => new Promise((resolve, reject) => {
    const id = ++nextId; pending.set(id, { resolve, reject }); const url = new URL(request.url());
    bridge.stdin.write(JSON.stringify({ id, path: url.pathname, query: url.search.slice(1), method: request.method(), body: request.postData() || "" }) + "\n");
  });
}
const browser = await chromium.launch({ headless: true, ...(args["browser-path"] ? { executablePath: args["browser-path"] } : {}) });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1,
  recordVideo: { dir: output, size: { width: 1440, height: 1000 } }, acceptDownloads: true });
const page = await context.newPage();
const problems = [];
page.on("pageerror", error => problems.push(error.message));
const base = args.url || (args["static-root"] ? "http://resume-tailor.local" : "http://127.0.0.1:5174");
await page.route("**/*", async route => {
  const request = route.request();
  const url = new URL(request.url());
  if (url.origin !== new URL(base).origin) return route.abort();
  if (url.pathname === "/api/ai/deepseek/status") return route.fulfill({ json: {
    provider: "DeepSeek", configured: true, model: "已验收输出回放", config_error: null, key_exposed: false, test_sends_personal_data: false,
  } });
  if (url.pathname === "/api/ai/deepseek/test") return route.fulfill({ status: 409, json: { message: "Recording replay makes no API calls." } });
  const match = url.pathname.match(/^\/api\/jobs\/(\d+)\/agent-v1\/candidates$/);
  if (match && request.method() === "POST") {
    const entry = manifest.cases.find(item => item.job_id === Number(match[1]));
    if (!entry || request.postDataJSON().context_hash !== entry.result.context_hash) throw new Error("Replay context changed; regenerate the local manifest.");
    return route.fulfill({ json: entry.result });
  }
  if (!args["static-root"]) return route.continue();
  if (url.pathname.startsWith("/api/")) {
    const reply = await bridgeRequest(request);
    return route.fulfill({ status: reply.status, headers: reply.headers, body: Buffer.from(reply.body, "base64") });
  }
  const staticRoot = path.resolve(args["static-root"]);
  const file = path.resolve(staticRoot, "." + (url.pathname === "/" ? "/index.html" : decodeURIComponent(url.pathname)));
  if (!file.startsWith(staticRoot + path.sep)) return route.fulfill({ status: 403 });
  const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml" };
  try { return await route.fulfill({ body: await fs.readFile(file), contentType: types[path.extname(file)] || "application/octet-stream" }); }
  catch { return route.fulfill({ status: 404 }); }
});
await page.goto(base);
await page.getByRole("button", { name: "查看项目事实素材", exact: true }).waitFor();
await page.evaluate(() => {
  const banner = document.createElement("aside"); banner.id = "recording-caption";
  banner.style.cssText = "position:fixed;bottom:0;left:0;right:0;z-index:99999;padding:15px 50px 20px;background:rgba(5,7,18,.97);border-top:1px solid #9981c3;color:#fff;pointer-events:none;font-family:Microsoft YaHei,sans-serif";
  banner.innerHTML = '<div style="font-size:13px;color:#c4b3e7;margin-bottom:7px">脱敏合成数据 · 2026-09-24 已验收模型结果回放 · 本次未调用 API</div><div id="caption-title" style="font-size:25px;font-weight:600"></div><div id="caption-detail" style="font-size:17px;color:#d1cddc;margin-top:6px"></div>';
  document.body.append(banner);
});
async function caption(title, detail, milliseconds = 7000) {
  await page.evaluate(({ title, detail }) => {
    document.getElementById("caption-title").textContent = title;
    document.getElementById("caption-detail").textContent = detail;
  }, { title, detail });
  await page.waitForTimeout(milliseconds);
}
await page.screenshot({ path: path.join(output, "01-home.png") });
await caption("AI 简历适配工作台", "同一个项目，面对不同岗位，突出不同的已验证经历。", 8000);
await page.getByRole("button", { name: "查看项目事实素材", exact: true }).click();
await page.locator(".project-fact-card").first().waitFor();
await page.locator(".project-fact-card").first().scrollIntoViewIfNeeded();
await caption("先记录真实事实，再生成表达", "已验证、需要补充、计划实现、禁止写入简历：只有已确认的可写事实能参与生成。", 8000);
await page.screenshot({ path: path.join(output, "02-facts.png") });
await page.getByRole("button", { name: "← 返回主界面", exact: true }).click();
const evidence = [];
for (const entry of manifest.cases) {
  await page.locator(".job-row").filter({ hasText: entry.title }).click();
  const group = page.locator(`#job-${entry.job_id}`);
  await group.locator(".job-detail").waitFor();
  const panel = group.locator(".deepseek-candidates");
  await panel.scrollIntoViewIfNeeded();
  await panel.getByRole("button", { name: "查看将发送的内容", exact: true }).click();
  await panel.locator(".candidate-context").waitFor();
  await panel.locator(".candidate-context").scrollIntoViewIfNeeded();
  await caption(entry.title, "先检查当前 JD、可引用事实与限制；模型表达不能新增个人经历。", 8000);
  await panel.getByRole("button", { name: "确认并生成候选（调用 1 次）", exact: true }).click();
  const version = panel.locator(".candidate-version").first();
  await version.waitFor(); await version.scrollIntoViewIfNeeded();
  await caption(entry.id === "tool-automation" ? "自动化侧重点：批量处理与流程控制" : "全栈侧重点：页面、接口、存储与交付", "查看项目描述、JD 原文依据、修改原因和引用事实。本段为此前真实生成结果回放。", 10000);
  await page.screenshot({ path: path.join(output, `${entry.id}-candidates.png`) });
  await version.locator("details").first().evaluate(element => { element.open = true; });
  await version.locator("details").first().scrollIntoViewIfNeeded();
  await caption("每条描述都有可核对的来源", "展开查看原事实；岗位要求只能改变侧重点，不能被当成你的经历。", 6000);
  await version.getByRole("button", { name: "选择这个版本", exact: true }).click();
  await panel.locator(".candidate-apply-confirm").scrollIntoViewIfNeeded();
  await caption("由用户确认后再保存", "候选不会自动覆盖草稿；确认应用后只保存到当前岗位。", 6000);
  const response = page.waitForResponse(item => item.url().endsWith(`/api/jobs/${entry.job_id}/agent-v1/candidates/apply`) && item.request().method() === "POST");
  await panel.getByRole("button", { name: "确认应用候选 1", exact: true }).click();
  const applied = await response;
  if (!applied.ok()) throw new Error(`Apply failed: ${await applied.text()}`);
  const result = await applied.json();
  evidence.push({ id: entry.id, job_id: entry.job_id, draft: result.draft });
  const draft = group.locator(".tailored-draft");
  await draft.locator(".draft-preview").waitFor();
  const projects = draft.locator(".resume-section").filter({ has: page.getByRole("heading", { name: "项目经历", exact: true }) });
  await projects.scrollIntoViewIfNeeded();
  await caption("实际保存的岗位级草稿", "保留原始简历结构，替换当前岗位的项目侧重点，还可以手动编辑。", 9000);
  await page.screenshot({ path: path.join(output, `${entry.id}-draft.png`) });
  for (const label of ["导出 Word", "导出 PDF"]) {
    const downloaded = page.waitForEvent("download");
    await draft.getByRole("link", { name: label, exact: true }).click();
    const download = await downloaded;
    await download.saveAs(path.join(output, `${entry.id}.${label.endsWith("PDF") ? "pdf" : "docx"}`));
  }
  await caption("可继续编辑，并交付 Word / PDF", "两份文件均从刚刚保存的真实草稿导出；不同岗位分别保存。", 6000);
}
// Comparison is a recording-only annotation, reading drafts that were actually saved.
const stored = await Promise.all(manifest.cases.map(entry => page.evaluate(async id => {
  const response = await fetch(`/api/jobs/${id}/draft`); if (!response.ok) throw new Error("Saved draft read failed"); return response.json();
}, entry.job_id)));
await page.evaluate(({ stored, entries }) => {
  const overlay = document.createElement("div"); overlay.id = "recording-comparison";
  overlay.style.cssText = "position:fixed;inset:45px 55px 150px;z-index:99998;background:rgba(10,10,26,.98);border:1px solid #9d83bd;border-radius:20px;padding:35px 40px;color:#ede8f6;font-family:Microsoft YaHei,sans-serif";
  const title = document.createElement("h2"); title.textContent = "两个岗位，两种合理侧重点"; overlay.append(title);
  const note = document.createElement("p"); note.textContent = "演示对照：读取两个实际保存的草稿；此对照层仅用于录屏。"; note.style.color = "#baafcf"; overlay.append(note);
  const grid = document.createElement("div"); grid.style.cssText = "display:grid;grid-template-columns:1fr 1fr;gap:35px;font-size:19px;line-height:1.9";
  stored.forEach((record, index) => {
    const column = document.createElement("section"); const heading = document.createElement("h3"); heading.textContent = entries[index].title; heading.style.color = "#edcf8e"; column.append(heading);
    const draft = record.draft || record;
    for (const text of draft.sections["项目经历"]) { const paragraph = document.createElement("p"); paragraph.textContent = text; column.append(paragraph); }
    grid.append(column);
  }); overlay.append(grid); document.body.append(overlay);
}, { stored, entries: manifest.cases });
await caption("不同的是表达重点，相同的是项目事实", "自动化岗优先讲批量导入、去重和定时任务；全栈岗优先讲 React、FastAPI、SQLite 与编辑导出。", 14000);
await page.screenshot({ path: path.join(output, "07-comparison.png") });
await caption("React + TypeScript · FastAPI + SQLite · DeepSeek", "本地运行，使用自己的 API Key；项目事实、人工确认和岗位独立草稿共同约束生成。", 8000);
await fs.writeFile(path.join(output, "recording-evidence.json"), JSON.stringify({ replay: true, external_api_calls: 0, problems, cases: evidence }, null, 2));
const video = page.video();
await context.close(); await browser.close();
if (bridge) bridge.stdin.end();
console.log(`Recorded video: ${await video.path()}`);
if (problems.length) throw new Error(`Browser errors: ${problems.join("; ")}`);
