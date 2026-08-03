"""带可验证下拉选择的 PlaywrightExecutor。

复用历史执行器的其他动作，只替换 select_option，消除“键盘按下即成功”的假阳性。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


_LEGACY_PATH = Path(__file__).resolve().parent.parent / "playwright_exec.py"
_SPEC = importlib.util.spec_from_file_location("executor._legacy_playwright_exec", _LEGACY_PATH)
_LEGACY = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_LEGACY)


class PlaywrightExecutor(_LEGACY.PlaywrightExecutor):
    """下拉选择必须点击真实选项并取得可观察的选中标签。"""

    OPTION_SELECTOR = (
        ".ant-select-item-option:not(.ant-select-item-option-disabled), "
        "[role='option']:not([aria-disabled='true']), "
        ".el-select-dropdown__item:not(.is-disabled)"
    )

    def execute(self, action_info: dict) -> dict:
        if action_info.get("action") != "select_option":
            return super().execute(action_info)

        params = action_info.get("parameters", {})
        option_text = str(params.get("option_text", "") or "").strip()
        locator = self._build_locator(params)
        locator_info = (
            f"role={params.get('role','?')}, name={params.get('name','?')}, "
            f"index={params.get('index','?')}"
        )
        try:
            locator.wait_for(state="visible", timeout=3000)
            locator.click(timeout=3000)
            self.page.wait_for_timeout(400)

            options = self.page.locator(self.OPTION_SELECTOR)
            candidates = []
            for index in range(options.count()):
                item = options.nth(index)
                try:
                    if not item.is_visible(timeout=500):
                        continue
                    label = (item.inner_text(timeout=1000) or "").strip()
                    if not label:
                        continue
                    candidates.append((item, label))
                except Exception:
                    continue

            if option_text:
                candidates = [pair for pair in candidates if option_text in pair[1]]
            if not candidates:
                expected = option_text or "第一个可见有效选项"
                return _LEGACY._fail(
                    _LEGACY.ELEMENT_NOT_FOUND,
                    f"找不到下拉选项: {expected}",
                    self._get_error_context(locator_info),
                )

            option, clicked_label = candidates[0]
            option.click(timeout=3000)
            self.page.wait_for_timeout(400)

            selected_labels = []
            selected = self.page.locator(
                ".ant-select-selection-item, "
                ".ant-select-item-option-selected, "
                "[role='option'][aria-selected='true']"
            )
            for index in range(selected.count()):
                try:
                    label = (selected.nth(index).inner_text(timeout=500) or "").strip()
                    if label:
                        selected_labels.append(label)
                except Exception:
                    continue

            if not any(clicked_label in label or label in clicked_label for label in selected_labels):
                return _LEGACY._fail(
                    _LEGACY.ASSERT_FAILED,
                    f"下拉点击后未回读到选中状态: {clicked_label}",
                    self._get_error_context(locator_info),
                )
            return _LEGACY._ok(
                f"已选择并回读确认: {clicked_label}", self._snapshot_page_change()
            )
        except Exception as exc:
            return _LEGACY._fail(
                _LEGACY.UNKNOWN_ERROR,
                f"下拉选择异常: {exc}",
                self._get_error_context(locator_info),
            )


__all__ = ["PlaywrightExecutor"]
