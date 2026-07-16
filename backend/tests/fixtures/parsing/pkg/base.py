"""跨文件解析 fixture 的公共定义。"""


def external_call(value: int = 0) -> str:
    """供 service.py 通过 import 静态绑定。"""
    return str(value)


class ExternalBase:
    """供 service.py 验证继承关系。"""

    pass


def duplicate() -> None:
    """同名函数用于证明解析器不会 all-to-all 猜测。"""
    return None
