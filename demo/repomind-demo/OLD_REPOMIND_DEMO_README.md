# RepoMind Synthetic Demo

一个只用于演示 RepoMind 索引、概览、影响分析、测试定位和安全线索扫描的小型 Python 仓库。

## 这个项目做什么

`repomind_demo.app.main` 是命令行入口。它读取 `config.json` 中的演示名称，调用服务层生成欢迎语，并将结果交给 `ConsoleNotifier` 输出。

代码链路：

```text
repomind_demo.app.main
  -> GreetingService.build_message
  -> GreetingService._format_name
  -> ConsoleNotifier.send
```

## 运行

不需要安装第三方依赖。请在此目录运行：

```bash
python -m repomind_demo.app.main
```

## 测试

项目使用 Python 标准库 `unittest`，因此同样不需要安装依赖：

```bash
python -m unittest discover -s tests -v
```

## 安全演示边界

`repomind_demo/security_examples.py` 故意保留 `eval`、`yaml.load` 和 `shell=True` 的**静态扫描样例**，使 RepoMind 的规则型安全分析能给出可预测的线索。该模块不会被入口导入，测试也不会执行其中的函数。

`config.json` 中的 `demo_api_key` 是公开、不可用的占位文本，不是密钥、令牌或任何可认证凭据。

## 预期展示

- **概览问题**：README、`config.json`、`repomind_demo/app/main.py` 和 `tests/test_greeting.py` 应出现在推荐阅读范围内。
- **影响问题**：修改 `GreetingService.build_message` 时，应检查其调用入口 `app/main.py` 和覆盖输出格式的 `tests/test_greeting.py`。
- **测试问题**：README 明确给出 unittest 命令，`tests/` 目录会被识别为测试目录。
- **安全问题**：`security_examples.py` 应产生三条规则型风险线索（eval、不安全 YAML 加载、带 shell 选项的 subprocess）；它们是待人工确认的演示，不是已证实漏洞。

详情见 `expected/showcase.json`。
