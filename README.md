# AI Web 测试智能体

基于 Python、Playwright 和大模型的 CLI 型多 Agent Web 自动化测试平台。项目使用自研 AgentRuntime、ToolRegistry、Blackboard 和 WorldModel，不依赖 LangChain、AutoGen 或 CrewAI。

## 正式入口

```powershell
python -m web_agent doctor
python -m web_agent capabilities
python -m web_agent explore
python -m web_agent explore --headless
python -m web_agent train --validate-only
python -m web_agent train --headless --priority P0 --repeat 2
python -m web_agent regression --headless
python -m web_agent benchmark --headless --repeat 2
```

自然语言任务：

```powershell
python -m web_agent explore --task "进入顾客档案并停留 2 秒" --url "https://example.test"
```

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

## 项目结构

```text
web_agent/          唯一生产组合、CLI 和浏览器执行边界
agents/             Agent 实现
core/               工具运行时、黑板、世界模型和凭证仓库
executor/           Playwright 基础动作和 Action Schema
perception/         ARIA 与视觉 SoM 感知
runner/             生产依赖的 Runner 实现
loader/             Excel 探索用例加载
case/               用例生成与管理
scripts/            模板生成、导出和诊断工具
docs/               当前生产文档与历史架构归档
tests/              单元、契约和架构守护测试
```

根目录不再保留 `main.py`、`ai_test.py` 或 `run_*.py`。所有生产操作统一通过 `python -m web_agent` 执行。

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

## 诊断与验证

```powershell
python -m scripts.diagnostics.login
python -m scripts.diagnostics.customer_page --wait-ms 2000
python -B -m unittest discover -s tests -v
```

详细说明：

- [生产架构](docs/ARCHITECTURE.md)
- [运行手册](docs/RUNBOOK.md)
- [Web Agent 评测](docs/EVALUATION.md)
- [Web Agent 课程训练](docs/TRAINING.md)
- [历史架构归档](docs/archive/README.md)
