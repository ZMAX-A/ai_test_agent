# Web Agent 生产架构

## 单一生产链路

```text
python -m web_agent
  -> web_agent.commands.main
  -> web_agent.runner.ProductionRunner
  -> RunnerDependencies
     -> CredentialAwareReasoningState
     -> AgentRuntime / ToolRegistry
     -> Coordinator / Executor / Verifier / Critic / Replanner
     -> web_agent.browser.PolicyAwareBrowserExecutor
     -> AuthenticationPolicy
     -> Playwright
```

回归命令路由到 `ProductionRegressionRunner`，并复用相同的浏览器和认证执行器。

## Agent 边界

| Agent | 职责 | 工具权限 |
|---|---|---|
| Planner | 自然语言任务拆步 | 无浏览器工具 |
| Coordinator | 感知调度和确定性动作 | `observe_aria`、`observe_visual` |
| Executor | 动作决策与执行 | 浏览器动作和断言 |
| Verifier | 独立完成条件验证 | `verify_page` |
| Critic | 审查模型候选动作 | 无浏览器工具 |
| Replanner | 失败后调整策略 | 无浏览器工具 |

Excel 已带步骤时不调用 Planner；确定性认证动作不调用模型。Critic 审查模型候选动作，Replanner 只在任务世界模型判定失败或停滞时触发。

## 核心状态和安全边界

- `TaskBlackboard` 保存 Agent 事件、模型调用数和审计轨迹。
- `TaskWorldModel` 保存页面事实、动作结果、失败假设和重规划状态。
- `AgentRuntime` 按 AgentProfile 和 ToolSpec 双重校验工具权限。
- `CredentialVault` 将真实凭证替换为引用，仅在执行边界解析。
- `ContextVar` 隔离每个任务的 Runtime 和 WorldModel。

## 目录约束

- 新生产能力只能进入 `web_agent`。
- 根目录不得增加 Python 启动脚本。
- 兼容层不得复制生产逻辑。
- 探索和回归必须复用同一认证执行器。
- 结构调整必须通过全量单元测试、CLI 冒烟和真实回归。
