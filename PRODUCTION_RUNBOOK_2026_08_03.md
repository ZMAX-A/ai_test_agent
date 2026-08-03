# Web Agent 生产运行手册（2026-08-03）

## 当前站点配置

当前账号需要按门店文本选择：

```powershell
$env:LOGIN_STORE_SELECTION_MODE = "text"
$env:LOGIN_STORE_OPTION_TEXT = "zwf1"
```

门店属于环境配置，不应硬编码到通用执行器。

## 统一生产命令

```powershell
python -m web_agent doctor
python -m web_agent capabilities
python -m web_agent explore
python -m web_agent explore --headless
python -m web_agent regression --headless
```

生产组合只有一条：

- `web_agent.runner.ProductionRunner`
- `web_agent.reasoning.CredentialAwareReasoningState`
- `web_agent.browser.PolicyAwareBrowserExecutor`
- `web_agent.auth.AuthenticationPolicy`
- `web_agent.regression.ProductionRegressionRunner`

## 兼容命令

以下命令仍可用，但只委托给统一实现：

```powershell
python -m web_agent.final explore
python -m web_agent.regression --headless
```

`main.py`、`ai_test.py`、`run_*.py` 和历史 Runner 暂时冻结，不再增加新能力。

## 可靠性约束

- 用户名和密码由 Coordinator 生成确定性引用，执行边界才注入真实凭证。
- 模型提供的登录字段值会被忽略。
- 无法确认字段语义时失败关闭，不执行模糊填充。
- 门店按目标文本使用键盘导航并以 Enter 提交。
- 提交前关闭 Ant Select 临时浮层。
- Playwright `wait_for_function` 使用 keyword-only `arg=...`。
- 登录成功必须返回真实 `old_url`、`new_url`、`url_changed`。
- Verifier 独立回读完成条件，动作成功不等于步骤成功。

## 验证基线

```powershell
python -B -m unittest discover -s tests -v
```

结构守护测试会阻止同名模块/包再次出现，并验证生产组合始终绑定唯一浏览器执行器。
