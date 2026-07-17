import { describe, expect, it } from "vitest";

import { buildBoundedTraceExport, redactExportData, redactExportText, saveTextExport } from "./exportRedaction";

describe("导出脱敏", () => {
  it("Trace JSON 移除密钥、用户数据和数据库绝对路径，保留相对证据引用", () => {
    const result = redactExportData({
      userDataPath: "C:\\Users\\alice\\AppData\\Roaming\\repomind",
      database_path: "C:\\Users\\alice\\AppData\\Roaming\\repomind\\repomind.sqlite3",
      repo_path: "C:\\projects\\private-repo",
      api_key: "super-secret-key",
      url: "https://example.test/search?q=hello&api_key=secret&token=abc",
      evidence: { file_path: "src/main.ts", snippet: "relative path is useful" },
    }) as Record<string, unknown>;

    expect(result.userDataPath).toBe("[redacted]");
    expect(result.database_path).toBe("[redacted]");
    expect(result.repo_path).toBe("[local path]");
    expect(result.api_key).toBe("[redacted]");
    expect(result.url).toBe("https://example.test/search?q=hello");
    expect((result.evidence as Record<string, unknown>).file_path).toBe("src/main.ts");
  });

  it("Markdown 使用相同规则，移除任意 Unix 本地路径、URL fragment 与凭据而保留相对引用", () => {
    const result = redactExportText(
      "Path: /srv/repomind/private/report.json\nFile: src/main.ts\n"
      + "URL: https://x.test/a?token=abc&mode=read#access_token=fragment-secret",
    );

    expect(result).not.toContain("/srv/repomind/private/report.json");
    expect(result).toContain("src/main.ts");
    expect(result).toContain("https://x.test/a?mode=read");
    expect(result).not.toContain("token=abc");
    expect(result).not.toContain("fragment-secret");
    expect(result).not.toContain("#");
  });

  it("完整遮挡 Authorization Bearer/Basic 与已知 webhook 路径凭据", () => {
    const result = redactExportText(
      "Authorization: Bearer eyJhbGciOi.secret/value==\n"
      + "authorization=Basic dXNlcjpwQHNzL3dvcmQ=\n"
      + "Slack https://hooks.slack.com/services/T00000000/B00000000/abcDEF123\n"
      + "Discord https://discord.com/api/webhooks/123456789/secret-token\n"
      + "Evidence https://example.test/repos/org/project/blob/main/src/auth.ts",
    );

    expect(result).toContain("Authorization: Bearer [redacted]");
    expect(result).toContain("authorization=Basic [redacted]");
    expect(result).toContain("https://hooks.slack.com/services/[redacted]");
    expect(result).toContain("https://discord.com/api/webhooks/[redacted]");
    expect(result).toContain("https://example.test/repos/org/project/blob/main/src/auth.ts");
    expect(result).not.toContain("eyJhbGciOi");
    expect(result).not.toContain("dXNlcjpwQHNz");
    expect(result).not.toContain("T00000000");
    expect(result).not.toContain("123456789");
  });

  it("完整遮挡带空格的 Windows 与 UNC 绝对路径", () => {
    const result = redactExportText(
      'Repo "C:\\Users\\Alice Smith\\Private Repo\\report.json"\n'
      + 'UNC "\\\\server name\\private share\\folder\\data.db"\n'
      + 'Field: C:\\Users\\Alice Smith\\Private Repo\\trace.json; status=ok',
    );

    expect(result).not.toContain("Alice Smith");
    expect(result).not.toContain("server name");
    expect(result).not.toContain("Private Repo");
    expect(result.match(/\[local path\]/g)?.length).toBe(3);
    expect(result).toContain("status=ok");
  });

  it("超大 Trace 使用有界 schema 并明确标记截断", () => {
    const huge = "x".repeat(100_000);
    const trace = {
      id: "trace-1", repo_id: "repo-1", snapshot_id: "snapshot-1", session_id: null,
      entrypoint: "ask", question: huge, mode: "agent", status: "succeeded" as const,
      planner_version: "1", final_answer: huge, confidence: "high", token_count: 1,
      error: null, created_at: "2026-01-01", completed_at: "2026-01-01",
      steps: Array.from({ length: 250 }, (_, index) => ({
        id: `step-${index}`, trace_id: "trace-1", step_no: index, step_type: "tool", tool_name: "read",
        status: "succeeded" as const, input: { prompt: huge, nested: { secret: huge } },
        output_summary: { summary: huge }, evidence_refs: Array.from({ length: 60 }, () => ({
          chunk_id: huge, file_path: "C:\\Users\\Alice Smith\\Private Repo\\file.py",
        })), token_count: 1, duration_ms: 1, error: huge, created_at: "2026-01-01", completed_at: "2026-01-01",
      })),
    };

    const payload = buildBoundedTraceExport(trace, { alias: "repo", commit: "a".repeat(40), snapshot_id: "snapshot-1" });
    const serialized = JSON.stringify(payload);
    const tracePayload = payload.trace as { steps: Array<{ evidence_refs?: unknown[] }>; question: string; final_answer: string };
    const retainedEvidence = (payload.evidence as unknown[]).length;

    expect(new TextEncoder().encode(serialized).byteLength).toBeLessThan(10 * 1024 * 1024);
    expect(tracePayload.steps).toHaveLength(40);
    expect(retainedEvidence).toBe(100);
    expect(tracePayload.question).toContain("[truncated]");
    expect(tracePayload.final_answer).toContain("[truncated]");
    expect(payload.truncation).toMatchObject({
      steps_truncated: true,
      omitted_steps: 250 - tracePayload.steps.length,
      evidence_truncated: true,
      evidence_per_step_truncated: true,
      omitted_evidence: 250 * 60 - retainedEvidence,
    });
    expect(serialized).not.toContain("Alice Smith");
    expect(serialized).not.toContain('"nested":{"secret"');
  });

  it("保存桥成功时返回保存的文件名", async () => {
    await expect(saveTextExport(
      async () => ({ saved: true, fileName: "report.md" }),
      { suggestedName: "report", content: "content", kind: "markdown" },
    )).resolves.toEqual({ status: "saved", fileName: "report.md" });
  });

  it("保存桥取消时明确返回 cancelled", async () => {
    await expect(saveTextExport(
      async () => ({ saved: false }),
      { suggestedName: "report", content: "content", kind: "markdown" },
    )).resolves.toEqual({ status: "cancelled" });
  });

  it("保存桥拒绝时返回可显示的失败原因", async () => {
    await expect(saveTextExport(
      async () => { throw new Error("disk full"); },
      { suggestedName: "report", content: "content", kind: "markdown" },
    )).resolves.toEqual({ status: "failed", error: "disk full" });
  });
});
