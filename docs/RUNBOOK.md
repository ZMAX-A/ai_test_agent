# Web Agent 生产运行手册

## 当前站点配置

```powershell
$env:LOGIN_STORE_SELECTION_MODE = "text"
$env:LOGIN_STORE_OPTION_TEXT = "zwf1"
```

门店属于环境配置，不应硬编码到通用执行器。

## 正式命令

```powershell
python -m web_agent doctor
python -m web_agent capabilities
python -m web_agent explore
python -m web_agent explore --headless
python -m web_agent regression --headless
```

诊断命令：

```powershell
python -m scripts.diagnostics.login
python -m scripts.diagnostics.customer_page --wait-ms 2000
```

## 生产组合

- `web_agent.runner.ProductionRunner`
- `web_agent.reasoning.CredentialAwareReasoningState`
- `web_agent.browser.PolicyAwareBrowserExecutor`
- `web_agent.auth.AuthenticationPolicy`
- `web_agent.regression.ProductionRegressionRunner`

## 可靠性约束

- 模型提供的登录字段值会被忽略。
- 无法确认登录字段语义时失败关闭。
- 门店按目标文本使用键盘导航并以 Enter 提交。
- 登录成功必须返回真实 URL 变化证据。
- Verifier 独立回读完成条件，动作成功不等于步骤成功。
- 导航加载事件超时只有在 URL 证明确已到达时才允许继续。

## 验证

```powershell
python -B -m unittest discover -s tests -v
python -m web_agent doctor
python -m web_agent capabilities
python -m web_agent regression --headless
```
