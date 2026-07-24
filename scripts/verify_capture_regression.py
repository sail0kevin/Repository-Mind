"""校验 `capture_demo_evidence.py` 泛化改造未改变内置 3 题 Demo 的采集结果。

比较分两层，因为两者的确定性保证强度不同：

1. `demo-evidence-capture-post-fix.json`（下游 `report_retrieval_metrics.py` 与
   `test_benchmark_fixtures.py` 实际依赖的契约文件）：剔除 UUID/时间戳等天然
   易变字段后，两次运行必须完全相等——这是本次泛化改造真正必须保住的不变量。
2. `repomind-demo-trace.post-fix.json`：只做结构级校验（每题的 route/retrieval/
   synthesis step 各恰好一次、route_tools 相同、evidence 路径集合相同），不要求
   列表顺序或分数逐一相等。经过两次干净重跑验证：即使 `_run_builtin_demo_capture()`
   的代码逐行未改动，`dependency_impact` 工具的引用候选在并列分数下的先后顺序
   仍会随进程哈希种子而变化（Python 的 set/dict 哈希随机化），这是改造前就存在
   的产品代码行为，不属于本次 Task 3 的范围，因此不作为逐字段回归判据。

用法：
    python scripts/verify_capture_regression.py
它会重新执行 `_run_builtin_demo_capture()`，并对结果做上述两层比较。
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import capture_demo_evidence as capture  # noqa: E402

VOLATILE_KEYS = {
    "trace_id",
    "repo_id",
    "snapshot_id",
    "session_id",
    "id",
    "chunk_id",
    "file_id",
    "parent_id",
    "created_at",
    "completed_at",
    "updated_at",
}


def _strip_volatile(value: Any) -> Any:
    """递归剔除 UUID/时间戳类字段，只保留可比较的确定性内容。"""
    if isinstance(value, dict):
        return {
            key: _strip_volatile(child)
            for key, child in value.items()
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


def _trace_shape(trace_payload: dict[str, Any]) -> dict[str, Any]:
    """把 Trace 精简成结构级不变量：每题的 step 类型序列、路由到的工具、去重后的证据路径集合。

    不比较列表顺序或分数——见模块文档：`dependency_impact` 在并列分数下的候选
    先后顺序本就会随进程哈希种子波动，这是改造前既有的产品行为。
    """
    shape: dict[str, Any] = {}
    for question_id, entry in trace_payload.get("questions", {}).items():
        trace = entry["trace"]
        step_types = [step.get("step_type") for step in trace.get("steps", [])]
        tools = [
            str(step.get("tool_name"))
            for step in trace.get("steps", [])
            if step.get("step_type") == "tool"
        ]
        evidence_paths: set[str] = set()
        for step in trace.get("steps", []):
            for ref in step.get("evidence_refs", []) or []:
                path = ref.get("file_path")
                if path:
                    evidence_paths.add(str(path))
        shape[question_id] = {
            "step_types": step_types,
            "tools": tools,
            "evidence_paths": sorted(evidence_paths),
        }
    return shape


def main() -> int:
    before_capture = json.loads(capture.OUTPUT_PATH.read_text(encoding="utf-8"))
    before_trace = json.loads(capture.TRACE_OUTPUT_PATH.read_text(encoding="utf-8"))

    exit_code = capture._run_builtin_demo_capture()
    if exit_code != 0:
        print(f"_run_builtin_demo_capture() 返回非零：{exit_code}", file=sys.stderr)
        return 1

    after_capture = json.loads(capture.OUTPUT_PATH.read_text(encoding="utf-8"))
    after_trace = json.loads(capture.TRACE_OUTPUT_PATH.read_text(encoding="utf-8"))

    stripped_before_capture = _strip_volatile(copy.deepcopy(before_capture))
    stripped_after_capture = _strip_volatile(copy.deepcopy(after_capture))

    ok = True
    if stripped_before_capture != stripped_after_capture:
        print("回归失败：demo-evidence-capture-post-fix.json 的确定性内容发生变化。", file=sys.stderr)
        ok = False

    if _trace_shape(before_trace) != _trace_shape(after_trace):
        print("回归失败：repomind-demo-trace.post-fix.json 的结构级不变量发生变化。", file=sys.stderr)
        ok = False

    if before_capture == after_capture:
        print("警告：capture 文件逐字节相同（未预期，通常至少 trace_id 会变化）。", file=sys.stderr)

    if ok:
        print("PASS：泛化改造未改变内置 3 题 Demo 采集的确定性内容与 Trace 结构。")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
