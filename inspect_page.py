"""探查顾客档案页面"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()
from playwright.sync_api import sync_playwright

LOGIN_URL = os.environ.get('LOGIN_URL', '')
USERNAME = os.environ.get('LOGIN_USERNAME', '')
PASSWORD = os.environ.get('LOGIN_PASSWORD', '')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
    context = browser.new_context(no_viewport=True)
    page = context.new_page()
    page.goto(LOGIN_URL, timeout=30000)
    page.wait_for_timeout(2000)

    # Login
    for i, val in enumerate([USERNAME, PASSWORD]):
        el = page.locator('input').nth(i)
        if el.count(): el.fill(val)
    page.wait_for_timeout(300)

    for sel in ['[role=combobox]', '.ant-select-selector']:
        cb = page.locator(sel)
        if cb.count():
            cb.first.click()
            page.wait_for_timeout(500)
            opt = page.locator('.ant-select-item-option').first
            if opt.count():
                opt.click()
                page.wait_for_timeout(500)
            break

    btn = page.locator('button[type=submit], button:has-text("登")')
    if btn.count():
        btn.first.click()
    page.wait_for_timeout(3000)

    print(f'首页 URL: {page.url}')
    print(f'首页 Title: {page.title()}')

    # 尝试直接访问 /customer
    page.goto(LOGIN_URL.rstrip('/login') + '/customer', timeout=30000)
    page.wait_for_timeout(2000)
    print(f'\n/customer URL: {page.url}')
    print(f'/customer Title: {page.title()}')

    els = page.evaluate("""() => {
        const all = document.querySelectorAll('button, a, input, [role], span, div');
        return Array.from(all).filter(el => el.offsetParent !== null).slice(0, 30).map(el => ({
            tag: el.tagName,
            text: (el.innerText || '').trim().slice(0, 40),
            cls: (typeof el.className === 'string' ? el.className : '').slice(0, 40),
        }));
    }""")
    print('\n=== /customer 页面元素 ===')
    for e in els:
        if e['text']:
            print(f'  [{e["tag"]}] "{e["text"]}" {e["cls"]}')

    browser.close()
