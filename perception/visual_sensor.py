"""
视觉多模态感知模块（SoM Set-of-Mark 增强版）

设计思路：
  借鉴 browser-use 的核心算法理念，但 100% 使用 Playwright JS 注入 + Pillow 后处理实现，
  不依赖 CDP 协议、不引入 browser-use 库。

核心改进（对比旧版）：
  1. JS 只读抽取元素，Pillow 后处理绘制标注 → 零 DOM 侵入，截图即干净页，无需清理
  2. 元素可交互性多维度检测：标签 / ARIA role / cursor:pointer / 事件处理器 / tabindex
  3. 分类着色虚线框：按钮(红)、输入框(青)、链接(绿)、下拉框(蓝)、文本域(橙)、默认(紫)
  4. 智能编号定位：大元素编号在左上角内部，小元素在正上方，自动适配边界
  5. 优先级排序 + 视口裁剪 + 隐藏/禁用元素过滤
"""

import base64
import io
import json
import logging
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import Page

from perception.base_sensor import BaseSensor
from openai import OpenAI
from config.settings import settings
from utils.json_utils import safe_parse_json

logger = logging.getLogger(__name__)


# ============================================================
# 一、JS 元素信息抽取脚本
# ============================================================
EXTRACT_ELEMENTS_JS = r"""
(() => {
  const dpr = window.devicePixelRatio || 1;
  const vw = window.innerWidth, vh = window.innerHeight;
  const elements = [];
  const all = document.querySelectorAll('*');

  // --- 跳过标签 ---
  const SKIP_TAGS = new Set([
    'script','style','head','meta','link','title','br','hr','noscript',
    'svg','path','g','circle','ellipse','line','polyline','polygon','defs',
    'iframe','frame','canvas','template','slot',
  ]);

  for (const el of all) {
    try {
      const tag = el.tagName.toLowerCase();
      if (SKIP_TAGS.has(tag)) continue;

      const r = el.getBoundingClientRect();
      if (r.width < 6 || r.height < 6) continue;
      if (r.top > vh - 5 || r.bottom < 5 || r.left > vw - 5 || r.right < 5) continue;

      const cs = window.getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) <= 0) continue;
      if (el.disabled === true || el.getAttribute('aria-disabled') === 'true') continue;

      const role     = (el.getAttribute('role') || '').toLowerCase();
      const ariaLabel = (el.getAttribute('aria-label') || '').trim();
      const typeAttr = (el.getAttribute('type') || '').toLowerCase();
      const placeholder = (el.getAttribute('placeholder') || '').trim();
      const tabindex = el.getAttribute('tabindex');
      const val      = (el.value !== undefined && el.value !== null) ? String(el.value) : '';
      const text     = (el.innerText || '').trim();
      const cursor   = cs.cursor;

      const hasHandler = !!(
        el.onclick || el.onmousedown || el.onmouseup ||
        el.getAttribute('onclick') || el.getAttribute('onmousedown') || el.getAttribute('onkeydown')
      );

      const interactiveTags = new Set([
        'button','input','select','textarea','a','details','summary','label','option','optgroup',
      ]);
      const interactiveRoles = new Set([
        'button','link','checkbox','radio','textbox','combobox','searchbox',
        'menuitem','tab','option','slider','switch','search','spinbutton',
        'dialog','alertdialog','menu','listbox','tree','gridcell',
      ]);

      const isInteractive = (
        interactiveTags.has(tag) ||
        interactiveRoles.has(role) ||
        cursor === 'pointer' ||
        hasHandler ||
        (tabindex !== null && parseInt(tabindex) >= 0) ||
        (el.id && (el.id.toLowerCase().includes('search') || el.id.toLowerCase().includes('btn'))) ||
        (el.className && typeof el.className === 'string' &&
         (el.className.toLowerCase().includes('search') || el.className.toLowerCase().includes('btn')))
      );

      if (!isInteractive) continue;

      elements.push({
        el: el,
        data: {
          idx: 0,
          tag: tag,
          x:  Math.round(r.left),
          y:  Math.round(r.top),
          w:  Math.round(r.width),
          h:  Math.round(r.height),
          text:  text.slice(0, 80),
          role:  role,
          ariaLabel: ariaLabel.slice(0, 60),
          type:  typeAttr,
          placeholder: placeholder.slice(0, 40),
          value: val.slice(0, 40),
          hasHandler: hasHandler,
          cursor: cursor,
          tabindex: tabindex || '',
        }
      });
    } catch (_) { /* 单元素异常跳过 */ }
  }

  // ---- 按交互优先级 + 位置排序 ----
  const TAG_PRIORITY = {
    button: 5, input: 5, a: 4, select: 4, textarea: 4,
    label: 3, details: 2, summary: 2, option: 2, optgroup: 2,
  };
  for (const item of elements) {
    const e = item.data;
    let s = (TAG_PRIORITY[e.tag] || 1) * 2;
    if (e.hasHandler)          s += 3;
    if (e.cursor === 'pointer') s += 2;
    if (e.role)                 s += 1;
    if (e.text || e.ariaLabel || e.placeholder) s += 1;
    e._score = s;
  }
  elements.sort((a, b) => b.data._score - a.data._score || a.data.y - b.data.y || a.data.x - b.data.x);

  // 分配序号 + 注入 data-som-index DOM 属性（供 Playwright 定位使用）
  elements.forEach((item, i) => {
    item.data.idx = i + 1;
    try { item.el.dataset.somIndex = String(item.data.idx); } catch (_) {}
    delete item.data._score;
  });

  // 返回纯数据（不含 DOM 引用）
  var result = { dpr: dpr, elements: elements.map(function(item) { return item.data; }) };
  return JSON.stringify(result);
})();
"""


