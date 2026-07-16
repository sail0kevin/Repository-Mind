import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getCallChain,
  getClassHierarchy,
  getCodeGraphStats,
  getHealth,
  getImportantFunctions,
  getRepositoryCatalogItem,
  getRepositoryCatalogTree,
  getRepositoryChunkDetail,
  getRepositoryFileDetail,
  getRepositoryFiles,
  getRepositorySnapshot,
  getRepositoryTrace,
  jobProgressPercent,
  listEvidence,
  listParserDiagnostics,
  listRelations,
  listRepositoryCatalog,
  listSymbols,
  listRepositories,
  listRepositorySnapshots,
  parseApiError,
  refreshRepository,
  runCollaboration,
  searchCodeFunctions,
  searchRepository,
  setApiBaseUrl,
  updateSettings,
} from "./apiClient";

// 用最小 Response 替身记录真实 fetch 参数，不依赖后端进程。
function mockSuccessfulFetch(payload: unknown = {}) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: async () => payload,
  } as Response);
}

afterEach(() => {
  setApiBaseUrl("http://127.0.0.1:8000/api/v1");
});

describe("HTTP 请求头契约", () => {
  it("GET 健康检查不发送 JSON Content-Type", async () => {
    const fetchMock = mockSuccessfulFetch({ status: "ok" });

    await getHealth();

    const options = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(options.headers);
    expect(headers.has("Content-Type")).toBe(false);
  });

  it("携带 JSON 请求体时发送 Content-Type", async () => {
    const fetchMock = mockSuccessfulFetch({ evidence: [] });

    await searchRepository("repo-1", "入口");

    const options = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(options.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(options.body).toBe(JSON.stringify({ query: "入口" }));
  });
});

describe("parseApiError", () => {
  it("读取项目统一的 FastAPI error.message", () => {
    expect(parseApiError(404, JSON.stringify({
      error: { code: "repo_not_found", message: "没有找到指定仓库。", trace_id: "trace-1" },
    }))).toBe("没有找到指定仓库。");
  });

  it("读取 FastAPI 标准 detail 和参数校验错误", () => {
    expect(parseApiError(400, JSON.stringify({ detail: "仓库路径无效" }))).toBe("仓库路径无效");
    expect(parseApiError(422, JSON.stringify({ detail: [{ msg: "Field required" }, { msg: "Input should be valid" }] })))
      .toBe("Field required；Input should be valid");
  });

  it("非 JSON 错误保留 HTTP 状态与响应正文", () => {
    expect(parseApiError(502, "Bad Gateway")).toBe("HTTP 502: Bad Gateway");
  });
});

describe("代码图谱请求契约", () => {
  it("函数搜索使用后端 GET 主契约和查询参数", async () => {
    const fetchMock = mockSuccessfulFetch({ matches: [] });

    await searchCodeFunctions("repo/a", "main 函数", 12);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/code-graph/repo%2Fa/search?q=main+%E5%87%BD%E6%95%B0&limit=12",
      expect.any(Object),
    );
  });

  it("调用链参数使用后端接受的 symbol，并正确编码特殊字符", async () => {
    const fetchMock = mockSuccessfulFetch();

    await getCallChain("repo-1", "Class.method/name", "both", 3);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/code-graph/repo-1/call-chain?symbol=Class.method%2Fname&direction=both&depth=3",
      expect.any(Object),
    );
  });

  it("类查询编码 class_name，重要节点发送后端声明的 limit", async () => {
    const fetchMock = mockSuccessfulFetch();

    await getClassHierarchy("repo-1", "中文 Class");
    await getImportantFunctions("repo-1", 99);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/api/v1/code-graph/repo-1/class?class_name=%E4%B8%AD%E6%96%87+Class",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/api/v1/code-graph/repo-1/important?limit=99",
      expect.any(Object),
    );
  });
  it("代码图谱请求在提供快照时附带 snapshot_id", async () => {
    const fetchMock = mockSuccessfulFetch();

    await getCodeGraphStats("repo-1", "snapshot/一");
    await searchCodeFunctions("repo-1", "main", 12, "snapshot-1");
    await getCallChain("repo-1", "run", "callees", 2, "snapshot-1");
    await getClassHierarchy("repo-1", "Widget", "snapshot-1");
    await getImportantFunctions("repo-1", 9, "snapshot-1");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/api/v1/code-graph/repo-1/stats?snapshot_id=snapshot%2F%E4%B8%80", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8000/api/v1/code-graph/repo-1/search?q=main&limit=12&snapshot_id=snapshot-1", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://127.0.0.1:8000/api/v1/code-graph/repo-1/call-chain?symbol=run&direction=callees&depth=2&snapshot_id=snapshot-1", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://127.0.0.1:8000/api/v1/code-graph/repo-1/class?class_name=Widget&snapshot_id=snapshot-1", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(5, "http://127.0.0.1:8000/api/v1/code-graph/repo-1/important?limit=9&snapshot_id=snapshot-1", expect.any(Object));
  });
});

