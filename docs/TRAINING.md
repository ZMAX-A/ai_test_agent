# Web Agent 课程训练

train 命令把 XLSX 课程表编译为可执行步骤，并且只把完整、可验证、可复现的轨迹写入经验记忆。训练不会修改源工作簿，也不会在运行中生成 standard.xlsx。

## 先做离线校验

~~~powershell
python -m web_agent train --validate-only
python -m web_agent train --validate-only --file test_cases/webagent_test_case.xlsx --output report/training/validation.json
~~~

校验不会启动浏览器，也不会创建 SQLite 记忆库。报告会列出每条用例被选中或跳过的原因、课程错误和能力缺口。

## 默认安全门禁

- 只选择源表中“是否执行”为“是”、格式有效且没有能力缺口的用例。
- 负向登录默认禁止；写操作需要显式传入 --allow-mutations，破坏性操作还需要 --allow-destructive。
- 默认按用例 ID 稳定划出 15% 保留集。即使显式传入 --case 也不会绕过保留集；只有 --include-holdout 会放行。
- 顾客、影像、个人资料等敏感模块或 URL 路径禁用视觉模型和页面内容外发，失败截图与自动生成用例也会被抑制。
- 明文手机号、邮箱和凭证不会进入模型上下文、报告或经验轨迹；凭证在执行边界才由 {{credential.*}} 引用解析。

## 执行训练

先从少量只读 P0 用例开始：

~~~powershell
python -m web_agent train --headless --priority P0 --limit 5 --repeat 2
~~~

按模块或用例运行：

~~~powershell
python -m web_agent train --headless --module 首页 --repeat 2
python -m web_agent train --headless --case home008 --repeat 2 --include-holdout
~~~

显式放行写操作时，应使用隔离测试数据并确认课程中有恢复步骤：

~~~powershell
python -m web_agent train --headless --allow-mutations --case example-write-case
python -m web_agent train --headless --allow-mutations --allow-destructive --case example-delete-case
~~~

## 经验晋升、隔离和续跑

一次“成功”只有在以下条件全部满足时才计为 passed_verified：

- 返回的结果数和轨迹数都与声明步骤数完全一致；
- 每一步都由 Verifier 判定通过；
- 每一步都有非空、可观察证据；
- 轨迹中的动作类型与步骤目标一致。

同一课程版本和训练策略下，至少两个不同运行 ID 的 passed_verified 才会把经验从 candidate 晋升为 promoted。旧策略指纹下的经验不会被当前策略复用或用于跳过用例。

已晋升经验出现业务失败后会进入 quarantined；候选经验连续出现两次业务失败也会被隔离。可识别的浏览器启动、导航和连接错误记为 infra_error，不会累积业务失败次数。默认不重试隔离用例，确需复核时显式使用 --retry-quarantined。

~~~powershell
python -m web_agent train --headless --resume
python -m web_agent train --headless --resume --retry-quarantined
~~~

--resume 只跳过当前课程与策略下已经 promoted 的用例。如果所选用例都已完成，命令正常返回退出码 0，且不会启动浏览器。

## 课程表要求

默认文件为 test_cases/webagent_test_case.xlsx，工作表名为“自动化测试用例”，必需列为：

| 用例ID | 起始网址 | 模块 | 测试场景 | 优先级 | 前置条件 | 操作步骤 | 期望结果 | 是否执行 |
|---|---|---|---|---|---|---|---|---|

建议把期望结果写成可独立观察的断言，例如：

- 显示：顾客档案、美际学院、案例管理、设置
- URL 包含 /customer/U
- 跳转到顾客档案列表页

“操作成功”“显示正确”“搜索结果”等模糊期望会被 fail-closed 标记为能力缺口。需要固定数据的用例应引用脱敏 fixture，不要把手机号、邮箱或真实顾客信息写进工作簿。

## 产物与退出码

- JSON 报告：report/training/latest.json
- SQLite 记忆：memory/web_agent_training.db
- 运行报告、数据库及其 WAL/SHM 文件均由 Git 忽略。

退出码含义：

- 0：校验存在可运行用例；或训练全部通过；或 --resume 发现所选用例均已晋升。
- 1：执行出现失败、无证据成功、不可晋升成功或基础设施错误。
- 2：没有可运行用例。
