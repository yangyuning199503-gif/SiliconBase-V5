#!/usr/bin/env python3
"""
原子工具：网页内容抓取
使用requests抓取网页HTML，支持静态页面

SSRF防护说明:
- 禁止访问内网IP地址(10.x.x.x, 172.16-31.x.x, 192.168.x.x, 169.254.x.x, 127.x.x.x)
- 禁止访问云元数据服务(169.254.169.254)
- 支持用户配置额外白名单
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import aiohttp

from core.base_tool import BaseTool
from core.error_codes import INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
from core.logger import logger
from tools.web_proxy_utils import aiohttp_proxy


class WebFetch(BaseTool):
    tool_id = "web_fetch"
    name = "网页抓取"
    description = "抓取网页HTML内容，适用于静态网页（非JavaScript渲染）"
    input_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "网页URL，需要完整地址如 https://example.com"
            },
            "timeout": {
                "type": "integer",
                "description": "超时时间（秒）",
                "default": 10
            },
            "headers": {
                "type": "object",
                "description": "自定义HTTP头（可选）",
                "default": {}
            },
            "whitelist": {
                "type": "array",
                "description": "额外允许的URL/域名白名单（可选）",
                "items": {"type": "string"},
                "default": []
            }
        },
        "required": ["url"]
    }

    # 禁止的内网IP网段 (CIDR格式)
    BLOCKED_NETWORKS = [
        ipaddress.ip_network('10.0.0.0/8'),       # 私有网络
        ipaddress.ip_network('172.16.0.0/12'),    # 私有网络
        ipaddress.ip_network('192.168.0.0/16'),   # 私有网络
        ipaddress.ip_network('169.254.0.0/16'),   # 链路本地（云元数据）
        ipaddress.ip_network('127.0.0.0/8'),      # 本地回环
        ipaddress.ip_network('0.0.0.0/8'),        # 当前网络
        ipaddress.ip_network('100.64.0.0/10'),    # 运营商级NAT
        ipaddress.ip_network('192.0.0.0/24'),     # IETF协议分配
        ipaddress.ip_network('192.0.2.0/24'),     # TEST-NET-1
        ipaddress.ip_network('198.18.0.0/15'),    # 网络基准测试
        ipaddress.ip_network('198.51.100.0/24'),  # TEST-NET-2
        ipaddress.ip_network('203.0.113.0/24'),   # TEST-NET-3
        ipaddress.ip_network('224.0.0.0/4'),      # 多播
        ipaddress.ip_network('240.0.0.0/4'),      # 保留
        ipaddress.ip_network('255.255.255.255/32'),  # 广播
    ]

    # 禁止的主机名/IP（黑名单）
    BLOCKED_HOSTS = {
        'localhost',
        'localhost.localdomain',
        '0.0.0.0',
        '::',
        '::1',
        '169.254.169.254',  # AWS/阿里云/腾讯云元数据服务
        '169.254.170.2',    # AWS ECS元数据
        '100.100.100.200',  # 阿里云元数据
    }

    # 禁止的协议
    BLOCKED_SCHEMES = {'file', 'ftp', 'ftps', 'gopher', 'telnet', 'ldap', 'ldaps', 'smb', 'ssh', 'smtp', 'imap', 'pop3'}

    # 是否使用增强内容提取
    USE_ENHANCED_EXTRACTION = True

    async def _execute_async(self, **kwargs) -> dict:
        url = kwargs.get("url")
        if not url:
            return format_error(INVALID_PARAMS, detail="url 不能为空")

        # 自动补全协议
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        # SSRF安全检查
        whitelist = kwargs.get("whitelist", [])
        safety_check = self._is_safe_url(url, whitelist)
        if not safety_check['safe']:
            return format_error(
                INVALID_PARAMS,
                detail=f"SSRF安全拦截: {safety_check['reason']}"
            )

        timeout = kwargs.get("timeout", 10)
        headers = kwargs.get("headers", {})

        # 默认User-Agent
        default_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        default_headers.update(headers)

        proxy = aiohttp_proxy()

        try:
            # 二次验证：解析最终IP（防止DNS重绑定攻击）
            # 当使用代理时，由代理服务器负责DNS解析，本地DNS可能受污染，跳过IP检查
            parsed = urlparse(url)
            hostname = parsed.hostname
            if hostname and not proxy:
                try:
                    resolved_ip = socket.getaddrinfo(hostname, None)[0][4][0]
                    if self._is_ip_blocked(ipaddress.ip_address(resolved_ip)):
                        return format_error(
                            INVALID_PARAMS,
                            detail=f"SSRF安全拦截: 解析后的IP {resolved_ip} 在禁止列表中"
                        )
                except socket.gaierror:
                    pass  # 解析失败，让请求继续尝试
            async with aiohttp.ClientSession(headers=default_headers) as session, session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=True,
                proxy=proxy
            ) as response:
                response.raise_for_status()
                text = await response.text()
                final_url = str(response.url)

            # 使用增强内容提取（桥接同步函数）
            if self.USE_ENHANCED_EXTRACTION:
                try:
                    from tools.web_content_extractor import extract_content
                    extracted = await asyncio.to_thread(extract_content, text, final_url)

                    if extracted.get("success"):
                        return {
                            "success": True,
                            "error_code": None,
                            "user_message": f"成功抓取网页: {extracted.get('title', '无标题')}",
                            "data": {
                                "url": final_url,
                                "status_code": response.status,
                                "title": extracted.get("title", self._extract_title(text)),
                                "content": extracted.get("content", text[:2000]),
                                "summary": extracted.get("summary", ""),
                                "links": extracted.get("links", []),
                                "length": len(text),
                                "extraction_method": extracted.get("method", "unknown")
                            }
                        }
                except Exception as e:
                    logger.debug(f"[WebFetch] 增强提取失败，回退到基础模式: {e}")

            # 基础模式：返回前2000字符
            content = text[:2000]

            return {
                "success": True,
                "error_code": None,
                "user_message": f"成功抓取网页: {self._extract_title(text)}",
                "data": {
                    "url": final_url,
                    "status_code": response.status,
                    "title": self._extract_title(text),
                    "content": content,
                    "length": len(text)
                }
            }
        except asyncio.TimeoutError:
            return format_error(TOOL_EXECUTION_ERROR, detail="请求超时")
        except aiohttp.ClientConnectorError:
            return format_error(TOOL_EXECUTION_ERROR, detail="连接失败，请检查网络或URL")
        except aiohttp.ClientResponseError as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"HTTP错误: {e.status}")
        except Exception as e:
            return format_error(TOOL_EXECUTION_ERROR, detail=f"抓取失败: {str(e)}")

    def _is_safe_url(self, url: str, extra_whitelist: list = None) -> dict:
        """
        检查URL是否安全，防止SSRF攻击

        Args:
            url: 要检查的URL
            extra_whitelist: 额外的白名单列表（域名或IP）

        Returns:
            dict: {'safe': bool, 'reason': str}
        """
        extra_whitelist = extra_whitelist or []

        try:
            parsed = urlparse(url)

            # 检查协议
            if parsed.scheme in self.BLOCKED_SCHEMES:
                return {
                    'safe': False,
                    'reason': f"禁止的协议: {parsed.scheme}"
                }

            if parsed.scheme not in ('http', 'https'):
                return {
                    'safe': False,
                    'reason': "仅允许HTTP/HTTPS协议"
                }

            hostname = parsed.hostname
            if not hostname:
                return {
                    'safe': False,
                    'reason': "无法解析主机名"
                }

            # 检查黑名单主机名
            if hostname.lower() in self.BLOCKED_HOSTS:
                return {
                    'safe': False,
                    'reason': f"禁止的主机名: {hostname}"
                }

            # 检查额外白名单
            if extra_whitelist:
                for allowed in extra_whitelist:
                    if hostname == allowed or hostname.endswith('.' + allowed.lstrip('.')):
                        return {'safe': True, 'reason': '在白名单中'}

            # 检查是否为IP地址
            try:
                ip = ipaddress.ip_address(hostname)
                if self._is_ip_blocked(ip):
                    return {
                        'safe': False,
                        'reason': f"禁止的IP地址: {ip}"
                    }
                return {'safe': True, 'reason': 'IP检查通过'}
            except ValueError:
                # 不是IP地址，是域名，继续检查
                pass

            return {'safe': True, 'reason': '域名检查通过'}

        except Exception as e:
            return {
                'safe': False,
                'reason': f"URL解析错误: {str(e)}"
            }

    def _is_ip_blocked(self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        """
        检查IP是否在禁止的网络范围内

        Args:
            ip: IP地址对象

        Returns:
            bool: 如果被禁止返回True
        """
        # IPv6本地地址检查
        if isinstance(ip, ipaddress.IPv6Address):
            return bool(ip.is_loopback or ip.is_link_local or ip.is_site_local or ip.is_private)

        # IPv4检查
        for network in self.BLOCKED_NETWORKS:
            try:
                if ip in network:
                    return True
            except TypeError:
                # IPv4/IPv6不匹配，跳过
                continue

        return False

    def _extract_title(self, html: str) -> str:
        """提取网页标题"""
        import re
        match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return "未找到标题"
