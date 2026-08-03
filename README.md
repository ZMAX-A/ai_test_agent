# AI Web 测试智能体

基于 Python、Playwright 和大模型的 CLI 型多 Agent Web 自动化测试平台。项目使用自研的 AgentRuntime、ToolRegistry、Blackboard 和 WorldModel，不依赖 LangChain、AutoGen 或 CrewAI。

## 生产入口

新开发和生产验证统一使用 `web_agent`：

```powershell
python -m web_agent doctor
python -m web_agent capabilities
python -m web_agent explore
python -m web_agent explore --headless
python -m web_agent regression --headless
```

自然语言任务：

```powershell
python -m web_agent explore --task "进入顾客档案并停留 2 秒" --url "https://example.test"
```

`python -m web_agent.final`、`python -m web_agent.regression` 和旧的 `run_*.py` 暂时保留兼容，但不再承载独立生产实现。

## 执行链路

```text
自然语言 / explore_cases.xlsx
  -> Planner（自然语言任务才调用）
  -> ProductionRunner
  -> Coordinator（ARIA / Visual 感知调度）
  -> Executor + Critic + Replanner
  -> AgentRuntime / ToolRegistry
  -> PolicyAwareBrowserExecutor
  -> Playwright
  -> StrictVerifier
  -> standard.xlsx / case_library / screenshots / Allure
```

正式 Agent 角色为 Planner、Coordinator、Executor、Verifier、Critic、Replanner。工具权限按角色隔离，执行和验证使用不同工具边界。

## 核心目录

```text
web_agent/   唯一生产组合、CLI 和浏览器执行边界
agents/      六类 Agent 的实现
core/        工具运行时、共享黑板、世界模型、凭证仓库
executor/    Playwright 基础动作和 Action Schema 校验
perception/  ARIA 与视觉 SoM 感知
runner/      回归执行器和历史兼容 Runner
loader/      Excel 探索用例加载
case/        用例生成与管理
tests/       单元和架构约束测试
```

## 安装

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

创建 `.env` 并配置：

```dotenv
LLM_API_KEY=
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-v4-flash
VL_API_KEY=
VL_BASE_URL=
VL_MODEL=
LOGIN_URL=
LOGIN_USERNAME=
LOGIN_PASSWORD=
LOGIN_STORE_SELECTION_MODE=text
LOGIN_STORE_OPTION_TEXT=
```

敏感凭证只在执行边界解析；模型上下文、共享黑板和日志中仅保存引用或脱敏值。

## 验证

```powershell
python -B -m unittest discover -s tests -v
python -m web_agent doctor
python -m web_agent capabilities
```

架构说明见 `PRODUCTION_ARCHITECTURE_V2.md`，运行配置见 `PRODUCTION_RUNBOOK_2026_08_03.md`。
