#!/usr/bin/env python3
"""
原子工具：网页解析
从HTML中提取结构化数据（链接、图片、表格等）
"""
from urllib.parse import urljoin

import requests

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except Exception:
    BeautifulSoup = None  # type: ignore[misc,assignment]
    BS4_AVAILABLE = False
from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
from tools.web_proxy_utils import requests_proxies


class WebParse(BaseTool):
    tool_id = "web_parse"
    name = "网页解析"
    description = "解析网页HTML，提取链接、图片、文本等结构化数据（需要BeautifulSoup）"
    input_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "网页URL"
            },
            "extract": {
                "type": "string",
                "enum": ["links", "images", "text", "tables", "all"],
                "description": "提取类型",
                "default": "text"
            },
            "css_selector": {
                "type": "string",
                "description": "CSS选择器，用于定位特定区域（可选）",
                "default": ""
            }
        },
        "required": ["url"]
    }

    def _execute(self, **kwargs) -> dict:
        url = kwargs.get("url")
        extract_type = kwargs.get("extract", "text")
        css_selector = kwargs.get("css_selector", "")

        if not url:
            return format_error(INVALID_PARAMS, detail="url 不能为空")

        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        if not BS4_AVAILABLE:
            return format_error(
                TOOL_EXECUTION_ERROR,
                detail="BeautifulSoup (bs4) 未安装，网页解析功能不可用"
            )

        try:
            # 抓取网页
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=10, proxies=requests_proxies())
            response.raise_for_status()
            response.encoding = response.apparent_encoding or 'utf-8'

            # 解析HTML
            soup = BeautifulSoup(response.text, 'html.parser')

            # 如果指定了CSS选择器，只解析该区域
            if css_selector:
                soup = soup.select_one(css_selector) or soup

            result = {
                "url": response.url,
                "title": soup.title.string if soup.title else "无标题"
            }

            # 根据类型提取数据
            if extract_type == "links" or extract_type == "all":
                result["links"] = self._extract_links(soup, url)

            if extract_type == "images" or extract_type == "all":
                result["images"] = self._extract_images(soup, url)

            if extract_type == "text" or extract_type == "all":
                result["text"] = self._extract_text(soup)

            if extract_type == "tables" or extract_type == "all":
                result["tables"] = self._extract_tables(soup)

            return {
                "success": True,
                "error_code": None,
                "user_message": f"网页解析成功: {result.get('title', '无标题')}",
                "data": result
            }

        except ImportError:
            return format_error(TOOL_EXECUTION_ERROR, detail="缺少BeautifulSoup，请安装: pip install beautifulsoup4")
        except requests.exceptions.RequestException as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"网络请求失败: {str(e)}")
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"解析失败: {str(e)}")

    async def _execute_async(self, **kwargs) -> dict:
        """Phase 8 TRUE_ASYNC: 使用 aiohttp 抓取网页，零线程池"""
        import aiohttp
        from bs4 import BeautifulSoup

        from tools.web_proxy_utils import aiohttp_proxy

        url = kwargs.get("url")
        extract_type = kwargs.get("extract", "text")
        css_selector = kwargs.get("css_selector", "")

        if not url:
            return format_error(INVALID_PARAMS, detail="url 不能为空")

        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            proxy = aiohttp_proxy()
            async with aiohttp.ClientSession() as session, session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10), proxy=proxy) as response:
                    response.raise_for_status()
                    text = await response.text()

            soup = BeautifulSoup(text, 'html.parser')

            if css_selector:
                soup = soup.select_one(css_selector) or soup

            result = {
                "url": url,
                "title": soup.title.string if soup.title else "无标题"
            }

            if extract_type == "links" or extract_type == "all":
                result["links"] = self._extract_links(soup, url)

            if extract_type == "images" or extract_type == "all":
                result["images"] = self._extract_images(soup, url)

            if extract_type == "text" or extract_type == "all":
                result["text"] = self._extract_text(soup)

            if extract_type == "tables" or extract_type == "all":
                result["tables"] = self._extract_tables(soup)

            return {
                "success": True,
                "error_code": None,
                "user_message": f"网页解析成功: {result.get('title', '无标题')}",
                "data": result
            }

        except ImportError:
            return format_error(TOOL_EXECUTION_ERROR, detail="缺少BeautifulSoup，请安装: pip install beautifulsoup4")
        except aiohttp.ClientError as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"网络请求失败: {str(e)}")
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"解析失败: {str(e)}")

    def _extract_links(self, soup, base_url):
        """提取所有链接"""
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            full_url = urljoin(base_url, href)
            links.append({
                "text": a.get_text(strip=True)[:50],
                "url": full_url
            })
        return links[:20]  # 最多20个

    def _extract_images(self, soup, base_url):
        """提取所有图片"""
        images = []
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if src:
                full_url = urljoin(base_url, src)
                images.append({
                    "url": full_url,
                    "alt": img.get('alt', '无描述')[:50]
                })
        return images[:10]  # 最多10个

    def _extract_text(self, soup):
        """提取正文文本"""
        # 移除script和style
        for script in soup(["script", "style"]):
            script.decompose()

        # 获取文本
        text = soup.get_text(separator='\n', strip=True)

        # 清理空行
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        return '\n'.join(lines[:50])  # 最多50行

    def _extract_tables(self, soup):
        """提取表格数据"""
        tables = []
        for table in soup.find_all('table'):
            rows = []
            for tr in table.find_all('tr'):
                row = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
                if row:
                    rows.append(row)
            if rows:
                tables.append(rows)
        return tables[:3]  # 最多3个表
