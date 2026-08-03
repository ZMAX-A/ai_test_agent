"""
Playwright 动作执行器 — 结构化结果 + 错误分类

所有 execute() 返回统一格式:
  {
    "success": bool,
    "error_type": "ELEMENT_NOT_FOUND" | "NOT_ENABLED" | "NOT_VISIBLE" |
                  "TIMEOUT" | "ASSERT_FAILED" | "UNKNOWN_ERROR" | "",
    "message": str,
    "page_change": {  # 仅 success=True 时填充
      "url_changed": bool,
      "new_url": str,
      "page_title": str,
      "toast_text": str,      # Ant Design message / 页面提示文字
    },
    "context": {  # 失败时附加上下文
      "locator_method": str,
      "wait_timeout_ms": int,
      "current_url": str,
      "visible_error_text": str,
    }
  }
"""
import os, re
from datetime import datetime
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from config.settings import settings
from perception.visual_sensor import VisualSensor


# ═══════════════════════════════════════════════
#  错误类型枚举
# ═══════════════════════════════════════════════
ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
NOT_ENABLED = "NOT_ENABLED"
NOT_VISIBLE = "NOT_VISIBLE"
TIMEOUT = "TIMEOUT"
ASSERT_FAILED = "ASSERT_FAILED"
UNKNOWN_ERROR = "UNKNOWN_ERROR"


def _ok(msg: str, page_change: dict = None) -> dict:
    return {"success": True, "error_type": "", "message": msg,
            "page_change": page_change or {}, "context": {}}


def _fail(error_type: str, msg: str, context: dict = None) -> dict:
    return {"success": False, "error_type": error_type, "message": msg,
            "page_change": {}, "context": context or {}}


