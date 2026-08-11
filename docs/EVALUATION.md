# Web 测试智能体评测

评测命令用于衡量探索智能体的真实完成质量，而不只统计进程是否退出成功。

## 运行

```powershell
python -m web_agent benchmark --headless
python -m web_agent benchmark --headless --repeat 3 --suite customer-baseline
python -m web_agent benchmark --headless --output report/benchmarks/customer.json
```

默认读取 `test_cases/explore_cases.xlsx`，每条用例重复执行两次。报告写入
`report/benchmarks/latest.json`，该目录属于运行产物，不提交到 Git。

## 指标

| 指标 | 含义 |
|---|---|
| `pass_rate` | 智能体报告成功的运行比例 |
| `evidence_backed_pass_rate` | 所有步骤均由 Verifier 通过且包含可观察证据的比例 |
| `unsupported_pass_rate` | 智能体报告成功但缺少完整验证证据的比例 |
| `recovery_success_rate` | 出现失败动作或重规划后最终恢复成功的比例 |
| `reproducibility_rate` | 同一用例重复执行时结果保持一致的比例 |
| `average_actions` | 平均浏览器动作数 |
| `average_model_calls` | 平均模型调用数 |
| `average_critic_revisions` | Critic 在执行前修订或替换候选动作的平均次数 |
| `average_duration_seconds` | 平均运行耗时 |

`unsupported_pass` 是误通过风险的自动代理指标，不等同于完整的独立业务
Oracle。后续接入接口、数据库或网络响应 Oracle 后，才能测量真正的业务误通过率。

## 质量门禁

命令只有在以下条件全部满足时返回退出码 `0`：

- 至少执行了一条用例；
- 所有运行均成功；
- 不存在缺少 Verifier 证据的成功运行。

单次运行无法证明可复现性，因此 `--repeat 1` 的
`reproducibility_rate` 为 `null`，而不是虚假报告为 100%。

## 建议的基线集

基线集应逐步扩充到至少 30 条真实场景，覆盖登录、表单、搜索、筛选、分页、
弹窗、动态下拉、表格、新标签页、iframe、上传下载、异常提示、超时和权限边界。
每次优化前后使用同一套用例和环境比较指标，避免凭单条成功案例判断能力提升。
