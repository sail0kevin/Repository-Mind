"""GreetingService 与入口流程的回归测试。"""

import unittest
from unittest.mock import patch

from repomind_demo.app.main import main
from repomind_demo.service import GreetingService


class GreetingServiceTests(unittest.TestCase):
    """验证欢迎语格式，修改服务层时应优先运行这些测试。"""

    def test_build_message_strips_name(self) -> None:
        # 该断言覆盖 build_message 对私有格式化方法的调用结果。
        service = GreetingService("Hello")
        self.assertEqual(service.build_message("  RepoMind demo  "), "Hello, RepoMind demo!")

    def test_build_message_uses_guest_for_blank_name(self) -> None:
        # 空名称的回退行为同样属于对外输出契约。
        service = GreetingService("Hello")
        self.assertEqual(service.build_message("   "), "Hello, Guest!")

    @patch("repomind_demo.app.main.ConsoleNotifier.send")
    def test_main_sends_configured_message(self, send_mock) -> None:
        # 入口必须把配置、服务和通知器连成完整链路。
        send_mock.side_effect = lambda message: message
        self.assertEqual(main(), "Hello, RepoMind demo!")
        send_mock.assert_called_once_with("Hello, RepoMind demo!")


if __name__ == "__main__":
    unittest.main()