# ============================================================
# 二、元素类型 → 视觉颜色映射
# ============================================================
ELEMENT_COLORS: dict[str, str] = {
    'button':   '#FF6B6B',   # 红色 —— 按钮
    'a':        '#96CEB4',   # 绿色 —— 链接
    'input':    '#4ECDC4',   # 青色 —— 输入框
    'select':   '#45B7D1',   # 蓝色 —— 下拉框
    'textarea': '#FF8C42',   # 橙色 —— 文本域
    'label':    '#DDA0DD',   # 紫色 —— 标签
    'default':  '#DDA0DD',   # 紫色 —— 其他可交互元素
}


def _get_element_color(tag: str, role: str = '', type_attr: str = '') -> str:
    """根据元素标签和 ARIA role 返回对应的标注颜色。"""
    if tag == 'input' and type_attr in ('button', 'submit', 'reset'):
        return ELEMENT_COLORS['button']
    if tag == 'input':
        return ELEMENT_COLORS['input']
    if role in ('button',):
        return ELEMENT_COLORS['button']
    if role in ('link',):
        return ELEMENT_COLORS['a']
    return ELEMENT_COLORS.get(tag, ELEMENT_COLORS['default'])


def _get_element_type_label(tag: str, role: str = '') -> str:
    """返回人类可读的中文元素类型名。"""
    label_map: dict[str, str] = {
        'button': '按钮', 'input': '输入框', 'select': '下拉框',
        'textarea': '文本域', 'a': '链接', 'label': '标签',
        'details': '详情', 'summary': '摘要',
    }
    if role:
        role_map: dict[str, str] = {
            'button': '按钮', 'link': '链接', 'textbox': '输入框',
            'combobox': '下拉框', 'searchbox': '搜索框', 'checkbox': '复选框',
            'radio': '单选', 'tab': '标签页', 'menuitem': '菜单项',
            'slider': '滑块', 'switch': '开关', 'search': '搜索',
            'dialog': '弹窗', 'listbox': '列表', 'tree': '树',
        }
        return role_map.get(role, label_map.get(tag, tag))
    return label_map.get(tag, tag)


# ============================================================
# 三、字体加载（跨平台 + 缓存）
# ============================================================
_FONT_CACHE: dict[int, ImageFont.FreeTypeFont | None] = {}


def _load_font(size: int = 14) -> ImageFont.FreeTypeFont | None:
    """加载系统字体，优先 Windows 字体，带缓存。"""
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]

    font_paths = [
        'C:/Windows/Fonts/arial.ttf',
        'C:/Windows/Fonts/msyh.ttc',
        'C:/Windows/Fonts/msyhbd.ttc',
        'arial.ttf',
        '/System/Library/Fonts/Arial.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf',
    ]
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, size)
            _FONT_CACHE[size] = font
            return font
        except Exception:
            continue
    _FONT_CACHE[size] = None
    return None


# ============================================================
# 四、Pillow 后处理标注绘制（虚线框 + 编号徽标）
# ============================================================

