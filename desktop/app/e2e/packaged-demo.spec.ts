import { test, expect, _electron as electron, type ElectronApplication, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

const DEMO_COMMIT = "e718d4a31f9df9d74b8b74fe5f5e49b92625862b";

function requiredEnvironment(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`缺少 E2E 环境变量：${name}`);
  return path.resolve(value);
}

async function askDemoQuestion(page: Page, index: number): Promise<void> {
  await page.getByTestId(`demo-question-${index}`).click();
  await page.getByTestId("ask-button").click();
  await expect(page.getByTestId("answer-panel")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("ask-button")).toBeEnabled({ timeout: 60_000 });
}

async function openTrace(page: Page): Promise<{ steps: string[]; tools: string[] }> {
  await page.getByTestId("open-trace").click();
  const drawer = page.getByTestId("trace-drawer");
  await expect(drawer).toBeVisible();
  const steps = await drawer.getByTestId("trace-step").locator("strong").allTextContents();
  const tools = await drawer.locator('[data-testid="trace-step"][data-step-type="tool"] strong').allTextContents();
  await drawer.getByTitle("关闭证据抽屉").click();
  return { steps, tools };
}

test("打包版内置 Demo 完成问答、证据、Trace 和导出", async () => {
  const appPath = requiredEnvironment("REPOMIND_E2E_APP_PATH");
  const userDataPath = requiredEnvironment("REPOMIND_USER_DATA_PATH");
  const exportDir = requiredEnvironment("REPOMIND_E2E_EXPORT_DIR");
  const artifactDir = path.resolve(process.env.REPOMIND_E2E_ARTIFACT_DIR || "test-results/runtime");
  if (path.basename(appPath).toLowerCase() !== "repomind.exe" || !appPath.toLowerCase().includes("win-unpacked")) {
    throw new Error("E2E 只能驱动 win-unpacked/RepoMind.exe。");
  }

  fs.mkdirSync(artifactDir, { recursive: true });
  const rendererLogs: string[] = [];
  let electronApp: ElectronApplication | null = null;
  let page: Page | null = null;
  try {
    electronApp = await electron.launch({
      executablePath: appPath,
      env: {
        ...process.env,
        REPOMIND_E2E: "1",
        REPOMIND_USER_DATA_PATH: userDataPath,
        REPOMIND_E2E_EXPORT_DIR: exportDir,
        REPOMIND_LLM_API_KEY: "",
        REPOMIND_CHAT__API_KEY: "",
        REPOMIND_EMBEDDING_API_KEY: "",
        REPOMIND_EMBEDDING__API_KEY: "",
        OPENAI_API_KEY: "",
        HTTP_PROXY: "",
        HTTPS_PROXY: "",
        ALL_PROXY: "",
        NO_PROXY: "127.0.0.1,localhost",
      },
    });
    page = await electronApp.firstWindow();
    page.on("console", (message) => rendererLogs.push(`[${message.type()}] ${message.text()}`));
    page.on("pageerror", (error) => rendererLogs.push(`[pageerror] ${error.message}`));

    await expect(page.getByTestId("app-ready")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByText("无法连接后端")).toHaveCount(0);

    await page.getByTestId("open-demo").click();
    await expect(page.getByTestId("ingest-progress")).toContainText("索引完成", { timeout: 120_000 });
    await expect(page.getByTestId("current-repository")).toContainText("RepoMind 内置 Demo");
    await expect(page.getByTestId("current-repository")).toContainText(DEMO_COMMIT.slice(0, 12));
    await expect(page.getByTestId("catalog-tree").locator("button").first()).toBeVisible();

    await page.getByTestId("workspace-tab-catalog").click();
    await page.getByTestId("catalog-tree").locator("button").first().click();
    await expect(page.getByTestId("catalog-workspace")).toContainText(/repomind_demo\/app\/main\.py|仓库总览/);

    await page.getByTestId("workspace-tab-qa").click();
    await page.getByTestId("question-input").fill("GreetingService.build_message 方法是做什么的？");
    await page.getByTestId("ask-button").click();
    await expect(page.getByTestId("answer-panel")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("ask-button")).toBeEnabled({ timeout: 60_000 });
    const directTrace = await openTrace(page);
    const directSteps = directTrace.steps;
    expect(directSteps.some((step) => step.includes("route"))).toBeTruthy();
    expect(directSteps.some((step) => step.includes("retrieval"))).toBeTruthy();
    expect(directSteps.some((step) => step.includes("synthesis"))).toBeTruthy();
    expect(directTrace.tools).toHaveLength(0);

    await askDemoQuestion(page, 1);
    const securityTrace = await openTrace(page);
    expect(securityTrace.tools.filter((step) => step.includes("security_review"))).toHaveLength(1);
    expect(securityTrace.tools.some((step) => step.includes("dependency_impact"))).toBeFalsy();
    await expect(page.getByTestId("evidence-item").filter({ hasText: "repomind_demo/security_examples.py" }).first()).toBeVisible();

    await askDemoQuestion(page, 2);
    const impactTrace = await openTrace(page);
    expect(impactTrace.tools.filter((step) => step.includes("dependency_impact"))).toHaveLength(1);
    expect(impactTrace.tools.some((step) => step.includes("security_review"))).toBeFalsy();
    const evidenceButton = page.getByTestId("evidence-item").filter({ hasText: /tests\/test_greeting\.py|repomind_demo\/service\.py/ }).first();
    await expect(evidenceButton).toBeVisible();
    await evidenceButton.click();
    const evidenceDrawer = page.getByTestId("evidence-drawer");
    await expect(evidenceDrawer).toContainText(/tests\/test_greeting\.py|repomind_demo\/service\.py/);
    await expect(evidenceDrawer).toContainText(/行 \d+ - \d+/);
    await evidenceDrawer.getByTitle("关闭证据抽屉").click();

    await page.getByTestId("export-trace-json").click();
    await expect(page.getByTestId("export-status")).toContainText("已导出");

    await page.getByTestId("workspace-tab-workflow").click();
    await page.getByTestId("run-workflow").click();
    await expect(page.getByTestId("workflow-report")).toBeVisible({ timeout: 60_000 });
    await page.getByTestId("export-markdown").click();
    await expect(page.getByTestId("export-status")).toContainText("已导出");

    const exported = fs.readdirSync(exportDir);
    const jsonName = exported.find((name) => name.endsWith(".json"));
    const markdownName = exported.find((name) => name.endsWith(".md"));
    expect(jsonName).toBeTruthy();
    expect(markdownName).toBeTruthy();

    const tracePayload = JSON.parse(fs.readFileSync(path.join(exportDir, jsonName!), "utf8"));
    expect(tracePayload.format).toBe("repomind-trace-export-v1");
    expect(tracePayload.repository.commit).toBe(DEMO_COMMIT);
    expect(tracePayload.repository.snapshot_id).toBeTruthy();
    expect(tracePayload.generation_mode).toBe("rule_fallback");
    expect(tracePayload.tool_route).toEqual([{ name: "dependency_impact", status: "succeeded" }]);
    expect(tracePayload.evidence.some((item: { file_path?: string; start_line?: number }) => item.file_path && item.start_line)).toBeTruthy();

    const markdown = fs.readFileSync(path.join(exportDir, markdownName!), "utf8");
    expect(markdown).toContain("## Export metadata");
    expect(markdown).toContain("Snapshot:");
    expect(markdown).not.toContain(userDataPath);
    expect(markdown).not.toMatch(/repomind\.sqlite3|api[_-]?key\s*[:=]\s*\S+/i);
  } finally {
    fs.writeFileSync(path.join(artifactDir, "renderer-console.txt"), rendererLogs.join("\n"), "utf8");
    // 先通过正式桌面桥接关闭后端，避免 PyInstaller 子进程占住 Playwright worker。
    if (page && !page.isClosed()) {
      await Promise.race([
        page.evaluate(async () => {
          const bridge = (window as Window & { repomind?: { backend?: { stop?: () => Promise<unknown> } } }).repomind;
          await bridge?.backend?.stop?.();
        }).catch(() => undefined),
        new Promise((resolve) => setTimeout(resolve, 10_000)),
      ]);
    }
    await Promise.race([
      electronApp?.close().catch(() => undefined),
      new Promise((resolve) => setTimeout(resolve, 10_000)),
    ]);
  }
});
