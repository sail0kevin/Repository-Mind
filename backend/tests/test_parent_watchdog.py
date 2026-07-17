"""Electron 父进程 watchdog 的聚焦单元测试。"""
from __future__ import annotations

import pytest

from service.core.parent_watchdog import (
    MAX_ANCESTOR_DEPTH,
    ParentWatcherPrimitives,
    WAIT_OBJECT_0,
    start_parent_lifetime_watchdog,
)


def _primitives(
    events: list[object],
    *,
    parents: dict[int, int | None] | None = None,
    opened_handle: int | None = 99,
    wait_result: int = WAIT_OBJECT_0,
):
    """用可注入原语模拟 Windows 祖先查询和 HANDLE 生命周期。"""
    parent_map = parents if parents is not None else {9000: 4242}

    def get_parent_pid(pid: int) -> int | None:
        events.append(("parent", pid))
        return parent_map.get(pid)

    def open_process(pid: int) -> int | None:
        events.append(("open", pid))
        return opened_handle

    def start_thread(target):
        events.append("thread")
        target()

    return ParentWatcherPrimitives(
        get_current_pid=lambda: 9000,
        get_parent_pid=get_parent_pid,
        open_process=open_process,
        wait_for_process=lambda handle: events.append(("wait", handle)) or wait_result,
        close_handle=lambda handle: events.append(("close", handle)),
        exit_process=lambda code: events.append(("exit", code)),
        start_thread=start_thread,
    )


def test_direct_parent_is_validated_before_opening_handle():
    """开发态 Python 的 Electron 直接父进程仍可正常启用 watchdog。"""
    events: list[object] = []

    assert start_parent_lifetime_watchdog(
        4242, platform="win32", primitives=_primitives(events)
    ) is True

    assert events == [
        ("parent", 9000),
        ("open", 4242),
        "thread",
        ("wait", 99),
        ("close", 99),
        ("exit", 0),
    ]


def test_one_pyinstaller_intermediate_parent_is_allowed():
    """one-file bootloader 位于中间时，仍只打开已验证的 Electron 祖先。"""
    events: list[object] = []

    assert start_parent_lifetime_watchdog(
        4242,
        platform="win32",
        primitives=_primitives(events, parents={9000: 7000, 7000: 4242}),
    ) is True

    assert events[:3] == [("parent", 9000), ("parent", 7000), ("open", 4242)]
    assert ("exit", 0) in events


def test_unrelated_injected_pid_is_rejected_without_opening_handle():
    """注入的任意 PID 不在祖先链时，不能进入 OpenProcess。"""
    events: list[object] = []

    with pytest.raises(RuntimeError, match="受限祖先链"):
        start_parent_lifetime_watchdog(
            5151,
            platform="win32",
            primitives=_primitives(events, parents={9000: 7000, 7000: 4242}),
        )

    assert not any(isinstance(event, tuple) and event[0] == "open" for event in events)


@pytest.mark.parametrize(
    "parents",
    [
        # 损坏或竞争中的快照可能形成环；检测到已访问 PID 后必须停止。
        {9000: 7000, 7000: 9000},
        # 即使更深处恰好等于注入 PID，也不能越过固定的小深度边界。
        {9000: 8000, 8000: 7000, 7000: 6000, 6000: 5000, 5000: 4242},
    ],
)
def test_cycles_and_excessive_depth_are_rejected(parents):
    """祖先遍历有环检测和固定深度上限。"""
    events: list[object] = []

    with pytest.raises(RuntimeError, match="受限祖先链"):
        start_parent_lifetime_watchdog(
            4242, platform="win32", primitives=_primitives(events, parents=parents)
        )

    lookups = [event for event in events if isinstance(event, tuple) and event[0] == "parent"]
    assert len(lookups) <= MAX_ANCESTOR_DEPTH
    assert not any(isinstance(event, tuple) and event[0] == "open" for event in events)


def test_parent_pid_disappearance_is_rejected_without_opening_handle():
    """进程在快照查询时消失会返回 None，安全地视为无法验证。"""
    events: list[object] = []

    with pytest.raises(RuntimeError, match="受限祖先链"):
        start_parent_lifetime_watchdog(
            4242, platform="win32", primitives=_primitives(events, parents={9000: None})
        )

    assert events == [("parent", 9000)]


def test_open_failure_after_validation_does_not_start_waiter():
    """祖先已验证但已退出导致 OpenProcess 失败时，不启动线程也没有 HANDLE 可关闭。"""
    events: list[object] = []

    with pytest.raises(RuntimeError, match="无法打开"):
        start_parent_lifetime_watchdog(
            4242,
            platform="win32",
            primitives=_primitives(events, opened_handle=None),
        )

    assert events == [("parent", 9000), ("open", 4242)]


def test_parent_exit_closes_handle_then_stops_backend():
    """父进程 HANDLE signaled 后先关闭 HANDLE，再让后端自行退出。"""
    events: list[object] = []

    start_parent_lifetime_watchdog(
        4242, platform="win32", primitives=_primitives(events)
    )

    assert events[-3:] == [("wait", 99), ("close", 99), ("exit", 0)]


def test_missing_parent_pid_keeps_standalone_backend_compatible():
    """独立运行开发后端、未注入 Electron PID 时不启动监视器。"""
    events: list[object] = []

    assert start_parent_lifetime_watchdog(
        None, platform="win32", primitives=_primitives(events)
    ) is False
    assert events == []


def test_wait_failure_closes_handle_without_exiting():
    """等待失败仍关闭 HANDLE，但不能把错误结果当成父进程退出。"""
    events: list[object] = []

    assert start_parent_lifetime_watchdog(
        4242,
        platform="win32",
        primitives=_primitives(events, wait_result=0xFFFFFFFF),
    ) is True
    assert ("close", 99) in events
    assert ("exit", 0) not in events


def test_thread_start_failure_closes_validated_handle():
    """线程创建异常时，调用方仍负责关闭尚未交给线程的 HANDLE。"""
    events: list[object] = []
    primitives = _primitives(events)
    primitives = ParentWatcherPrimitives(
        **{
            **primitives.__dict__,
            "start_thread": lambda target: (_ for _ in ()).throw(RuntimeError("boom")),
        }
    )

    with pytest.raises(RuntimeError, match="boom"):
        start_parent_lifetime_watchdog(4242, platform="win32", primitives=primitives)

    assert events[-1] == ("close", 99)
