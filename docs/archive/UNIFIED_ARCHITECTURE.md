# 统一 Smart Agent 架构

正式入口：

```powershell
python ai_test.py explore
python ai_test.py explore --headless
python ai_test.py regression --headless
python ai_test.py capabilities
```

`UnifiedSmartRunner` 通过构造器直接持有所有依赖，不修改 `base_runner`、
`TaskBlackboard`、`ExecutorAgent` 或 `PlaywrightExecutor` 等模块全局对象。旧入口
仅作为兼容层保留，新开发应使用 `ai_test.py`。

模型上下文中的真实账号密码会转换为 `{{credential.username}}` 和
`{{credential.password}}`，只有在受控 Playwright 工具执行前才由本地
`CredentialVault` 注入真实值。

类型化验收示例：

```json
{
  "url_contains": "/customer",
  "title_contains": "顾客档案",
  "text_contains": ["顾客档案", "顾客列表"],
  "elements": [{"role": "heading", "name": "顾客档案"}]
}
```
