"""最小命令行入口：读取配置、生成欢迎语并输出。"""

from __future__ import annotations

import json
from pathlib import Path

from repomind_demo.notifier import ConsoleNotifier
from repomind_demo.service import GreetingService


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.json"


def load_config() -> dict[str, str]:
    """读取仓库根目录的 JSON 配置。"""
    # 这是固定的演示配置，不会读取环境变量或任何真实凭据。
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def main() -> str:
    """组装依赖并运行一条可预测的演示流程。"""
    config = load_config()
    service = GreetingService(config["greeting_prefix"])
    message = service.build_message(config["app_name"])
    return ConsoleNotifier().send(message)


if __name__ == "__main__":
    main()
