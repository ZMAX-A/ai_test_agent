"""增强推理入口：世界模型 + Critic + 动态 Replanner。"""

# 必须先安装推理运行时，再加载通用 CLI。
from runner.reasoning_runtime_activation import ReasoningAgentRunner  # noqa: F401
from run_agent_runtime import main


if __name__ == "__main__":
    main()
