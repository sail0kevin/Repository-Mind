"""Python AST 解析器的主要结构 fixture。"""
from pkg.base import ExternalBase, external_call


def trace(label: str):
    """只用于验证装饰器源码提取。"""
    return lambda function: function


def helper(name: str) -> str:
    """供类方法验证同文件调用解析。"""
    return name.upper()


class BaseService(ExternalBase):
    """同时覆盖继承、异步方法、签名、装饰器和调用关系。"""

    @trace("service")
    async def run(self, value: int = 1, *, strict: bool = False) -> str:
        external_call(value)
        return helper(str(value))


def dynamic(callback):
    """参数调用无法确定真实目标，因此不能建调用边。"""
    callback()
    unknown()
    return getattr(callback, "run")()
