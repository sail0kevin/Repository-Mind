import { describe, expect, it, vi } from "vitest";
import { loadWorkflowReportRepository } from "./repositoryRegistration";

describe("repository registration flows", () => {
  it("loads an existing workflow report without ingesting", async () => {
    const calls: string[] = [];
    const response = { response_type: "workflow_report" as const, repo: { repo_id: "repo" }, sections: [{ key: "summary" }], snapshot_id: "snap" };
    await loadWorkflowReportRepository(response, {
      setWorkflowReport: vi.fn(), setActiveWorkflowSection: vi.fn(),
      loadRepository: async () => { calls.push("load"); }, refreshRepositoryInsights: async () => { calls.push("insights"); },
      loadRepositoryKnowledge: async () => { calls.push("knowledge"); }, setRegisterProgress: vi.fn(),
    });
    expect(calls).toEqual(["load", "insights", "knowledge"]);
  });
});
