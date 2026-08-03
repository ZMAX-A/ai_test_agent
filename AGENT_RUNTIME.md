# Agent Runtime 架构

推荐入口：

```powershell
python run_agents.py
python run_agents.py --headless
python run_agents.py --show-capabilities
python run_agents.py --task "进入顾客档案 /customer" --url "http://目标地址"
```

## 角色权限

- `planner`：没有浏览器工具，只负责把自然语言目标拆成步骤。
- `coordinator`：只能调用 `observe_aria` 和 `observe_visual`。
- `executor`：只能调用动作白名单中的浏览器工具。
- `verifier`：只能调用 `verify_page`，独立回读完成证据。

工具调用依次经过 AgentProfile 和 ToolSpec 两层授权。所有调用结果写入
TaskBlackboard；输入值、用户名、密码、Token 和 API Key 会在黑板中脱敏。

`LLM_TOOL_CALLING_MODE` 支持：

- `auto`（默认）：优先使用 OpenAI 兼容 Tool Calling，不支持时降级为 JSON。
- `required`：强制使用原生 Tool Calling，失败时不降级。
- `off`：只使用兼容的 JSON 动作协议。
