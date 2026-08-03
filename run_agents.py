"""推荐入口：先激活 AgentRuntime，再复用统一 CLI。"""

# 导入即完成运行时绑定，必须早于 CLI 开始创建 Runner。
from runner.agent_runtime_activation import AgentRuntimeTestRunner  # noqa: F401
from run_agent_runtime import main


if __name__ == "__main__":
    main()
