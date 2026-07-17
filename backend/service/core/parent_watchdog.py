"""Electron 父进程生命周期监视器。

Windows 桌面版在后端启动时注入 Electron 主进程 PID。本模块通过只读进程快照验证该 PID
确实位于后端的短祖先链中，再只用 ``SYNCHRONIZE`` 权限打开它并等待 HANDLE 变为
signaled。这样既兼容 PyInstaller one-file 中间 bootloader，也不会信任、扫描终止任意 PID。
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
INFINITE = 0xFFFFFFFF
TH32CS_SNAPPROCESS = 0x00000002
ERROR_NO_MORE_FILES = 18
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_ANCESTOR_DEPTH = 4


class PROCESSENTRY32W(ctypes.Structure):
    """Toolhelp32 进程快照条目，只读取 PID 与父 PID 字段。"""

    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_uint32),
        ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


@dataclass(frozen=True)
class ParentWatcherPrimitives:
    """可注入的底层操作，便于测试所有权校验、等待和退出分支。"""

    get_current_pid: Callable[[], int]
    get_parent_pid: Callable[[int], int | None]
    open_process: Callable[[int], int | None]
    wait_for_process: Callable[[int], int]
    close_handle: Callable[[int], None]
    exit_process: Callable[[int], None]
    start_thread: Callable[[Callable[[], None]], None]


def _windows_primitives() -> ParentWatcherPrimitives:
    """构造只申请 SYNCHRONIZE 权限的 Windows HANDLE 操作。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = ctypes.c_int
    kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = ctypes.c_int
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    def get_parent_pid(pid: int) -> int | None:
        """从只读 Toolhelp32 快照查询一个进程的父 PID，并始终关闭快照 HANDLE。"""
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        snapshot_value = int(snapshot) if snapshot is not None else None
        if snapshot_value in (None, INVALID_HANDLE_VALUE):
            return None

        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        try:
            found = kernel32.Process32FirstW(ctypes.c_void_p(snapshot_value), ctypes.byref(entry))
            while found:
                if int(entry.th32ProcessID) == pid:
                    parent_pid = int(entry.th32ParentProcessID)
                    return parent_pid if parent_pid > 0 else None
                found = kernel32.Process32NextW(
                    ctypes.c_void_p(snapshot_value), ctypes.byref(entry)
                )
            # 进程可能已在快照期间消失；此时安全地视为无法验证。
            if ctypes.get_last_error() not in (0, ERROR_NO_MORE_FILES):
                logger.warning("读取 Windows 进程快照失败，错误码=%s。", ctypes.get_last_error())
            return None
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(snapshot_value))

    def open_process(pid: int) -> int | None:
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        return int(handle) if handle else None

    def wait_for_process(handle: int) -> int:
        return int(kernel32.WaitForSingleObject(ctypes.c_void_p(handle), INFINITE))

    def close_handle(handle: int) -> None:
        kernel32.CloseHandle(ctypes.c_void_p(handle))

    def start_thread(target: Callable[[], None]) -> None:
        threading.Thread(
            target=target,
            name="repomind-electron-parent-watchdog",
            daemon=True,
        ).start()

    return ParentWatcherPrimitives(
        get_current_pid=os.getpid,
        get_parent_pid=get_parent_pid,
        open_process=open_process,
        wait_for_process=wait_for_process,
        close_handle=close_handle,
        exit_process=os._exit,
        start_thread=start_thread,
    )


def start_parent_lifetime_watchdog(
    injected_parent_pid: int | None,
    *,
    platform: str = sys.platform,
    primitives: ParentWatcherPrimitives | None = None,
) -> bool:
    """验证并监视 Electron 的受限祖先进程；成功启动监视线程时返回 True。

    Windows 的 PyInstaller one-file 后端可能以 bootloader 作为直接父进程，因此从当前后端
    PID 开始做小深度、可检测循环的祖先查询。只有注入 PID 出现在链上才会申请 HANDLE。
    非 Windows 平台不启用基于 PID 的轮询，因为 PID 可复用且无法提供等价 HANDLE 身份保证。
    """
    if injected_parent_pid is None:
        return False
    if injected_parent_pid <= 0:
        raise ValueError("Electron 父进程 PID 必须为正整数。")
    if platform != "win32" and primitives is None:
        logger.info("当前平台不启用 Electron 父进程 HANDLE 监视器。")
        return False

    watcher = primitives or _windows_primitives()
    current_pid = watcher.get_current_pid()
    visited = {current_pid}
    ancestor_pid = current_pid
    validated = False
    for _ in range(MAX_ANCESTOR_DEPTH):
        ancestor_pid = watcher.get_parent_pid(ancestor_pid)
        if ancestor_pid is None:
            break
        if ancestor_pid in visited:
            break
        if ancestor_pid == injected_parent_pid:
            validated = True
            break
        visited.add(ancestor_pid)

    if not validated:
        raise RuntimeError(
            "拒绝监视未验证的进程：注入 PID 不在后端的受限祖先链中。"
        )

    handle = watcher.open_process(injected_parent_pid)
    if handle is None:
        raise RuntimeError("无法打开已验证的 Electron 父进程 HANDLE。")

    def wait_for_parent_exit() -> None:
        try:
            wait_result = watcher.wait_for_process(handle)
        finally:
            watcher.close_handle(handle)
        if wait_result == WAIT_OBJECT_0:
            logger.warning("Electron 父进程已结束，RepoMind 后端将自行退出。")
            watcher.exit_process(0)
        else:
            logger.error("等待 Electron 父进程 HANDLE 失败，结果码=%s。", wait_result)

    try:
        watcher.start_thread(wait_for_parent_exit)
    except BaseException:
        watcher.close_handle(handle)
        raise
    return True