class PlaywrightExecutor:
    """动作执行器：将JSON动作映射为Playwright真实操作，返回结构化结果"""

    def __init__(self, page: Page, visual_sensor: VisualSensor = None, screenshot_dir: str = None):
        self.page = page
        self.visual_sensor = visual_sensor or VisualSensor()
        if screenshot_dir:
            self.screenshot_dir = screenshot_dir
        else:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.screenshot_dir = os.path.join(project_root, "screenshots")
        os.makedirs(self.screenshot_dir, exist_ok=True)
        self._last_url = ""

    # ── 页面变化快照 ──────────────────────────────

    def _snapshot_page_change(self) -> dict:
        """捕获当前页面关键变化"""
        try:
            current_url = self.page.url
            url_changed = (current_url != self._last_url)
            self._last_url = current_url
            title = self.page.title() or ""
            toast = ""
            try:
                toast_el = self.page.locator(".ant-message-notice, .ant-notification-notice, [class*='toast'], [class*='message']").first
                if toast_el.count() > 0:
                    toast = (toast_el.inner_text(timeout=1000) or "")[:200]
            except Exception:
                pass
            return {"url_changed": url_changed, "new_url": current_url,
                    "page_title": title, "toast_text": toast}
        except Exception:
            return {}

    def _get_error_context(self, locator_info: str = "") -> dict:
        """失败时收集上下文"""
        ctx = {"locator_method": locator_info, "wait_timeout_ms": settings.ACTION_TIMEOUT}
        try:
            ctx["current_url"] = self.page.url
        except Exception:
            ctx["current_url"] = ""
        try:
            body = self.page.locator("body").inner_text(timeout=1000) or ""
            # 提取可见的错误/提示文本
            errors = re.findall(r'(错误|失败|异常|请\S{1,20}|必须\S{1,20})', body[:500])
            ctx["visible_error_text"] = "; ".join(errors[:3]) if errors else ""
        except Exception:
            ctx["visible_error_text"] = ""
        return ctx

    def _capture_fail_screenshot(self, action_name: str) -> str:
        try:
            ts = datetime.now().strftime("%H%M%S_%f")[:15]
            filename = f"fail_{ts}_{action_name}.png"
            filepath = os.path.join(self.screenshot_dir, filename)
            self.page.screenshot(path=filepath)
            return filepath
        except Exception:
            return ""

    # ── Locator 构建 ──────────────────────────────

    def _build_locator(self, params: dict):
        # som_index 优先（视觉标注的精准索引），不合并 role 避免 strict mode
        if "som_index" in params:
            idx = int(params["som_index"])
            return self.page.locator(f'[data-som-index="{idx}"]')
        locator_kwargs = {"role": params.get("role", "")}
        if params.get("name"):
            locator_kwargs["name"] = params["name"]
        locator = self.page.get_by_role(**locator_kwargs)
        if "index" in params:
            locator = locator.nth(int(params["index"]))
        return locator

    def get_css_selector(self, params: dict, action: str = "") -> str:
        role = params.get("role", "")
        name = params.get("name", "")
        idx = params.get("index", "")
        som = params.get("som_index", "")
        if som:
            # som_index 仅探索时有效，回归模式用通用选择器兜底
            if action in ("fill", "input"):
                return "input, textarea, [contenteditable]"
            elif action in ("click",):
                return "button, a, [role=button], [role=link]"
            return "input, button, a, textarea, select"
        if role == "textbox":
            if idx: return f"input[type='text']:nth-of-type({int(idx)+1})"
            return "input[type='text']"
        elif role == "searchbox": return "input[type='search']"
        elif role == "button":
            if name: return f"button:has-text('{name}')"
            return "button"
        elif role == "link":
            if name: return f"a:has-text('{name}')"
            return "a"
        elif role == "combobox": return ".ant-select-selector"
        elif role == "checkbox": return "input[type='checkbox']"
        elif role == "radio": return "input[type='radio']"
        elif name: return f"*:has-text('{name}')"
        return role or "*"

    # ═══════════════════════════════════════════════
    #  主入口 — 返回结构化结果
    # ═══════════════════════════════════════════════

    def execute(self, action_info: dict) -> dict:
        action = action_info.get("action")
        params = action_info.get("parameters", {})
        thought = action_info.get("thought", "")
        cached = action_info.get("cached_strategy")

        if cached and action in ("click", "fill") and "som_index" not in params:
            old_role = params.get("role", "?")
            params["role"] = cached["role"]
            if cached.get("name"): params["name"] = cached["name"]
            print(f"[CACHE] 缓存加速：{old_role} → {cached['role']}/{cached.get('name','')}")

        print(f"[BOT] 思考：{thought}")
        print(f"[CONFIG] {action} | {params}")

        try:
            # ── 无需定位器 ──
            if action == "finish":
                return _ok(f"步骤完成：{params.get('result')}", self._snapshot_page_change())

            elif action == "assert_url":
                current_url = self.page.url
                expect = params.get("expect_url_contains", "")
                if expect in current_url:
                    return _ok(f"URL断言通过：{current_url}", self._snapshot_page_change())
                sp = self._capture_fail_screenshot("assert_url")
                return _fail(ASSERT_FAILED, f"URL断言失败：期望含「{expect}」，当前={current_url}",
                             {**self._get_error_context("url_check"), "screenshot": sp})

            elif action == "assert_title":
                current_title = self.page.title()
                expect = params.get("expect_title_contains", "")
                if expect in current_title:
                    return _ok(f"标题断言通过：{current_title}", self._snapshot_page_change())
                sp = self._capture_fail_screenshot("assert_title")
                return _fail(ASSERT_FAILED, f"标题断言失败：期望含「{expect}」，当前={current_title}",
                             {**self._get_error_context("title_check"), "screenshot": sp})

            elif action == "assert_visual":
                is_match, msg = self.visual_sensor.check_page_match(self.page, params["expect_desc"])
                if is_match:
                    return _ok(msg, self._snapshot_page_change())
                return _fail(ASSERT_FAILED, msg, self._get_error_context("visual_check"))

            elif action == "scroll":
                offset = 600 if params.get("direction") == "down" else -600
                self.page.evaluate(f"window.scrollBy(0, {offset})")
                return _ok("滚动完成", self._snapshot_page_change())

            # ── 需要定位器 ──
            locator = self._build_locator(params)
            locator_info = f"role={params.get('role','?')}, name={params.get('name','?')}, index={params.get('index','?')}"

            # ── select_option: 键盘优先（快），文本定位兜底 ──
            if action == "select_option":
                # 1) 点击 combobox 展开下拉
                try:
                    locator.wait_for(state="visible", timeout=3000)
                    locator.click(timeout=3000)
                except PlaywrightTimeoutError:
                    pass
                self.page.wait_for_timeout(350)

                option_text = params.get("option_text", "")

                # 2) 键盘优先 — 速度快、兼容所有自定义下拉
                try:
                    self.page.keyboard.press("ArrowDown")
                    self.page.wait_for_timeout(200)
                    if option_text:
                        found = False
                        for _ in range(30):
                            try:
                                active = self.page.locator(":focus").first
                                active_text = (active.text_content() or "").strip()
                                if option_text in active_text:
                                    self.page.keyboard.press("Enter")
                                    self.page.wait_for_timeout(200)
                                    return _ok(f"已键盘选择: {option_text}", self._snapshot_page_change())
                            except Exception:
                                pass
                            self.page.keyboard.press("ArrowDown")
                            self.page.wait_for_timeout(100)
                        self.page.keyboard.press("Enter")
                        self.page.wait_for_timeout(200)
                        return _ok(f"键盘选到底(未匹配'{option_text}')，已选当前项", self._snapshot_page_change())
                    else:
                        self.page.keyboard.press("Enter")
                        self.page.wait_for_timeout(200)
                        return _ok("已选下拉第一项（键盘）", self._snapshot_page_change())
                except Exception as e:
                    pass  # 键盘失败→文本兜底

                # 3) 文本定位兜底
                if option_text:
                    for strategy in [
                        lambda: self.page.get_by_text(option_text).first,
                        lambda: self.page.locator(f"text={option_text}").first,
                        lambda: self.page.locator(f"li:has-text('{option_text}')").first,
                        lambda: self.page.locator(f"div:has-text('{option_text}')").first,
                        lambda: self.page.locator(f".ant-select-item-option:has-text('{option_text}')").first,
                    ]:
                        try:
                            opt = strategy()
                            opt.click(timeout=2000, force=True)
                            return _ok(f"已文本选择: {option_text}", self._snapshot_page_change())
                        except Exception:
                            continue
                    return _fail(ELEMENT_NOT_FOUND, f"找不到下拉选项: {option_text}",
                                 self._get_error_context(locator_info))
                return _ok("已处理下拉", self._snapshot_page_change())

            # ── click ──
            elif action == "click":
                name = params.get("name", "")
                # ── 尝试1: role定位 ──
                try:
                    locator.wait_for(state="visible", timeout=settings.ACTION_TIMEOUT)
                except PlaywrightTimeoutError:
                    pass  # 不立即失败，尝试文本兜底
                else:
                    try:
                        locator.click(timeout=settings.ACTION_TIMEOUT)
                        return _ok("点击成功", self._snapshot_page_change())
                    except PlaywrightTimeoutError:
                        pass
                    except Exception as e:
                        if "not enabled" in str(e).lower() or "disabled" in str(e).lower():
                            return _fail(NOT_ENABLED, f"元素不可交互: {e}", self._get_error_context(locator_info))

                # ── 尝试2: 文本定位兜底 ──
                if name:
                    # 多匹配策略：取所有匹配元素，逐个尝试点击
                    all_matches = []
                    try:
                        all_matches = self.page.locator(f"text={name}").all()
                    except Exception:
                        pass

                    if not all_matches:
                        try:
                            all_matches = self.page.get_by_text(name, exact=False).all()
                        except Exception:
                            pass

                    # 排序：可交互元素优先（a > li > button > menuitem > 其他）
                    def _priority(el):
                        try:
                            tag = el.evaluate("el => el.tagName.toLowerCase()")
                            role = el.get_attribute("role") or ""
                            cls = (el.get_attribute("class") or "").lower()
                            has_click = "cursor:pointer" in (el.get_attribute("style") or "")
                            if tag in ("a", "button") or role in ("link", "button", "menuitem"):
                                return 0
                            if tag in ("li", "span") and ("menu" in cls or "nav" in cls or "item" in cls):
                                return 1
                            if has_click:
                                return 2
                            return 3
                        except Exception:
                            return 3

                    all_matches.sort(key=_priority)

                    for idx, el in enumerate(all_matches):
                        try:
                            el.wait_for(state="visible", timeout=1000)
                            el.click(timeout=3000)
                            return _ok(f"点击成功(文本匹配[{idx}]): {name}", self._snapshot_page_change())
                        except Exception:
                            continue

                    # 全部失败 → 用第一个 force click
                    if all_matches:
                        try:
                            all_matches[0].click(force=True, timeout=3000)
                            return _ok(f"点击成功(force): {name}", self._snapshot_page_change())
                        except Exception:
                            sp = self._capture_fail_screenshot("click")
                            return _fail(NOT_VISIBLE, f"文本'{name}'匹配{len(all_matches)}个元素但全部不可点击",
                                         {**self._get_error_context(f"text={name}"), "screenshot": sp})

                sp = self._capture_fail_screenshot("click")
                return _fail(NOT_VISIBLE, f"元素不可见/超时 (role={params.get('role','')}, name={name})",
                             {**self._get_error_context(locator_info), "screenshot": sp})
                return _ok("点击成功", self._snapshot_page_change())

            # ── fill ──
            elif action == "fill":
                try:
                    locator.wait_for(state="visible", timeout=settings.ACTION_TIMEOUT)
                except PlaywrightTimeoutError:
                    sp = self._capture_fail_screenshot("fill")
                    return _fail(NOT_VISIBLE, "输入框不可见/超时",
                                 {**self._get_error_context(locator_info), "screenshot": sp})
                try:
                    locator.fill(params["value"], timeout=settings.ACTION_TIMEOUT)
                except PlaywrightTimeoutError:
                    sp = self._capture_fail_screenshot("fill")
                    return _fail(TIMEOUT, "输入超时",
                                 {**self._get_error_context(locator_info), "screenshot": sp})
                except Exception as e:
                    sp = self._capture_fail_screenshot("fill")
                    return _fail(UNKNOWN_ERROR, f"输入异常: {e}",
                                 {**self._get_error_context(locator_info), "screenshot": sp})
                return _ok(f"输入成功：{params['value']}", self._snapshot_page_change())

            # ── assert_text ──
            elif action == "assert_text":
                try:
                    locator.wait_for(state="visible", timeout=settings.ACTION_TIMEOUT)
                    text = locator.text_content(timeout=settings.ACTION_TIMEOUT)
                except PlaywrightTimeoutError:
                    return _fail(NOT_VISIBLE, "断言元素不可见",
                                 self._get_error_context(locator_info))
                expect = params.get("expect_text", "")
                if expect in text:
                    return _ok("文本断言通过", self._snapshot_page_change())
                sp = self._capture_fail_screenshot("assert_text")
                return _fail(ASSERT_FAILED, f"文本断言失败：期望含「{expect}」，实际={text[:200]}",
                             {**self._get_error_context(locator_info), "screenshot": sp})

            # ── 新增工具动作 ──
            elif action == "go_back":
                self.page.go_back()
                self.page.wait_for_load_state("domcontentloaded", timeout=5000)
                return _ok("已返回上一页", self._snapshot_page_change())

            elif action == "refresh":
                self.page.reload()
                self.page.wait_for_load_state("domcontentloaded", timeout=10000)
                return _ok("页面已刷新", self._snapshot_page_change())

            elif action == "goto":
                url = params.get("url", "")
                if not url:
                    return _fail(UNKNOWN_ERROR, "goto 缺少 url 参数", {})
                # 自动补全相对路径
                if url.startswith("/"):
                    try:
                        base = self.page.url.rstrip("/")
                        # 去掉路径部分取协议+域名
                        from urllib.parse import urlparse
                        parsed = urlparse(base)
                        url = f"{parsed.scheme}://{parsed.netloc}{url}"
                    except Exception:
                        pass
                try:
                    self.page.goto(url, timeout=settings.PAGE_TIMEOUT)
                    self.page.wait_for_load_state("networkidle", timeout=8000)
                    return _ok(f"已导航到: {url}", self._snapshot_page_change())
                except Exception as e:
                    return _fail(UNKNOWN_ERROR, f"导航失败: {e}", self._get_error_context("goto"))

            elif action == "scroll_to_element":
                try:
                    locator.wait_for(state="attached", timeout=3000)
                    locator.scroll_into_view_if_needed()
                    return _ok("已滚动到元素", self._snapshot_page_change())
                except PlaywrightTimeoutError:
                    return _fail(ELEMENT_NOT_FOUND, "目标元素不存在，无法滚动",
                                 self._get_error_context(locator_info))

            elif action == "close_popup":
                closed = False
                for sel in [
                    ".ant-modal-close", ".ant-drawer-close",
                    "button:has-text('知道了')", "button:has-text('确定')",
                    "button:has-text('关闭')", ".ant-message-notice-close",
                    "[aria-label='Close']", "[aria-label='close']",
                ]:
                    try:
                        el = self.page.locator(sel).first
                        if el.is_visible(timeout=500):
                            el.click(timeout=2000)
                            closed = True
                            print(f"  [POPUP] 已关闭: {sel}")
                            self.page.wait_for_timeout(300)
                            break
                    except Exception:
                        continue
                if closed:
                    return _ok("已关闭弹窗", self._snapshot_page_change())
                return _ok("未检测到可关闭的弹窗", self._snapshot_page_change())

            elif action == "get_element_attr":
                try:
                    attr_name = params.get("attr_name", "innerText")
                    locator.wait_for(state="attached", timeout=3000)
                    if attr_name in ("innerText", "textContent", "text"):
                        val = locator.inner_text(timeout=3000)
                    else:
                        val = locator.get_attribute(attr_name, timeout=3000)
                    return _ok(f"属性值: {str(val)[:200]}", self._snapshot_page_change())
                except PlaywrightTimeoutError:
                    return _fail(ELEMENT_NOT_FOUND, f"元素不存在",
                                 self._get_error_context(locator_info))

            elif action == "get_page_info":
                info = {
                    "url": self.page.url,
                    "title": self.page.title() or "",
                }
                return _ok(f"URL={info['url']}, Title={info['title']}", info)

            else:
                return _fail(UNKNOWN_ERROR, f"不支持的动作：{action}")

        except PlaywrightTimeoutError:
            sp = self._capture_fail_screenshot(action or "timeout")
            return _fail(TIMEOUT, "操作超时",
                         {**self._get_error_context(""), "screenshot": sp})
        except Exception as e:
            sp = self._capture_fail_screenshot(action or "exception")
            return _fail(UNKNOWN_ERROR, f"执行异常：{str(e)}",
                         {**self._get_error_context(""), "screenshot": sp})
