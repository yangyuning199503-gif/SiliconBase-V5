# protocol.py
import json
import uuid
from typing import Literal

RequestType = Literal["chat", "tool_call", "system"]

# 延迟导入config避免循环依赖
_config_instance = None

def _get_config():
    global _config_instance
    if _config_instance is None:
        try:
            from core.config import config
            _config_instance = config
        except ImportError:
            _config_instance = None
    return _config_instance


class ChatMessage:
    def __init__(self, role: str, content: str):
        print(f"[DEBUG] ChatMessage.__init__() 被调用，role={role}")
        self.role = role
        self.content = content

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}

class BaseProtocol:
    @staticmethod
    def generate_request_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def build_request(
        request_type: RequestType,
        content: str,
        context: list[ChatMessage],
        model_name: str = None,       # 默认从配置读取
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: int = 30,
        retry_times: int = 2
    ) -> dict:
        # 如果未指定模型或指定为 "default"，从配置读取实际模型
        if model_name is None or str(model_name).lower() == "default":
            cfg = _get_config()
            model_name = cfg.get("ai.default_model", "qwen3:8b") if cfg else "qwen3:8b"
        limited_context = context[-3:] if len(context) > 3 else context
        context_dict = [msg.to_dict() for msg in limited_context]

        return {
            "request_id": BaseProtocol.generate_request_id(),
            "type": request_type,
            "content": content,
            "context": context_dict,
            "model_config": {
                "model_name": model_name,
                "temperature": temperature,
                "max_tokens": max_tokens
            },
            "callback_info": {
                "timeout": timeout,
                "retry_times": retry_times
            }
        }

    @staticmethod
    def parse_response(raw_response: str, request_id: str) -> dict:
        try:
            response_json = json.loads(raw_response)
            # 处理 JSON 是列表的情况
            if isinstance(response_json, list):
                # 如果是列表，尝试取第一个元素，或者将整个列表转为字符串
                if len(response_json) > 0 and isinstance(response_json[0], dict):
                    return {
                        "request_id": request_id,
                        "type": response_json[0].get("type", "chat"),
                        "content": response_json[0].get("content", str(response_json)),
                        "success": True,
                        "error_msg": ""
                    }
                else:
                    return {
                        "request_id": request_id,
                        "type": "chat",
                        "content": str(response_json),
                        "success": True,
                        "error_msg": ""
                    }
            # 正常情况：JSON 是字典
            # 【修复】支持更多JSON格式：action字段、反思格式
            content = raw_response  # 默认返回原始响应

            if isinstance(response_json, dict):
                # 优先级1: 直接content字段
                if "content" in response_json and response_json["content"]:
                    content = response_json["content"]
                # 优先级2: message字段
                elif "message" in response_json and response_json["message"]:
                    content = response_json["message"]
                # 优先级3: 反思格式 (observation + insight/suggestion)
                elif "observation" in response_json:
                    insight = response_json.get("insight", "")
                    suggestion = response_json.get("suggestion", "")
                    if insight and suggestion:
                        content = f"观察: {response_json['observation']}\n洞察: {insight}\n建议: {suggestion}"
                    elif insight:
                        content = f"观察: {response_json['observation']}\n洞察: {insight}"
                    elif suggestion:
                        content = f"观察: {response_json['observation']}\n建议: {suggestion}"
                    else:
                        content = f"观察: {response_json['observation']}"
                # 优先级4: 其他字段，返回格式化后的JSON
                else:
                    # 过滤掉空值后返回有意义的JSON内容
                    meaningful_fields = {k: v for k, v in response_json.items()
                                         if v and k not in ("action", "type")}
                    if meaningful_fields:
                        content = json.dumps(meaningful_fields, ensure_ascii=False)

            return {
                "request_id": request_id,
                "type": response_json.get("type", response_json.get("action", "chat")),
                "content": content,
                "success": True,
                "error_msg": ""
            }
        except json.JSONDecodeError:
            return {
                "request_id": request_id,
                "type": "chat",
                "content": raw_response,
                "success": True,
                "error_msg": ""
            }

    @staticmethod
    def build_error_response(request_id: str, error_msg: str) -> dict:
        return {
            "request_id": request_id,
            "type": "system",
            "content": "",
            "success": False,
            "error_msg": error_msg
        }
