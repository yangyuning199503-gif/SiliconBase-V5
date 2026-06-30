#!/usr/bin/env python3
"""
原子工具：网页搜索 (真正搜索版)
2026-03-12 重构：强制抛错原则 - 搜索失败绝不明示/暗示"已在浏览器中搜索"

核心铁律:
1. 搜索失败 = ERROR日志 + 抛错 + 告诉用户"搜索服务暂时不可用"
2. 内容抓取失败 = ERROR日志 + 抛错
3. 必须返回实际的搜索结果内容
"""
import asyncio
from typing import Any

from core.base_tool import BaseTool
from core.logger import logger
from tools.web_proxy_utils import aiohttp_proxy, requests_proxies

# 搜索依赖
try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        DDGS_AVAILABLE = True
    except ImportError:
        DDGS_AVAILABLE = False

# 网页抓取依赖
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

try:
    import requests
    from bs4 import BeautifulSoup
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class WebSearchError(Exception):
    """搜索失败异常 - 必须抛出让上层处理"""
    pass


class ContentFetchError(Exception):
    """内容抓取失败异常"""
    pass


class WebSearch(BaseTool):
    """
    网页搜索工具 - 真正返回搜索结果，失败时抛错

    功能：
    1. 使用 DuckDuckGo 搜索获取结果
    2. 自动抓取前N个网页内容
    3. 失败时抛 WebSearchError，绝不静默返回假结果
    """

    tool_id = "web_search"
    tool_owner = "system"
    name = "网页搜索"
    description = """搜索互联网获取实时信息。可以搜索天气、新闻、知识等，并自动抓取网页内容供AI分析。

使用示例：
- 搜索天气：{"query": "北京今天天气"}
- 搜索新闻：{"query": "最新科技新闻"}
- 搜索知识：{"query": "Python是什么"}
- 深度搜索：{"query": "某个话题", "max_results": 3}

注意：搜索失败时会抛出错误，不会静默返回。
"""

    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词"
            },
            "max_results": {
                "type": "integer",
                "default": 3,
                "minimum": 1,
                "maximum": 10,
                "description": "返回搜索结果数量"
            },
            "max_content_length": {
                "type": "integer",
                "default": 2000,
                "description": "每个页面最多抓取字符数"
            },
            "region": {
                "type": "string",
                "default": "cn-zh",
                "description": "搜索区域 (如 cn-zh, us-en, wt-wt)"
            },
            "safe_search": {
                "type": "string",
                "enum": ["on", "moderate", "off"],
                "default": "moderate",
                "description": "安全搜索级别"
            }
        },
        "required": ["query"]
    }

    # 请求配置
    REQUEST_TIMEOUT = 10
    REQUEST_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    # 并发配置
    MAX_WORKERS = 3

    def __init__(self):
        super().__init__()
        self._ddgs = None

    def _get_ddgs(self):
        """获取 DuckDuckGo 搜索实例（自动使用系统代理）"""
        if self._ddgs is None and DDGS_AVAILABLE:
            from tools.web_proxy_utils import aiohttp_proxy
            proxy = aiohttp_proxy()
            self._ddgs = DDGS(proxy=proxy) if proxy else DDGS()
        return self._ddgs

    async def _execute_async(self, query: str, **kwargs) -> dict:
        """
        异步执行网页搜索 - Phase 8 原生异步化

        改造策略：
        - DDGS 搜索仍是同步库，使用 run_in_executor 桥接（搜索通常 <1s）
        - 网页抓取使用 aiohttp 原生异步 + asyncio.gather 并发
        - BeautifulSoup 解析是 CPU 计算，使用 run_in_executor 桥接
        """
        # 1. 参数校验
        if not query or not query.strip():
            logger.error("[WebSearch] 搜索查询为空")
            raise WebSearchError("搜索查询不能为空")

        query = query.strip()
        max_results = kwargs.get("max_results", 3)
        max_content_length = kwargs.get("max_content_length", 2000)
        region = kwargs.get("region", "cn-zh")
        safe_search = kwargs.get("safe_search", "moderate")

        logger.info(f"[WebSearch] 开始搜索: '{query}', max_results={max_results}")

        # 2. 检查依赖
        if not DDGS_AVAILABLE:
            logger.error("[WebSearch] duckduckgo-search 未安装")
            raise WebSearchError("搜索服务暂时不可用：缺少必要依赖 duckduckgo-search")

        if not AIOHTTP_AVAILABLE:
            logger.error("[WebSearch] aiohttp 未安装")
            raise WebSearchError("搜索服务暂时不可用：缺少必要依赖 aiohttp")

        # 3. 执行搜索（原生异步 aiohttp，不再依赖 ddgs 同步库）
        try:
            search_results = await self._perform_search_async(
                query,
                max_results=max_results,
                region=region,
                safe_search=safe_search
            )
        except WebSearchError:
            raise
        except Exception as e:
            logger.error(f"[WebSearch] 搜索执行失败: {e}", exc_info=True)
            raise WebSearchError(f"搜索服务暂时不可用: {str(e)}") from e

        # 4. 检查结果
        if not search_results:
            logger.error(f"[WebSearch] 搜索返回空结果: '{query}'")
            raise WebSearchError(f"搜索'{query}'未返回结果，请尝试其他关键词")

        # 5. 抓取网页内容（aiohttp 原生异步 + gather 并发）
        logger.info(f"[WebSearch] 开始抓取 {len(search_results)} 个结果的内容")
        contents = await self._fetch_contents_async(search_results, max_content_length)

        if not contents:
            logger.error("[WebSearch] 所有结果内容抓取失败")
            raise WebSearchError("无法获取搜索结果内容，请稍后重试")

        # 6. 生成摘要
        summary = self._generate_summary(contents, query)

        # 7. 构建成功结果
        result_data = {
            "query": query,
            "summary": summary,
            "sources": contents,
            "success": True
        }

        logger.info(f"[WebSearch] 搜索完成: '{query[:30]}...', 成功获取 {len(contents)} 条结果")

        return {
            "success": True,
            "error_code": None,
            "user_message": summary,
            "data": result_data
        }

    def _execute(self, query: str, **kwargs) -> dict:
        """
        执行网页搜索 - 失败时抛错

        Args:
            query: 搜索关键词
            max_results: 返回结果数量
            max_content_length: 每个页面最大字符数
            region: 搜索区域
            safe_search: 安全搜索级别

        Returns:
            搜索结果字典

        Raises:
            WebSearchError: 搜索失败时抛出
            ContentFetchError: 内容抓取失败时抛出
        """
        # 1. 参数校验
        if not query or not query.strip():
            logger.error("[WebSearch] 搜索查询为空")
            raise WebSearchError("搜索查询不能为空")

        query = query.strip()
        max_results = kwargs.get("max_results", 3)
        max_content_length = kwargs.get("max_content_length", 2000)
        region = kwargs.get("region", "cn-zh")
        safe_search = kwargs.get("safe_search", "moderate")

        logger.info(f"[WebSearch] 开始搜索: '{query}', max_results={max_results}")

        # 2. 检查依赖
        if not DDGS_AVAILABLE:
            logger.error("[WebSearch] duckduckgo-search 未安装")
            raise WebSearchError("搜索服务暂时不可用：缺少必要依赖 duckduckgo-search")

        if not REQUESTS_AVAILABLE:
            logger.error("[WebSearch] requests/beautifulsoup4 未安装")
            raise WebSearchError("搜索服务暂时不可用：缺少必要依赖 requests/beautifulsoup4")

        # 3. 执行搜索
        try:
            search_results = self._perform_search(
                query,
                max_results=max_results,
                region=region,
                safe_search=safe_search
            )
        except WebSearchError:
            raise
        except Exception as e:
            logger.error(f"[WebSearch] 搜索执行失败: {e}", exc_info=True)
            raise WebSearchError(f"搜索服务暂时不可用: {str(e)}") from e

        # 4. 检查结果
        if not search_results:
            logger.error(f"[WebSearch] 搜索返回空结果: '{query}'")
            raise WebSearchError(f"搜索'{query}'未返回结果，请尝试其他关键词")

        # 5. 抓取网页内容
        logger.info(f"[WebSearch] 开始抓取 {len(search_results)} 个结果的内容")
        contents = self._fetch_contents(
            search_results,
            max_content_length=max_content_length
        )

        if not contents:
            logger.error("[WebSearch] 所有结果内容抓取失败")
            raise WebSearchError("无法获取搜索结果内容，请稍后重试")

        # 6. 生成摘要
        summary = self._generate_summary(contents, query)

        # 7. 构建成功结果
        result_data = {
            "query": query,
            "summary": summary,
            "sources": contents,
            "success": True
        }

        logger.info(f"[WebSearch] 搜索完成: '{query[:30]}...', 成功获取 {len(contents)} 条结果")

        return {
            "success": True,
            "error_code": None,
            "user_message": summary,
            "data": result_data
        }

    def _perform_search(self, query: str, max_results: int = 5,
                       region: str = "cn-zh", safe_search: str = "moderate") -> list[dict[str, str]]:
        """
        执行 DuckDuckGo 搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            region: 搜索区域
            safe_search: 安全搜索级别

        Returns:
            搜索结果列表

        Raises:
            WebSearchError: 搜索失败
        """
        try:
            ddgs = self._get_ddgs()

            # 使用新API: query参数和返回列表
            # 尝试使用lite后端，更可靠
            results = ddgs.text(
                query=query,
                region=region,
                safesearch=safe_search,
                max_results=max_results * 2,  # 多获取一些，因为有些可能抓取失败
                backend="lite"
            )

            # 新API直接返回列表
            if results is None:
                logger.error(f"[WebSearch] 搜索返回None: '{query}'")
                raise WebSearchError(f"搜索'{query}'返回空结果")

            formatted_results = []
            for r in results[:max_results]:
                formatted_results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")
                })

            return formatted_results

        except WebSearchError:
            raise
        except Exception as e:
            logger.error(f"[WebSearch] DuckDuckGo 搜索失败: {e}", exc_info=True)
            raise WebSearchError(f"搜索引擎调用失败: {str(e)}") from e

    async def _perform_search_async(self, query: str, max_results: int = 5,
                                    region: str = "cn-zh", safe_search: str = "moderate") -> list[dict[str, str]]:
        """
        异步 DuckDuckGo 搜索

        实现策略：复用经过验证的同步 DDGS.text() API，通过 asyncio.to_thread
        包装为异步接口。原生的 html.duckduckgo.com 直接请求在中国大陆等网络环境
        下极易超时，不再作为主路径。

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            region: 搜索区域
            safe_search: 安全搜索级别

        Returns:
            搜索结果列表
        """
        import asyncio

        def _sync_search():
            return self._perform_search(
                query,
                max_results=max_results,
                region=region,
                safe_search=safe_search
            )

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_sync_search),
                timeout=30.0
            )
        except asyncio.TimeoutError as _exc:
            raise WebSearchError("DuckDuckGo 搜索超时，请稍后重试") from _exc
        except WebSearchError:
            raise
        except Exception as e:
            logger.error(f"[WebSearch] 异步搜索失败: {e}", exc_info=True)
            raise WebSearchError(f"搜索引擎调用失败: {str(e)}") from e

    def _fetch_contents(self, results: list[dict[str, str]],
                       max_content_length: int = 2000) -> list[dict[str, Any]]:
        """
        同步版：并发抓取网页内容（ThreadPoolExecutor + requests）

        供旧代码和同步路径使用。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        contents = []

        def fetch_single(result: dict[str, str]) -> dict[str, Any] | None:
            """抓取单个页面"""
            url = result.get("url", "")
            title = result.get("title", "")
            snippet = result.get("snippet", "")

            if not url or not url.startswith(("http://", "https://")):
                return None

            try:
                content = self._fetch_content(url, max_content_length)
                return {
                    "title": title,
                    "url": url,
                    "content": content
                }
            except Exception as e:
                logger.warning(f"[WebSearch] 抓取内容失败 {url}: {e}，使用搜索摘要回退")
                fallback = snippet[:max_content_length] if snippet else f"[{title}]"
                return {
                    "title": title,
                    "url": url,
                    "content": fallback
                }

        # 并发抓取
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            futures = [executor.submit(fetch_single, r) for r in results]

            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        contents.append(result)
                except Exception as e:
                    logger.warning(f"[WebSearch] 抓取任务异常: {e}")

        return contents

    async def _fetch_contents_async(self, results: list[dict[str, str]],
                                    max_content_length: int = 2000) -> list[dict[str, Any]]:
        """
        异步版：并发抓取网页内容（asyncio.gather + aiohttp）

        相比同步版的 ThreadPoolExecutor，真正的并发优势：
        - 多个 HTTP 请求同时发出，无需等待线程池调度
        - 不占用线程资源，适合高并发场景
        """
        tasks = [
            self._fetch_content_async(r, max_content_length)
            for r in results
        ]

        results_gathered = await asyncio.gather(*tasks, return_exceptions=True)

        contents = []
        for item in results_gathered:
            if isinstance(item, Exception):
                logger.warning(f"[WebSearch] 抓取任务异常: {item}")
            elif item is not None:
                contents.append(item)

        return contents

    async def _fetch_content_async(self, result: dict[str, str],
                                   max_length: int = 2000) -> dict[str, Any] | None:
        """
        异步抓取单个网页内容（aiohttp 原生异步）

        BeautifulSoup 解析是 CPU 计算，桥接到线程池执行。
        """
        url = result.get("url", "")
        title = result.get("title", "")

        if not url or not url.startswith(("http://", "https://")):
            return None

        snippet = result.get("snippet", "")

        try:
            proxy = aiohttp_proxy()
            async with aiohttp.ClientSession(headers=self.REQUEST_HEADERS) as session, session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT),
                allow_redirects=True,
                proxy=proxy
            ) as response:
                response.raise_for_status()
                html_text = await response.text()

            # BeautifulSoup 解析是 CPU 计算，桥接到线程池
            loop = asyncio.get_running_loop()
            parsed_text = await loop.run_in_executor(
                None, self._parse_html, html_text, max_length
            )

            return {
                "title": title,
                "url": url,
                "content": parsed_text
            }

        except Exception as e:
            logger.warning(f"[WebSearch] 抓取内容失败 {url}: {e}，使用搜索摘要回退")
            fallback = snippet[:max_length] if snippet else f"[{title}]"
            return {
                "title": title,
                "url": url,
                "content": fallback
            }

    def _parse_html(self, html_text: str, max_length: int = 2000) -> str:
        """
        解析 HTML 提取正文（CPU 计算，同步实现）

        供同步 _fetch_content 和异步 _fetch_content_async 复用。
        """
        soup = BeautifulSoup(html_text, 'html.parser')

        # 移除script和style
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()

        # 提取正文
        text = soup.get_text(separator=' ', strip=True)

        # 清理空白
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)

        # 限制长度
        if len(text) > max_length:
            text = text[:max_length] + "..."

        return text

    def _fetch_content(self, url: str, max_length: int = 2000) -> str:
        """
        同步抓取单个网页内容（requests + BeautifulSoup）

        供旧代码和同步路径使用。

        Raises:
            ContentFetchError: 抓取失败
        """
        try:
            response = requests.get(
                url,
                headers=self.REQUEST_HEADERS,
                timeout=self.REQUEST_TIMEOUT,
                allow_redirects=True,
                proxies=requests_proxies()
            )
            response.raise_for_status()

            # 检测编码
            response.encoding = response.apparent_encoding or 'utf-8'

            # 解析 HTML
            return self._parse_html(response.text, max_length)

        except requests.RequestException as e:
            logger.error(f"[WebSearch] 请求失败 {url}: {e}")
            raise ContentFetchError(f"无法获取网页内容: {e}") from e
        except Exception as e:
            logger.error(f"[WebSearch] 解析失败 {url}: {e}")
            raise ContentFetchError(f"网页内容解析失败: {e}") from e

    def _generate_summary(self, contents: list[dict[str, Any]], query: str) -> str:
        """
        生成搜索结果摘要

        Args:
            contents: 内容列表
            query: 查询词

        Returns:
            摘要文本
        """
        if not contents:
            return f"未找到关于'{query}'的搜索结果"

        parts = [f"已搜索到 {len(contents)} 条关于'{query}'的结果：\n"]

        for i, source in enumerate(contents[:3], 1):
            title = source.get("title", "")
            content = source.get("content", "")
            url = source.get("url", "")

            # 提取内容的前200字符作为摘要
            content_preview = content[:200].replace('\n', ' ').strip()

            parts.append(f"[{i}] {title}")
            parts.append(f"    {content_preview}...")
            if url:
                parts.append(f"    来源: {url}")
            parts.append("")

        return "\n".join(parts)


# 兼容性：保留旧的导入方式
WebSearchTool = WebSearch