def _draw_dashed_rect(draw: ImageDraw.Draw,
                      x1: int, y1: int, x2: int, y2: int,
                      color: str, line_width: int = 2) -> None:
    """在截图上绘制虚线矩形边框（browser-use style）。"""
    dash = 4
    gap = 8

    # 上边
    x = x1
    while x < x2:
        end = min(x + dash, x2)
        draw.line([(x, y1), (end, y1)], fill=color, width=line_width)
        x += dash + gap
    # 下边
    x = x1
    while x < x2:
        end = min(x + dash, x2)
        draw.line([(x, y2), (end, y2)], fill=color, width=line_width)
        x += dash + gap
    # 左边
    y = y1
    while y < y2:
        end = min(y + dash, y2)
        draw.line([(x1, y), (x1, end)], fill=color, width=line_width)
        y += dash + gap
    # 右边
    y = y1
    while y < y2:
        end = min(y + dash, y2)
        draw.line([(x2, y), (x2, end)], fill=color, width=line_width)
        y += dash + gap


def _draw_index_badge(draw: ImageDraw.Draw,
                      x1: int, y1: int, x2: int, y2: int,
                      index_text: str,
                      font: ImageFont.FreeTypeFont | None,
                      image_size: tuple[int, int]) -> None:
    """绘制编号徽标：白色底 + 黑色文字 + 黑色边框，智能定位避免遮挡。"""
    try:
        if font:
            bbox = draw.textbbox((0, 0), index_text, font=font)
        else:
            bbox = draw.textbbox((0, 0), index_text)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        pad = 4

        ew = x2 - x1
        eh = y2 - y1
        img_w, img_h = image_size

        if ew < 60 or eh < 30:
            bx1 = x1 + (ew - tw - pad * 2) // 2
            by1 = y1 - th - pad * 2 - 2
        else:
            bx1 = x1 + 2
            by1 = y1 + 2

        bx2 = bx1 + tw + pad * 2
        by2 = by1 + th + pad * 2

        if bx1 < 2:
            shift = 2 - bx1
            bx1 += shift; bx2 += shift
        if by1 < 2:
            shift = 2 - by1
            by1 += shift; by2 += shift
        if bx2 > img_w - 2:
            shift = bx2 - (img_w - 2)
            bx1 -= shift; bx2 -= shift
        if by2 > img_h - 2:
            shift = by2 - (img_h - 2)
            by1 -= shift; by2 -= shift

        draw.rectangle([bx1, by1, bx2, by2], fill='white', outline='black', width=2)
        tx = bx1 + pad
        ty = by1 + pad - bbox[1]
        draw.text((tx, ty), index_text, fill='black', font=font)

    except Exception:
        logger.debug(f'Badge绘制异常(idx={index_text})', exc_info=True)


def _build_highlighted_screenshot(screenshot_bytes: bytes,
                                   elements: list[dict[str, Any]],
                                   device_pixel_ratio: float = 1.0) -> bytes:
    """在截图上绘制彩色虚线框 + 编号徽标，返回新的 PNG bytes。"""
    img = Image.open(io.BytesIO(screenshot_bytes)).convert('RGBA')
    draw = ImageDraw.Draw(img)
    font = _load_font(14)

    dpr = device_pixel_ratio or 1.0

    for el in elements:
        try:
            x1 = int(el['x'] * dpr)
            y1 = int(el['y'] * dpr)
            x2 = int((el['x'] + el['w']) * dpr)
            y2 = int((el['y'] + el['h']) * dpr)

            img_w, img_h = img.size
            x1 = max(0, min(x1, img_w - 1))
            y1 = max(0, min(y1, img_h - 1))
            x2 = max(x1 + 3, min(x2, img_w))
            y2 = max(y1 + 3, min(y2, img_h))

            if x2 - x1 < 4 or y2 - y1 < 4:
                continue

            color = _get_element_color(el['tag'], el.get('role', ''), el.get('type', ''))

            _draw_dashed_rect(draw, x1, y1, x2, y2, color, line_width=2)
            _draw_index_badge(draw, x1, y1, x2, y2, str(el['idx']), font, img.size)

        except Exception:
            logger.debug(f'元素 #{el.get("idx", "?")} 高亮绘制失败', exc_info=True)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


# ============================================================
# 五、结构化元素映射表构建
# ============================================================

def _build_element_map_text(elements: list[dict[str, Any]]) -> str:
    """构建「序号 → 元素类型 + 可见文本 + role」的结构化映射文本。"""
    lines = []
    for el in elements:
        type_label = _get_element_type_label(el['tag'], el.get('role', ''))
        label = (el.get('ariaLabel') or el.get('placeholder') or el.get('text') or el.get('value') or '')[:40]
        if label:
            lines.append(f"  #{el['idx']} [{type_label}] \"{label}\"")
        else:
            lines.append(f"  #{el['idx']} [{type_label}] (no label)")
    return '\n'.join(lines)


# ============================================================
# 六、VisualSensor 主类
# ============================================================

