import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8000";
const QA_EMAIL = process.env.QA_EMAIL;
const QA_PASSWORD = process.env.QA_PASSWORD;
if (!QA_EMAIL || !QA_PASSWORD) {
  throw new Error("Set QA_EMAIL and QA_PASSWORD environment variables before running QA.");
}
const shotDir = new URL("./screenshots/", import.meta.url).pathname.replace(/^\//, "");
fs.mkdirSync(shotDir, { recursive: true });

const errors = [];
let expectedDuplicate = false;
let step = 0;
function log(message) {
  console.log("[" + String(++step).padStart(2, "0") + "] " + message);
}
function assert(condition, message) {
  if (!condition) throw new Error("ASSERTION FAILED: " + message);
  console.log("     ✓ " + message);
}
async function shot(page, name) {
  await page.screenshot({ path: shotDir + name + ".png", fullPage: false });
}

async function login(page) {
  await page.goto(BASE + "/login", { waitUntil: "networkidle" });
  await page.fill('input[type="email"]', QA_EMAIL);
  await page.fill('input[type="password"]', QA_PASSWORD);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.waitForURL("**/app", { timeout: 20000 });
  await page.waitForSelector(".home-head", { timeout: 20000 });
  const skip = page.getByRole("button", { name: "跳过引导" });
  if (await skip.count()) {
    await skip.click();
    await page.waitForTimeout(500);
  }
}

const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const page = await context.newPage();
page.on("console", (message) => {
  if (message.type() === "error" && !message.text().includes("409")) errors.push("console: " + message.text());
});
page.on("pageerror", (error) => errors.push("pageerror: " + error.message));
page.on("response", (response) => {
  if (response.status() >= 400 && !(response.status() === 409 && response.url().endsWith("/api/knowledge"))) errors.push("http " + response.status() + ": " + response.url());
});

try {
  log("Landing page");
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  await page.waitForSelector(".hero-copy h1");
  await shot(page, "01-landing");
  assert((await page.textContent(".hero-copy h1")).includes("读懂论文"), "hero headline renders");

  log("Login flow");
  await page.goto(BASE + "/login", { waitUntil: "networkidle" });
  await page.waitForSelector(".auth-card");
  await shot(page, "01b-login");
  await login(page);
  await shot(page, "02-home-empty");
  assert(await page.locator(".home-head h1").innerText(), "home greeting present");
  assert((await page.locator(".rail-papers li").count()) >= 2, "library papers listed in rail");

  log("Research agent chat");
  const composer = page.locator(".composer textarea");
  await composer.fill("这篇论文的核心贡献是什么？");
  await composer.press("Enter");
  await page.waitForSelector(".msg-assistant .markdown", { timeout: 30000 });
  await page.waitForSelector(".source-card", { timeout: 60000 });
  await page.waitForFunction(() => {
    const button = document.querySelector(".composer-right .btn");
    return button && button.textContent.includes("发送");
  }, { timeout: 60000 });
  const answer = await page.locator(".msg-assistant .markdown").last().innerText();
  assert(answer.length > 40, "assistant produced a grounded answer");
  assert((await page.locator(".source-card").count()) >= 1, "citations rendered");
  if ((await page.locator(".timeline-step").count()) === 0) {
    await page.locator(".timeline-head").first().click();
    await page.waitForTimeout(200);
  }
  assert((await page.locator(".timeline-step").count()) >= 1, "agent tool timeline visible");
  await shot(page, "03-chat-answer");

  log("Evidence drawer from chat answer");
  await page.locator(".evidence-open").first().click();
  await page.waitForSelector(".ev-drawer", { timeout: 15000 });
  await page.waitForSelector(".ev-card", { timeout: 20000 });
  const drawerCards = await page.locator(".ev-card").count();
  assert(drawerCards >= 1, "chat answer exposes evidence records (" + drawerCards + ")");
  assert((await page.locator(".ev-verified.ok").count()) >= 1, "at least one evidence item is verified");
  await page.waitForTimeout(500);
  await shot(page, "03b-evidence-drawer");
  await page.getByRole("button", { name: "关闭证据视图" }).click();
  await page.waitForTimeout(300);

  log("Library page");
  await page.getByRole("link", { name: "论文阅读" }).click();
  await page.waitForSelector(".paper-grid");
  await page.waitForSelector(".paper-card");
  await shot(page, "04-library");
  assert((await page.locator(".paper-card").count()) >= 2, "paper cards render");

  log("Reader with persisted annotations");
  await page.locator(".paper-title").first().click();
  await page.waitForURL("**/app/papers/**", { timeout: 20000 });
  await page.waitForSelector(".pdf-page canvas", { timeout: 30000 });
  await page.waitForTimeout(2500);
  await shot(page, "05-reader");
  const highlights = await page.locator(".highlight").count();
  assert(highlights >= 1, "persisted highlights rendered on PDF (" + highlights + ")");
  assert((await page.locator(".outline-item").count()) >= 3, "section outline rendered");

  log("Create a highlight from a real text selection");
  const beforeCount = await page.locator(".highlight").count();
  await page.locator('.pdf-page[data-page="2"]').scrollIntoViewIfNeeded();
  await page.waitForTimeout(900);
  await page.evaluate(() => {
    const layers = Array.from(document.querySelectorAll(".text-layer"));
    const layer = layers.find((item) => {
      const page = item.closest(".pdf-page");
      return page && page.dataset.page === "2" && item.querySelectorAll("span").length > 4;
    }) || layers[1] || layers[0];
    const spans = Array.from(layer.querySelectorAll("span")).filter((span) => {
      const rect = span.getBoundingClientRect();
      return span.textContent.trim().length > 20 && rect.top > 90 && rect.bottom < window.innerHeight - 140;
    });
    const target = spans[1] || spans[0];
    if (!target) return;
    const range = document.createRange();
    range.selectNodeContents(target);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    target.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  });
  await page.waitForSelector(".selection-toolbar", { timeout: 10000 });
  await page.locator(".toolbar-color").nth(2).click();
  await page.waitForTimeout(1500);
  const afterCount = await page.locator(".highlight").count();
  assert(afterCount > beforeCount, "new highlight saved from text selection (" + beforeCount + " → " + afterCount + ")");
  await shot(page, "05b-reader-highlight");

  log("Highlight survives a full reload");
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector(".pdf-page canvas", { timeout: 30000 });
  await page.waitForTimeout(2800);
  const reloadedCount = await page.locator(".highlight").count();
  assert(reloadedCount >= afterCount, "highlights restored after reload (" + reloadedCount + ")");

  log("Annotation joins the evidence library");
  await page.getByRole("tab", { name: /批注/ }).click();
  await page.locator(".annotation-main").first().click();
  await page.waitForSelector(".annotation-editor");
  await page.getByRole("button", { name: "加入证据库" }).click();
  await page.waitForSelector(".ev-drawer", { timeout: 15000 });
  await page.waitForSelector(".ev-card", { timeout: 15000 });
  assert((await page.locator(".ev-card").count()) >= 1, "annotation evidence drawer opens");
  await page.waitForTimeout(500);
  await shot(page, "05c-annotation-evidence");
  await page.getByRole("button", { name: "关闭证据视图" }).click();
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);

  log("Reader summary");
  await page.getByRole("button", { name: "方法", exact: true }).first().click();
  await page.waitForSelector(".summary-output", { timeout: 30000 });
  await page.waitForFunction(() => !document.querySelector(".ai-loading"), { timeout: 30000 });
  const summary = await page.locator(".summary-output .markdown").innerText();
  assert(summary.length > 40, "summary generated in reader");
  await shot(page, "06-reader-summary");

  log("Evidence drawer from summary");
  await page.locator(".summary-actions button").filter({ hasText: "证据" }).first().click();
  await page.waitForSelector(".ev-drawer", { timeout: 15000 });
  await page.waitForSelector(".ev-card", { timeout: 15000 });
  assert((await page.locator(".ev-card").count()) >= 1, "summary exposes evidence records");
  await page.waitForTimeout(500);
  await shot(page, "06c-summary-evidence");
  await page.getByRole("button", { name: "关闭证据视图" }).click();
  await page.waitForTimeout(300);

  log("Critical review in reader");
  await page.getByRole("button", { name: "批判性评估" }).click();
  await page.waitForFunction(() => {
    const output = document.querySelector(".summary-output");
    return output && output.textContent && output.textContent.length > 80 && !document.querySelector(".ai-loading");
  }, { timeout: 40000 });
  const critical = await page.locator(".summary-output").innerText();
  assert(critical.includes("批判") || critical.includes("研究问题"), "critical review rendered");
  await shot(page, "06b-reader-critical");

  log("Export a real file");
  await page.getByRole("button", { name: "导出", exact: true }).first().click();
  await page.waitForSelector(".export-formats");
  await page.locator(".export-format", { hasText: "DOCX" }).click();
  const downloadPromise = page.waitForEvent("download", { timeout: 60000 });
  await page.getByRole("button", { name: "生成并下载" }).click();
  const download = await downloadPromise;
  const path = await download.path();
  const size = fs.statSync(path).size;
  assert(size > 1000, "DOCX export downloaded (" + size + " bytes)");
  await page.waitForTimeout(500);

  log("Multi-paper comparison");
  await page.goto(BASE + "/app/research", { waitUntil: "networkidle" });
  await page.waitForSelector(".research-paper");
  await page.locator(".research-paper").nth(0).click();
  await page.locator(".research-paper").nth(1).click();
  await page.getByRole("button", { name: "开始对比" }).click();
  await page.waitForSelector(".research-result", { timeout: 60000 });
  const comparison = await page.locator(".research-result .markdown").innerText();
  assert(comparison.length > 60, "comparison report generated");
  assert((await page.locator(".result-source").count()) >= 2, "comparison carries sources");
  await shot(page, "07-research-compare");

  log("Evidence matrix");
  await page.getByRole("tab", { name: "证据矩阵" }).click();
  await page.waitForSelector(".research-paper");
  await page.getByRole("button", { name: "生成矩阵" }).click();
  await page.waitForSelector(".matrix-table", { timeout: 60000 });
  await page.waitForSelector(".matrix-cell", { timeout: 20000 });
  assert((await page.locator(".matrix-table tbody tr").count()) === 2, "matrix contains one row per paper");
  assert((await page.locator(".matrix-cell").count()) >= 6, "matrix cells carry evidence-backed facets");
  await shot(page, "07d-evidence-matrix");

  log("Conflict detection (local honesty)");
  await page.getByRole("tab", { name: "观点冲突" }).click();
  await page.getByRole("button", { name: "检测冲突" }).click();
  await page.waitForSelector(".comparability-card", { timeout: 60000 });
  const conflictNote = await page.locator(".p4-panel .p4-note").first().innerText();
  assert(conflictNote.includes("不判定"), "local mode does not invent conflicts");
  await shot(page, "07e-conflicts");

  log("Method evolution timeline");
  await page.getByRole("tab", { name: "方法演化" }).click();
  await page.getByRole("button", { name: "生成时间线" }).click();
  await page.waitForSelector(".evo-timeline", { timeout: 60000 });
  assert((await page.locator(".evo-paper").count()) >= 2, "evolution timeline lists papers");
  await shot(page, "07f-evolution");

  log("Research gap analysis");
  await page.getByRole("tab", { name: "研究缺口" }).click();
  await page.waitForSelector(".research-paper");
  const clearSelection = page.getByRole("button", { name: "清空", exact: true });
  if (await clearSelection.count()) await clearSelection.click();
  await page.locator(".research-paper").nth(0).click();
  await page.locator(".research-paper").nth(1).click();
  await page.getByRole("button", { name: "分析研究缺口" }).click();
  await page.waitForSelector(".research-result", { timeout: 60000 });
  const gapText = await page.locator(".research-result .markdown").innerText();
  assert(gapText.length > 80, "research gap report generated");
  await shot(page, "07c-research-gap");

  log("Cross-paper gap validation");
  await page.locator(".gap-validation-input input").fill("section-aware chunking improves faithfulness");
  await page.getByRole("button", { name: "验证", exact: true }).click();
  await page.waitForSelector(".gap-validation-result", { timeout: 30000 });
  assert((await page.locator(".gap-support").count()) >= 1, "gap validation finds supporting papers");
  await shot(page, "07g-gap-validation");

  log("Fragment comparison");
  await page.getByRole("tab", { name: /片段对比/ }).click();
  await page.waitForSelector(".fragment-paper");
  await page.locator(".fragment-paper").nth(0).click();
  await page.waitForSelector(".chunk-picker-item");
  await page.locator(".chunk-picker-item").first().click();
  await page.waitForTimeout(300);
  await page.locator(".fragment-paper").nth(1).click();
  await page.waitForSelector(".chunk-picker-item");
  await page.locator(".chunk-picker-item").nth(1).click();
  await page.waitForTimeout(300);
  await page.getByRole("button", { name: "比较这些片段" }).click();
  await page.waitForSelector(".research-result", { timeout: 60000 });
  assert((await page.locator(".fragment-item").count()) >= 2, "two fragments selected for comparison");
  await shot(page, "07b-fragment-compare");

  log("Knowledge base and graph");
  await page.getByRole("link", { name: "个人知识库" }).click();
  await page.waitForSelector(".knowledge-card");
  await shot(page, "08-knowledge");
  await page.getByRole("button", { name: "图谱视图" }).click();
  await page.waitForSelector(".graph-svg", { timeout: 20000 });
  await shot(page, "09-knowledge-graph");
  assert((await page.locator(".graph-node").count()) >= 2, "knowledge graph nodes render");

  log("Knowledge intelligence");
  await page.getByRole("button", { name: "卡片视图" }).click();
  const knowledgeTitle = "P7 知识测试 " + Date.now();
  const knowledgeContent = "unique knowledge note " + knowledgeTitle + " evidence token " + Math.random().toString(36).slice(2);
  await page.getByRole("button", { name: "新建知识" }).click();
  await page.waitForSelector(".knowledge-editor");
  await page.locator(".knowledge-editor input").first().fill(knowledgeTitle);
  await page.locator(".knowledge-editor textarea").fill(knowledgeContent);
  await page.locator(".modal-root").getByRole("button", { name: "保存", exact: true }).click();
  await page.waitForSelector(".modal-root", { state: "detached", timeout: 20000 });
  await page.waitForSelector(".auto-tags", { timeout: 20000 });
  assert((await page.locator(".auto-tags").first().innerText()).length > 0, "auto tags generated on save");

  await page.getByRole("button", { name: "新建知识" }).click();
  await page.waitForSelector(".knowledge-editor");
  await page.locator(".knowledge-editor input").first().fill(knowledgeTitle);
  await page.locator(".knowledge-editor textarea").fill(knowledgeContent);
  expectedDuplicate = true;
  await page.locator(".modal-root").last().getByRole("button", { name: "保存", exact: true }).click();
  await page.waitForSelector(".duplicate-panel", { timeout: 20000 });
  assert((await page.locator(".duplicate-panel").innerText()).includes("相似度"), "duplicate content is blocked with similarity");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(500);
  expectedDuplicate = false;
  assert((await page.locator(".modal-root").count()) === 0, "duplicate dialog closes without creating an entry");

  await page.locator(".filter-search input").fill(knowledgeTitle);
  await page.waitForTimeout(800);
  assert((await page.locator(".knowledge-card").count()) >= 1, "hybrid search retrieves knowledge");
  assert((await page.locator(".knowledge-card").first().innerText()).includes("P7 知识测试"), "hybrid search hits the right note");
  await shot(page, "09g-knowledge-intelligence");

  await page.locator(".filter-search input").fill("");
  await page.waitForTimeout(300);
  const versionButton = page.getByRole("button", { name: "版本历史" }).first();
  if (await versionButton.count()) {
    await versionButton.click();
    await page.waitForSelector(".version-card", { timeout: 15000 });
    assert((await page.locator(".version-card").count()) >= 1, "knowledge version history opens");
    await page.keyboard.press("Escape");
  }
  assert((await page.locator(".cluster-chips .filter-chip").count()) >= 2, "knowledge clusters render");

  await page.getByRole("button", { name: "相似条目" }).click();
  await page.waitForSelector(".modal-root");
  await page.waitForTimeout(300);
  await shot(page, "09h-knowledge-duplicates");
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "图谱视图" }).click();
  await page.waitForSelector(".graph-svg", { timeout: 20000 });
  assert((await page.locator(".node-tag").count()) >= 1, "knowledge graph exposes tag nodes");
  await shot(page, "09i-knowledge-graph");

  log("Evidence library");
  await page.getByRole("link", { name: "证据库" }).click();
  await page.waitForSelector(".evidence-row", { timeout: 20000 });
  await page.waitForSelector(".evidence-stat");
  const evidenceRows = await page.locator(".evidence-row").count();
  assert(evidenceRows >= 3, "evidence library lists persisted evidence (" + evidenceRows + ")");
  await shot(page, "09b-evidence-library");
  const directFilter = page.locator(".evidence-toolbar .filter-chip").filter({ hasText: "原文" });
  if (await directFilter.count()) {
    await directFilter.first().click();
    await page.waitForTimeout(500);
    assert((await page.locator(".evidence-row").count()) >= 1, "evidence type filter works");
  }

  log("Research Intelligence landscape");
  await page.getByRole("link", { name: "研究情报" }).click();
  await page.waitForSelector(".intel-scope-bar");
  await page.getByRole("button", { name: "生成研究情报" }).click();
  await page.waitForSelector(".intel-overview-card", { timeout: 60000 });
  const boundary = await page.locator(".intel-boundary").innerText();
  assert(boundary.includes("资料库"), "intelligence states its data boundary");
  assert((await page.locator(".intel-item-list li").count()) >= 2, "landscape lists evidence-backed items");
  await shot(page, "08b-intelligence-landscape");

  log("Research Intelligence trends");
  await page.getByRole("tab", { name: "研究趋势" }).click();
  await page.waitForSelector(".year-bar", { timeout: 20000 });
  assert((await page.locator(".year-bar").count()) >= 1, "trends use real publication years");
  await shot(page, "08c-intelligence-trends");

  log("Research Intelligence connections");
  await page.getByRole("tab", { name: "知识关联" }).click();
  await page.waitForSelector(".connection-svg", { timeout: 30000 });
  assert((await page.locator(".connection-node").count()) >= 5, "connections graph renders real nodes");
  await page.locator(".connection-node").first().click();
  await page.waitForTimeout(400);
  await shot(page, "08d-intelligence-connections");

  log("Research Intelligence opportunities");
  await page.getByRole("tab", { name: "研究机会" }).click();
  await page.waitForSelector(".opportunity-card", { timeout: 20000 });
  assert((await page.locator(".opportunity-card").count()) >= 1, "opportunities are labelled suggestions");
  await page.waitForTimeout(300);
  await shot(page, "08e-intelligence-opportunities");

  log("Agent plan preview");
  await page.goto(BASE + "/app", { waitUntil: "networkidle" });
  await page.waitForSelector(".home-head");
  await page.locator(".composer textarea").fill("对比这两篇论文的方法与实验条件");
  await page.locator(".composer textarea").press("Enter");
  await page.waitForSelector(".plan-card", { timeout: 30000 });
  assert((await page.locator(".plan-step").count()) >= 4, "plan preview lists steps");
  await shot(page, "09c-task-plan");

  await page.getByRole("button", { name: "调整步骤" }).click();
  await page.locator(".plan-editor textarea").fill("确认范围与目标（已调整）\n检索原文证据\n组织答案并标注证据\n执行证据自检");
  await page.getByRole("button", { name: "保存计划" }).click();
  await page.waitForTimeout(400);
  assert((await page.locator(".plan-step").first().innerText()).includes("已调整"), "plan can be edited by the user");

  await page.getByRole("button", { name: "执行计划" }).click();
  await page.waitForSelector(".self-check", { timeout: 60000 });
  assert((await page.locator(".msg-assistant .markdown").last().innerText()).length > 40, "plan execution produced an answer");
  await shot(page, "09d-task-result");

  log("Task center");
  await page.getByRole("link", { name: "任务中心" }).click();
  await page.waitForSelector(".task-list-item", { timeout: 30000 });
  await page.waitForSelector(".task-detail", { timeout: 20000 });
  assert((await page.locator(".task-plan-row").count()) >= 4, "task center shows the saved plan");
  await shot(page, "09e-task-center");

  log("Cancel plan preview");
  await page.goto(BASE + "/app", { waitUntil: "networkidle" });
  await page.locator(".composer textarea").fill("生成研究情报与趋势");
  await page.locator(".composer textarea").press("Enter");
  await page.waitForSelector(".plan-card", { timeout: 30000 });
  await page.getByRole("button", { name: "取消任务" }).click();
  await page.waitForSelector(".plan-cancelled", { timeout: 10000 });
  assert((await page.locator(".msg-assistant").last().innerText()).includes("已取消"), "cancelled plan shows a cancellation state");
  await shot(page, "09f-task-cancelled");

  log("Academic artifacts");
  await page.getByRole("link", { name: "学术成果" }).click();
  await page.waitForSelector(".artifact-kind-card", { timeout: 30000 });
  const reviewCard = page.locator(".artifact-kind-card").filter({ hasText: "文献综述" });
  await reviewCard.getByRole("button", { name: "生成", exact: true }).click();
  await page.waitForSelector(".artifact-preview", { timeout: 60000 });
  await page.waitForSelector(".artifact-evidence tbody tr", { timeout: 30000 });
  assert((await page.locator(".artifact-evidence tbody tr").count()) >= 1, "artifact carries an evidence table");
  assert((await page.locator(".artifact-quality .artifact-issue").count()) >= 1, "quality checker lists issues");
  assert((await page.locator(".artifact-preview").innerText()).includes("仅基于资料库"), "artifact declares its scope");
  await shot(page, "09j-academic-artifact");

  const designCard = page.locator(".artifact-kind-card").filter({ hasText: "实验设计" });
  await designCard.getByRole("button", { name: "生成", exact: true }).click();
  await page.waitForFunction(() => document.querySelector(".artifact-preview h2")?.textContent?.includes("实验设计"), { timeout: 60000 });
  assert((await page.locator(".artifact-preview").innerText()).includes("消融"), "experiment design artifact generated");

  const [artifactDownload] = await Promise.all([
    page.waitForEvent("download", { timeout: 30000 }),
    page.getByRole("button", { name: "MD", exact: true }).click(),
  ]);
  assert(Boolean(await artifactDownload.path()), "artifact exports a real Markdown file");
  await page.locator(".artifact-quality").scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  await shot(page, "09k-artifact-quality");

  log("Figures page");
  await page.getByRole("link", { name: "图片与图表" }).click();
  await page.waitForSelector(".figure-grid");
  await page.waitForTimeout(1200);
  await shot(page, "10-figures");

  log("Projects page");
  await page.getByRole("link", { name: "研究项目" }).click();
  await page.waitForSelector(".project-card");
  await page.locator(".project-card").first().click();
  await page.waitForSelector(".project-head-card");
  await shot(page, "11-projects");

  log("History page");
  await page.getByRole("link", { name: "历史记录" }).click();
  await page.waitForSelector(".history-item");
  await shot(page, "12-history");

  log("Settings and model configuration");
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await page.waitForSelector(".settings-card");
  await page.getByRole("button", { name: "AI 模型配置" }).click();
  await page.waitForSelector(".model-status");
  await shot(page, "13-settings-model");

  log("Dark theme");
  const darkButton = page.getByRole("button", { name: "切换到深色" });
  if (await darkButton.count()) {
    await darkButton.click();
    await page.waitForTimeout(700);
  }
  await page.goto(BASE + "/app", { waitUntil: "networkidle" });
  await page.waitForSelector(".home-head");
  await shot(page, "14-home-dark");
  assert((await page.getAttribute("html", "data-theme")) === "dark", "dark theme applied");
  await page.getByRole("button", { name: "切换到浅色" }).click();
  await page.waitForTimeout(500);

  log("Confirmable write action");
  await page.goto(BASE + "/app", { waitUntil: "networkidle" });
  await page.waitForSelector(".home-head");
  const composer2 = page.locator(".composer textarea");
  await composer2.fill("把这篇论文的核心结论保存到知识库");
  await composer2.press("Enter");
  await page.waitForSelector(".action-card", { timeout: 60000 });
  await page.getByRole("button", { name: "确认并执行" }).click();
  await page.waitForSelector(".action-done", { timeout: 20000 });
  assert(true, "write action required confirmation and executed");
  await shot(page, "14b-action-confirmed");

  log("Mobile layout");
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const mobilePage = await mobile.newPage();
  mobilePage.on("pageerror", (error) => errors.push("mobile pageerror: " + error.message));
  await login(mobilePage);
  await shot(mobilePage, "15-mobile-home");
  await mobilePage.getByRole("button", { name: "打开导航" }).click();
  await page.waitForTimeout(400);
  await shot(mobilePage, "16-mobile-nav");
  await mobilePage.getByRole("link", { name: "论文阅读" }).click();
  await mobilePage.waitForSelector(".paper-card");
  await mobilePage.waitForTimeout(700);
  await shot(mobilePage, "17-mobile-library");
  assert((await mobilePage.locator(".paper-card").count()) >= 1, "mobile library renders");

  console.log("\nSCREENSHOTS:", fs.readdirSync(shotDir).join(", "));
  if (errors.length) {
    console.log("\nBROWSER ERRORS (" + errors.length + "):");
    errors.forEach((error) => console.log(" - " + error));
  } else {
    console.log("\nNo browser console/page errors.");
  }
  console.log("\nBROWSER QA PASSED");
} catch (error) {
  console.error("\nBROWSER QA FAILED:", error.message);
  await page.screenshot({ path: shotDir + "failure.png", fullPage: true }).catch(() => {});
  if (errors.length) errors.forEach((item) => console.log(" - " + item));
  process.exitCode = 1;
} finally {
  await browser.close();
}