"""演示业务服务：把配置中的名称转换为欢迎语。"""


class GreetingService:
    """集中管理欢迎语格式，方便影响分析定位调用方和测试。"""

    def __init__(self, prefix: str) -> None:
        # 保存由配置传入的固定前缀，避免在多个调用点重复拼写。
        self.prefix = prefix

    def build_message(self, name: str) -> str:
        """为用户名称生成稳定、可测试的欢迎语。"""
        formatted_name = self._format_name(name)
        return f"{self.prefix}, {formatted_name}!"

    def _format_name(self, name: str) -> str:
        """去除首尾空白；空名称回退到访客。"""
        return name.strip() or "Guest"