class VisualSensor(BaseSensor):
    """次链路兜底感知：SoM 页面元素彩色标注 → 截图 → 多模态大模型解析。

    流程：
      JS 抽取元素 + 注入 data-som-index DOM 属性
      → clean screenshot
      → Pillow 后处理绘制彩色虚线框 + 编号徽标
      → 结构化映射表 + 标注截图 → VL 模型
      → data-som-index 供 Playwright 精准定位
    """

    def __init__(self):
        self.vl_client = OpenAI(
            api_key=settings.VL_API_KEY or settings.LLM_API_KEY,
            base_url=settings.VL_BASE_URL or settings.LLM_BASE_URL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=settings.LLM_MAX_RETRIES,
        )
        self.vl_model = settings.VL_MODEL or settings.LLM_MODEL
        self.model_name = self.vl_model

    # ------------------------------------------------------------------
    # 公开接口（向下兼容）
    # ------------------------------------------------------------------

    def capture(self, page: Page, step_goal: str = '') -> str:
        """采集带 SoM 标注的页面快照，返回 VL 模型解析结果。

        Args:
            page:     Playwright Page 实例
            step_goal:  当前步骤目标（可选，用于 VL prompt 上下文）

        Returns:
            格式: "【SoM视觉感知结果】{VL推理结果}\n元素编号映射：{结构化映射}"
            异常时: "【SoM视觉感知异常】{错误信息}"
        """
        try:
            # ── Step 1: JS 抽取元素 + 注入 data-som-index ──
            raw = page.evaluate(EXTRACT_ELEMENTS_JS)
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            dpr = float(parsed.get('dpr', 1.0))
            elements: list[dict[str, Any]] = parsed.get('elements', [])

            if not elements:
                logger.info('未检测到可交互元素，使用干净截图')
                clean_bytes = page.screenshot(full_page=False)
                b64_img = base64.b64encode(clean_bytes).decode('utf-8')
                element_map_text = '（无标注元素）'
            else:
                clean_bytes = page.screenshot(full_page=False)

                highlighted_bytes = _build_highlighted_screenshot(
                    clean_bytes, elements, device_pixel_ratio=dpr,
                )
                b64_img = base64.b64encode(highlighted_bytes).decode('utf-8')

                element_map_text = _build_element_map_text(elements)

            goal_hint = f'\n当前步骤目标：{step_goal}' if step_goal else ''
            prompt = (
                '页面已对所有可交互元素标注彩色虚线框+数字编号，各颜色含义：\n'
                '  红色[按钮] 青色[输入框] 绿色[链接]\n'
                '  蓝色[下拉框] 橙色[文本域] 紫色[其他交互元素]\n\n'
                f'编号与元素映射：\n{element_map_text}'
                f'{goal_hint}\n\n'
                '请根据步骤目标，输出要操作元素的【序号】+元素类型+可见文字描述。'
                '后续程序根据序号精准定位元素，返回简洁文本即可。'
            )

            resp = self.vl_client.chat.completions.create(
                model=self.vl_model,
                temperature=0.05,
                messages=[{
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': prompt},
                        {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{b64_img}'}},
                    ],
                }],
            )
            res_text = resp.choices[0].message.content

            return (
                f'【SoM视觉感知结果】{res_text}\n'
                f'元素编号映射：{json.dumps({e["idx"]: {"tag": e["tag"], "text": (e.get("ariaLabel") or e.get("placeholder") or e.get("text",""))[:40], "role": e.get("role","")} for e in elements}, ensure_ascii=False)}'
            )

        except Exception as e:
            logger.error(f'视觉感知异常: {e}', exc_info=True)
            return f'【SoM视觉感知异常】{e}'

    def check_page_match(self, page: Page, expect_desc: str) -> tuple[bool, str]:
        """视觉断言：截图让 VL 模型判断页面是否符合预期描述（assert_visual 底层实现）。"""
        try:
            screenshot_bytes = page.screenshot(full_page=False)
            b64_img = base64.b64encode(screenshot_bytes).decode('utf-8')

            prompt = (
                f'判断当前截图是否符合以下描述：{expect_desc}\n'
                '只返回纯JSON：{"match": true/false, "reason": "简短说明"}'
            )

            resp = self.vl_client.chat.completions.create(
                model=self.vl_model,
                temperature=0,
                messages=[{
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': prompt},
                        {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{b64_img}'}},
                    ],
                }],
            )
            result = safe_parse_json(resp.choices[0].message.content)
            return bool(result.get('match', False)), str(result.get('reason', '视觉校验完成'))
        except Exception as e:
            return False, f'视觉校验异常：{e}'