describe("解析事实 API 请求契约", () => {
  it("按后端端点传递 Evidence、Symbol、Relation 和诊断的筛选快照", async () => {
    const fetchMock = mockSuccessfulFetch({ items: [] });

    await listEvidence("repo/a", { snapshotId: "snapshot-1", fileId: "file/一", query: "入口", limit: 12 });
    await listSymbols("repo/a", { snapshotId: "snapshot-1", query: "run", limit: 13 });
    await listRelations("repo/a", 14, "snapshot-1");
    await listParserDiagnostics("repo/a", { snapshotId: "snapshot-1", fileId: "file/一", limit: 15 });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/api/v1/repos/repo%2Fa/evidence?snapshot_id=snapshot-1&file_id=file%2F%E4%B8%80&query=%E5%85%A5%E5%8F%A3&limit=12", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8000/api/v1/repos/repo%2Fa/symbols?snapshot_id=snapshot-1&query=run&limit=13", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://127.0.0.1:8000/api/v1/repos/repo%2Fa/relations?limit=14&snapshot_id=snapshot-1", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://127.0.0.1:8000/api/v1/repos/repo%2Fa/parser-diagnostics?snapshot_id=snapshot-1&file_id=file%2F%E4%B8%80&limit=15", expect.any(Object));
  });
});

describe("Snapshot API 请求契约", () => {
  it("仓库和快照查询正确编码路径与 limit", async () => {
    const fetchMock = mockSuccessfulFetch([]);

    await listRepositories(25);
    await listRepositorySnapshots("repo/a", 12);
    await getRepositorySnapshot("repo/a", "snapshot/一");
    await getRepositoryFiles("repo/a", 40, "snapshot/一");
    await getRepositoryFileDetail("repo/a", "file/一", "snapshot/一");
    await getRepositoryChunkDetail("repo/a", "chunk/一", "snapshot/一");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/api/v1/repos?limit=25",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/api/v1/repos/repo%2Fa/snapshots?limit=12",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://127.0.0.1:8000/api/v1/repos/repo%2Fa/snapshots/snapshot%2F%E4%B8%80",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "http://127.0.0.1:8000/api/v1/repos/repo%2Fa/files?limit=40&snapshot_id=snapshot%2F%E4%B8%80",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "http://127.0.0.1:8000/api/v1/repos/repo%2Fa/files/file%2F%E4%B8%80?snapshot_id=snapshot%2F%E4%B8%80",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      "http://127.0.0.1:8000/api/v1/repos/repo%2Fa/chunks/chunk%2F%E4%B8%80?snapshot_id=snapshot%2F%E4%B8%80",
      expect.any(Object),
    );
  });

  it("refresh 使用 POST，显式快照只在提供时加入搜索请求体", async () => {
    const fetchMock = mockSuccessfulFetch({ evidence: [] });

    await refreshRepository("repo-1");
    await searchRepository("repo-1", "入口");
    await searchRepository("repo-1", "入口", "snapshot-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/api/v1/repos/repo-1/refresh",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/api/v1/repos/repo-1/search",
      expect.objectContaining({ body: JSON.stringify({ query: "入口" }) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://127.0.0.1:8000/api/v1/repos/repo-1/search",
      expect.objectContaining({ body: JSON.stringify({ query: "入口", snapshot_id: "snapshot-1" }) }),
    );
  });
});

describe("M3/M4 API 请求契约", () => {
  it("Catalog 列表、树和详情正确编码仓库、快照和条目 ID", async () => {
    const fetchMock = mockSuccessfulFetch({ items: [], roots: [] });

    await listRepositoryCatalog("repo/a", { snapshotId: "snapshot/一", kind: "repository_overview" });
    await getRepositoryCatalogTree("repo/a", "snapshot/一");
    await getRepositoryCatalogItem("repo/a", "item/一", "snapshot/一");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/api/v1/repos/repo%2Fa/catalog?snapshot_id=snapshot%2F%E4%B8%80&kind=repository_overview", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8000/api/v1/repos/repo%2Fa/catalog/tree?snapshot_id=snapshot%2F%E4%B8%80", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://127.0.0.1:8000/api/v1/repos/repo%2Fa/catalog/item%2F%E4%B8%80?snapshot_id=snapshot%2F%E4%B8%80", expect.any(Object));
  });

  it("Trace 查询和 Legacy 协作请求保持 M4 快照契约", async () => {
    const fetchMock = mockSuccessfulFetch({});

    await getRepositoryTrace("repo/a", "trace/一");
    await runCollaboration("repo/a", "检查认证", [{ name: "安全员", role: "security" }], "snapshot/一");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8000/api/v1/repos/repo%2Fa/traces/trace%2F%E4%B8%80", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/api/v1/collaborate",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          repo_id: "repo/a",
          topic: "检查认证",
          agents: [{ name: "安全员", role: "security" }],
          snapshot_id: "snapshot/一",
        }),
      }),
    );
  });

  it("设置更新分别发送 Chat 与 Embedding 密钥动作", async () => {
    const fetchMock = mockSuccessfulFetch({});

    await updateSettings({
      embedding_provider: "openai_compatible",
      llm_api_key_update: { action: "unchanged" },
      embedding_api_key_update: { action: "set", value: "embedding-secret" },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/settings",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          embedding_provider: "openai_compatible",
          llm_api_key_update: { action: "unchanged" },
          embedding_api_key_update: { action: "set", value: "embedding-secret" },
        }),
      }),
    );
  });
});

describe("jobProgressPercent", () => {
  it.each([
    [0, 0],
    [0.346, 35],
    [1, 100],
    [45, 45],
    [200, 100],
    [-0.5, 0],
    [undefined, 0],
  ])("把进度 %s 转换为 %s%%", (input, expected) => {
    expect(jobProgressPercent(input)).toBe(expected);
  });
});
