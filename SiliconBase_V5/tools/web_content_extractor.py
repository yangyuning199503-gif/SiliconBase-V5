#!/usr/bin/env python3
"""
网页内容提取器
从HTML中提取正文内容，去除广告、导航等噪音
"""
import html
import re
from typing import Any
from urllib.parse import urljoin

from core.logger import logger

# 可选依赖：BeautifulSoup
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    logger.warning("[WebContentExtractor] BeautifulSoup 未安装，将使用基础提取模式")


class WebContentExtractor:
    """
    网页内容提取器

    功能：
    1. 从HTML中提取正文内容
    2. 去除广告、导航、侧边栏等噪音
    3. 提取标题、摘要、正文
    4. 智能识别主要内容区域
    """

    # 需要移除的标签
    NOISE_TAGS = [
        'script', 'style', 'nav', 'header', 'footer', 'aside',
        'advertisement', 'ad', 'banner', 'popup', 'modal',
        'noscript', 'iframe', 'svg', 'canvas', 'video', 'audio'
    ]

    # 可能是广告或噪音的class/id关键词
    NOISE_PATTERNS = [
        r'ad[s\-_]?', r'advert', r'banner', r'popup', r'modal',
        r'sidebar', r'widget', r'social', r'share', r'comment',
        r'related', r'recommend', r'promo', r'sponsor',
        r'footer', r'header', r'nav', r'menu', r'breadcrumb'
    ]

    # 可能是正文的class/id关键词
    CONTENT_PATTERNS = [
        r'content', r'article', r'post', r'entry', r'main',
        r'text', r'body', r'description', r'detail'
    ]

    def __init__(self):
        self.stats = {
            "extracted": 0,
            "failed": 0,
            "fallback_used": 0
        }

    def extract(self, html_content: str, url: str = None) -> dict[str, Any]:
        """
        从HTML中提取内容

        Args:
            html_content: HTML内容
            url: 页面URL（用于解析相对链接）

        Returns:
            提取结果字典
        """
        if not html_content or len(html_content) < 100:
            return self._empty_result("内容太短")

        try:
            if BS4_AVAILABLE:
                result = self._extract_with_bs4(html_content, url)
            else:
                result = self._extract_basic(html_content, url)

            self.stats["extracted"] += 1
            return result

        except Exception as e:
            logger.warning(f"[WebContentExtractor] 提取失败: {e}")
            self.stats["failed"] += 1
            return self._empty_result(f"提取失败: {str(e)}")

    def _extract_with_bs4(self, html_content: str, url: str = None) -> dict[str, Any]:
        """使用BeautifulSoup提取内容"""
        soup = BeautifulSoup(html_content, 'lxml')

        # 移除噪音标签
        for tag in soup.find_all(self.NOISE_TAGS):
            tag.decompose()

        # 移除包含噪音class/id的元素
        for elem in soup.find_all(class_=self._is_noise_class):
            elem.decompose()

        for elem in soup.find_all(id=self._is_noise_class):
            elem.decompose()

        # 提取标题
        title = self._extract_title(soup)

        # 提取主要内容
        main_content = self._extract_main_content(soup)

        # 清理文本
        clean_text = self._clean_text(main_content)

        # 生成摘要
        summary = self._generate_summary(clean_text)

        # 提取链接
        links = self._extract_links(soup, url)

        return {
            "success": True,
            "title": title,
            "content": clean_text[:5000],  # 限制长度
            "summary": summary,
            "links": links[:10],  # 最多10个链接
            "content_length": len(clean_text),
            "method": "beautifulsoup"
        }

    def _extract_basic(self, html_content: str, url: str = None) -> dict[str, Any]:
        """基础提取模式（无BeautifulSoup时使用）"""
        self.stats["fallback_used"] += 1

        # 移除script和style标签
        text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # 提取标题
        title_match = re.search(r'<title[^>]*>(.*?)</title>', text, re.IGNORECASE | re.DOTALL)
        title = self._clean_text(title_match.group(1)) if title_match else "无标题"

        # 移除所有HTML标签
        text = re.sub(r'<[^>]+>', ' ', text)

        # 解码HTML实体
        text = html.unescape(text)

        # 清理文本
        clean_text = self._clean_text(text)

        # 生成摘要
        summary = self._generate_summary(clean_text)

        return {
            "success": True,
            "title": title,
            "content": clean_text[:5000],
            "summary": summary,
            "links": [],
            "content_length": len(clean_text),
            "method": "basic"
        }

    def _is_noise_class(self, value):
        """检查class/id是否是噪音"""
        if not value:
            return False
        value_lower = str(value).lower()
        return any(re.search(pattern, value_lower) for pattern in self.NOISE_PATTERNS)

    def _is_content_class(self, value):
        """检查class/id可能是正文"""
        if not value:
            return False
        value_lower = str(value).lower()
        return any(re.search(pattern, value_lower) for pattern in self.CONTENT_PATTERNS)

    def _extract_title(self, soup) -> str:
        """提取页面标题"""
        # 尝试各种标题标签
        for selector in ['h1', 'h2', 'title']:
            elem = soup.find(selector)
            if elem:
                title = elem.get_text(strip=True)
                if len(title) > 5:
                    return title

        # 尝试og:title
        og_title = soup.find('meta', property='og:title')
        if og_title:
            return og_title.get('content', '').strip()

        return "无标题"

    def _extract_main_content(self, soup) -> str:
        """提取主要内容"""
        # 策略1: 找article标签
        article = soup.find('article')
        if article:
            return article.get_text(separator='\n', strip=True)

        # 策略2: 找main标签
        main = soup.find('main')
        if main:
            return main.get_text(separator='\n', strip=True)

        # 策略3: 找包含正文的div
        best_div = None
        best_score = 0

        for div in soup.find_all('div'):
            # 计算得分
            score = 0

            # 检查class/id
            div_classes = div.get('class', [])
            div_id = div.get('id', '')

            if any(self._is_content_class(c) for c in div_classes):
                score += 10
            if self._is_content_class(div_id):
                score += 10

            # 检查文本长度
            text = div.get_text(strip=True)
            text_len = len(text)

            # 偏好适中的长度（太短可能是导航，太长可能是整个页面）
            if 500 < text_len < 5000:
                score += 20
            elif text_len > 200:
                score += 10

            # 检查段落数量
            paragraphs = len(div.find_all('p'))
            score += paragraphs * 5

            if score > best_score:
                best_score = score
                best_div = div

        if best_div and best_score > 20:
            return best_div.get_text(separator='\n', strip=True)

        # 策略4: 找body
        body = soup.find('body')
        if body:
            return body.get_text(separator='\n', strip=True)

        # 最后手段：返回所有文本
        return soup.get_text(separator='\n', strip=True)

    def _clean_text(self, text: str) -> str:
        """清理文本"""
        if not text:
            return ""

        # 解码HTML实体
        text = html.unescape(text)

        # 移除多余空白
        text = re.sub(r'\s+', ' ', text)

        # 移除特殊字符
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)

        # 移除常见噪音文本
        noise_texts = [
            r'Copyright \d{4}',
            r'All rights reserved',
            r'隐私政策',
            r'使用条款',
            r'联系我们',
            r'关于我们',
            r'登录',
            r'注册',
        ]
        for noise in noise_texts:
            text = re.sub(noise, '', text, flags=re.IGNORECASE)

        return text.strip()

    def _generate_summary(self, text: str, max_length: int = 200) -> str:
        """生成文本摘要"""
        if not text:
            return ""

        # 取前max_length个字符，尝试在句子边界截断
        if len(text) <= max_length:
            return text

        # 尝试在句子边界截断
        truncated = text[:max_length]
        last_period = truncated.rfind('。')
        last_dot = truncated.rfind('. ')

        cut_point = max(last_period, last_dot)
        if cut_point > max_length * 0.5:  # 至少保留一半
            return truncated[:cut_point + 1]

        return truncated + "..."

    def _extract_links(self, soup, base_url: str = None) -> list[dict[str, str]]:
        """提取页面链接"""
        links = []

        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text(strip=True)

            # 跳过无意义的链接
            if not text or len(text) < 3:
                continue

            # 处理相对链接
            if base_url and not href.startswith(('http://', 'https://')):
                href = urljoin(base_url, href)

            # 跳过锚点
            if href.startswith('#'):
                continue

            links.append({
                "url": href,
                "text": text[:50]  # 限制长度
            })

        return links

    def _empty_result(self, reason: str) -> dict[str, Any]:
        """返回空结果"""
        return {
            "success": False,
            "title": "",
            "content": "",
            "summary": "",
            "links": [],
            "content_length": 0,
            "error": reason,
            "method": "none"
        }

    def get_stats(self) -> dict[str, int]:
        """获取统计信息"""
        return self.stats.copy()


# 全局提取器实例
_extractor: WebContentExtractor | None = None


def get_extractor() -> WebContentExtractor:
    """获取全局提取器实例"""
    global _extractor
    if _extractor is None:
        _extractor = WebContentExtractor()
    return _extractor


def extract_content(html_content: str, url: str = None) -> dict[str, Any]:
    """
    便捷的提取函数

    Args:
        html_content: HTML内容
        url: 页面URL

    Returns:
        提取结果
    """
    return get_extractor().extract(html_content, url)
