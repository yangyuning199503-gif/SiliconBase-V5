#!/usr/bin/env python3
"""
Custom Provider - 支持任意HTTP API
"""

import asyncio
import json
import re
from typing import Any

import aiohttp
import requests

from .base import AIProvider, ProviderCapabilities, ProviderConfigError, ProviderNotAvailableError


class CustomProvider(AIProvider):
    """自定义HTTP API Provider"""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)

        self.api_url = config.get("api_url", "")
        self.headers = config.get("headers", {})
        self.request_template = config.get("request_template", {})
        self.response_path = config.get("response_path", "choices[0].message.content")
        self.timeout = config.get("timeout", 30)

        # 能力配置（可选）
        self._capabilities = config.get("capabilities", {})

        valid, error = self.validate_config()
        if not valid:
            raise ProviderConfigError(error)

    def get_capabilities(self) -> ProviderCapabilities:
        """返回Custom Provider的能力声明"""
        return ProviderCapabilities(
            streaming=self._capabilities.get("streaming", False),
            vision=self._capabilities.get("vision", False),
            function_calling=self._capabilities.get("function_calling", False),
            max_context_length=self._capabilities.get("max_context_length", 4096)
        )

    def validate_config(self) -> tuple[bool, str]:
        if not self.api_url:
            return False, "api_url不能为空"
        if not self.request_template:
            return False, "request_template不能为空"
        return True, ""

    def _build_request(self, messages: list[dict[str, str]], **kwargs) -> dict[str, Any]:
        prompt = messages[0].get("content", "") if messages else ""

        template_str = json.dumps(self.request_template, ensure_ascii=False)

        replace_map = {
            "{prompt}": json.dumps(prompt, ensure_ascii=False)[1:-1],
            "{messages}": json.dumps(messages, ensure_ascii=False),
            "{model}": kwargs.get("model", "default-model"),
            "{temperature}": str(kwargs.get("temperature", 0.7)),
            "{max_tokens}": str(kwargs.get("max_tokens", 1024)),
        }

        for placeholder, value in replace_map.items():
            template_str = template_str.replace(placeholder, value)

        return json.loads(template_str)

    def _extract_response(self, data: dict[str, Any]) -> str | None:
        parts = self.response_path.split('.')
        current = data

        for part in parts:
            match = re.match(r'(\w+)\[(\d+)\]', part)
            if match:
                key, index = match.groups()
                if key in current and isinstance(current[key], list):
                    current = current[key][int(index)]
                else:
                    return None
            else:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None

        return str(current) if current is not None else None

    def chat(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        try:
            request_data = self._build_request(messages, **kwargs)

            resp = requests.post(
                self.api_url,
                json=request_data,
                headers=self.headers,
                timeout=self.timeout
            )

            resp.raise_for_status()
            data = resp.json()

            content = self._extract_response(data)
            return content

        except requests.exceptions.Timeout as _exc:
            raise ProviderNotAvailableError("请求超时") from _exc
        except requests.exceptions.ConnectionError as e:
            raise ProviderNotAvailableError(f"连接失败: {e}") from e
        except Exception as e:
            self._set_error(str(e))
            raise

    async def chat_async(self, messages: list[dict[str, str]], **kwargs) -> str | None:
        """异步多轮对话（原生 aiohttp 实现）

        _build_request 和 _extract_response 直接复用同步版本。
        """
        try:
            request_data = self._build_request(messages, **kwargs)
            timeout = aiohttp.ClientTimeout(total=self.timeout)

            async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
                self.api_url,
                json=request_data,
                headers=self.headers
            ) as resp:
                if resp.status >= 500:
                    raise ProviderNotAvailableError(f"服务器错误: HTTP {resp.status}")
                resp.raise_for_status()
                data = await resp.json()

                content = self._extract_response(data)
                return content

        except asyncio.TimeoutError as _exc:
            raise ProviderNotAvailableError("请求超时") from _exc
        except aiohttp.ClientConnectionError as e:
            raise ProviderNotAvailableError(f"连接失败: {e}") from e
        except Exception as e:
            self._set_error(str(e))
            raise

    def is_available(self) -> bool:
        try:
            resp = requests.get(self.api_url, timeout=2)
            return resp.status_code < 500
        except Exception:
            return False

    def get_config(self) -> dict[str, Any]:
        return {
            "provider": "custom",
            "api_url": self.api_url,
            "response_path": self.response_path,
            "capabilities": {
                "streaming": self._capabilities.get("streaming", False),
                "vision": self._capabilities.get("vision", False),
                "function_calling": self._capabilities.get("function_calling", False),
                "max_context_length": self._capabilities.get("max_context_length", 4096)
            }
        }
