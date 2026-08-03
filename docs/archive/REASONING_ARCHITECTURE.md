# 增强推理架构

推荐入口：

```powershell
python run_reasoning_agents.py
python run_reasoning_agents.py --headless
python run_reasoning_agents.py --task "进入顾客档案 /customer" --url "http://目标地址"
```

## 六个正式 Agent

- Planner：把自然语言任务拆成带验收条件的步骤。
- Coordinator：路由感知、控制预算和停止条件。
- Executor：基于页面证据和世界模型提出原子工具调用。
- Verifier：独立读取页面并裁决是否完成。
- Critic：独立审查高影响动作，必要时拒绝或替换。
- Replanner：失败或连续缺少证据时重新制定策略。

## 显式任务世界模型

世界模型记录当前页面、访问历史、动作结果、Verifier 证据、开放失败假设和策略
修订。它只保存结构化事实，不保存隐藏思维链。输入值等敏感参数会被脱敏。

正常路径不会强制调用 Replanner；只有动作失败或连续缺少完成证据时才触发，
并且同一个失败动作不会重复重规划。Critic 对填充、读取、断言等低影响动作做
本地协议审查，对点击、导航、选择和刷新等高影响动作使用独立模型上下文审查。
