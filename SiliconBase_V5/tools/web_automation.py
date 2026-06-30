#!/usr/bin/env python3
"""
原子工具：浏览器自动化（预留接口）
使用Playwright/Selenium控制真实浏览器

注意：这是预留设计，需要额外安装playwright或selenium
"""
from core.base_tool import BaseTool
from core.error_codes import TOOL_EXECUTION_ERROR, format_error
from tools.web_proxy_utils import playwright_proxy


class WebAutomation(BaseTool):
    """
    浏览器自动化工具 - 支持JS渲染的网页抓取

    需要安装: pip install playwright
    然后执行: playwright install
    """
    tool_id = "web_automation"
    name = "浏览器自动化"
    description = "使用真实浏览器抓取JS渲染的网页（需要安装playwright）"
    input_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "目标URL"},
            "action": {
                "type": "string",
                "enum": ["open", "click", "input", "screenshot", "get_text"],
                "default": "open"
            },
            "selector": {"type": "string", "description": "CSS选择器（用于click/input）"},
            "text": {"type": "string", "description": "输入文本（用于input）"},
            "wait_for": {"type": "string", "description": "等待元素出现的选择器"}
        },
        "required": ["url"]
    }

    async def _execute_async(self, **kwargs) -> dict:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail="未安装playwright，请执行: pip install playwright && playwright install"
            )

        url = kwargs.get("url")
        action = kwargs.get("action", "open")
        selector = kwargs.get("selector", "")
        text = kwargs.get("text", "")
        wait_for = kwargs.get("wait_for", "")

        try:
            proxy = playwright_proxy()
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, proxy=proxy)
                page = await browser.new_page()

                # 打开页面
                # 使用 domcontentloaded 而非 networkidle，避免资源密集型页面（如 OKX）超时
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)

                # 等待特定元素
                if wait_for:
                    await page.wait_for_selector(wait_for)

                result = {}

                # 执行动作
                if action == "open":
                    result = {
                        "title": await page.title(),
                        "content": (await page.content())[:2000]
                    }
                elif action == "click" and selector:
                    await page.click(selector)
                    result = {"message": f"已点击 {selector}"}
                elif action == "input" and selector and text:
                    await page.fill(selector, text)
                    result = {"message": f"已在 {selector} 输入文本"}
                elif action == "screenshot":
                    screenshot = await page.screenshot()
                    result = {"screenshot_size": len(screenshot)}
                elif action == "get_text":
                    result = {"text": (await page.inner_text("body"))[:2000]}

                await browser.close()

                return {
                    "success": True,
                    "error_code": None,
                    "user_message": f"浏览器操作 '{action}' 完成",
                    "data": result
                }

        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"浏览器自动化失败: {str(e)}")

    async def run(self, **kwargs) -> dict:
        return await self.run_async(**kwargs)
