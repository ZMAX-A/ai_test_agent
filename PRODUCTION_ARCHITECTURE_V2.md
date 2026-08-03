# Web Agent 生产架构 V2（结构收敛版）

## 单一生产链路

```text
web_agent.__main__
  -> web_agent.cli
  -> web_agent.commands.main
  -> web_agent.runner.ProductionRunner
  -> RunnerDependencies（显式依赖）
     -> CredentialAwareReasoningState
     -> AgentRuntime / ToolRegistry
     -> Coordinator / Executor / Verifier / Critic / Replanner
     -> web_agent.browser.PolicyAwareBrowserExecutor
     -> AuthenticationPolicy
     -> Playwright
```

回归命令由同一 CLI 路由到 `ProductionRegressionRunner`，并复用相同的 `PolicyAwareBrowserExecutor`，不再使用另一套登录实现。

## Agent 边界

| Agent | 职责 | 工具权限 |
|---|---|---|
| Planner | 自然语言任务拆步 | 无浏览器工具 |
| Coordinator | 感知调度和确定性动作 | `observe_aria`、`observe_visual` |
| Executor | 动作决策与执行 | 浏览器动作和断言 |
| Verifier | 独立完成条件验证 | `verify_page` |
| Critic | 审查模型候选动作 | 无浏览器工具 |
| Replanner | 失败后调整策略 | 无浏览器工具 |

Excel 已带步骤时不调用 Planner；确定性登录动作不调用模型。Critic 审查模型生成的候选动作，Replanner 仅在任务世界模型判定失败或停滞时触发。

## 核心状态

- `TaskBlackboard`：保存 Agent 事件、模型调用数和可审计轨迹。
- `TaskWorldModel`：保存页面事实、动作结果、失败假设和重规划状态。
- `AgentRuntime`：按 AgentProfile 和 ToolSpec 双重校验工具权限。
- `CredentialVault`：把真实凭证替换为引用，并仅在执行边界解析。
- `ContextVar`：隔离每个任务的 Runtime 和 WorldModel，不修改全局类。

## 浏览器执行边界

`web_agent/browser/executor.py` 是唯一生产实现，合并了此前分散在 browser、stable、keyboard_text 和 final 层中的能力：

- 登录字段语义识别和凭证强制注入；
- 门店键盘文本匹配；
- 临时浮层关闭；
- Playwright keyword-only 导航等待；
- URL 变化后置条件；
- 凭证和错误消息脱敏。

`final_browser.py` 和 `keyboard_text_browser.py` 仅保留公开名称别名，不包含独立逻辑。

## 目录约束

- `web_agent` 和 `core` 下禁止同时出现 `name.py` 与 `name/__init__.py`。
- 新功能只能进入 `web_agent` 生产链路。
- 兼容入口只能委托，不得复制生产逻辑。
- 探索与回归必须复用同一认证执行器。
- 每次结构调整必须通过全量单元测试和 CLI 冒烟测试。
