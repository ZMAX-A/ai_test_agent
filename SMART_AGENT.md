# Smart Agent 推荐入口

增强推理版本使用以下入口：

```powershell
python run_smart_agents.py
python run_smart_agents.py --headless
python run_smart_agents.py --show-capabilities
python run_smart_agents.py --task "进入顾客档案 /customer" --url "http://目标地址"
```

该入口包含六个正式 Agent：Planner、Coordinator、Executor、Verifier、Critic、
Replanner。Critic 和 Replanner 没有浏览器工具权限；它们分别负责独立动作审查
和失败后的动态策略修订。
