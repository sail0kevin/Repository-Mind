"""仅用于安全规则展示的样例；入口和测试均不会执行这里的函数。"""


def parse_demo_expression(expression: str) -> object:
    """不安全示例：eval 应改为受限的解析或白名单映射。"""
    return eval(expression)


def load_demo_yaml(text: str) -> object:
    """不安全示例：yaml.load 应改为 yaml.safe_load。"""
    import yaml

    return yaml.load(text)


def run_demo_command(command: str) -> None:
    """不安全示例：shell=True 应改为参数列表和输入校验。"""
    import subprocess

    subprocess.run(command, shell=True, check=False)
