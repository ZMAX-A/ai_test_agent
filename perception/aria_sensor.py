import re
from playwright.sync_api import Page
from perception.base_sensor import BaseSensor


class AriaSensor(BaseSensor):
    """主链路感知：获取页面无障碍语义树，轻量高效

    增强：返回前过滤掉非交互元素，减少 Token 与干扰信息。
    只保留 button / textbox / link / combobox / textarea / checkbox / radio
    """

    # 白名单：保留这些角色及其子树（含弹窗/下拉/菜单等障碍元素）
    KEEP_ROLES = frozenset({
        'button', 'textbox', 'link', 'combobox',
        'textarea', 'checkbox', 'radio',
        # ── 障碍物感知：下拉选项、弹窗、菜单 ──
        'listbox', 'option', 'listitem', 'menuitem', 'menu', 'menubar',
        'dialog', 'alertdialog', 'alert',
        # ── 页面结构：标签页、树、表格 ──
        'tab', 'tabpanel', 'tablist',
        'tree', 'treeitem', 'gridcell', 'row',
        'heading', 'searchbox', 'spinbutton', 'switch',
        'separator', 'tooltip',
    })

    @staticmethod
    def _filter_aria_snapshot(snapshot: str) -> str:
        """保留交互元素及其子树，过滤纯文本/装饰性节点。

        Playwright aria_snapshot 是类 YAML 的缩进树结构：
          - text "Hello"          ← 过滤（纯文本）
          - button "Search"       ← 保留
            - text "Search"       ← 保留（交互元素的子树）
          - heading "Title"       ← 过滤
        """
        lines = snapshot.split('\n')
        result = []
        keep_indent = -1  # -1 = 不在保留子树中

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if keep_indent >= 0:
                    result.append(line)
                continue

            indent = len(line) - len(line.lstrip())

            # 提取行首角色名："- role "name""
            m = re.match(r'^- (\w+)', stripped)
            role = m.group(1).lower() if m else ''

            if role in AriaSensor.KEEP_ROLES:
                keep_indent = indent
                result.append(line)
            elif keep_indent >= 0 and indent > keep_indent:
                # 交互元素的子树 → 保留
                result.append(line)
            else:
                # 离开交互子树 → 重置
                keep_indent = -1

        return '\n'.join(result) if result else snapshot

    def capture(self, page: Page) -> str:
        try:
            snapshot = page.locator("body").aria_snapshot()
            filtered = self._filter_aria_snapshot(snapshot)
            return filtered
        except Exception as e:
            return f"[Aria快照获取失败] {str(e)}"