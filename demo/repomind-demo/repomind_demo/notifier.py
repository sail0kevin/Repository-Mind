"""演示输出适配器。"""


class ConsoleNotifier:
    """把服务层生成的文本输出到控制台。"""

    def send(self, message: str) -> str:
        """打印并返回消息，既便于用户查看，也便于单元测试断言。"""
        print(message)
        return message
