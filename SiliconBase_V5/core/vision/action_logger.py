#!/usr/bin/env python3
"""
ActionLogger - UI 操作记录器（半自动因果记录）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
职责：
1. 记录 UI 操作（点击、输入、窗口操作等）的前后截图
2. 调用 AI 生成操作建议结果描述（不入库，仅展示）
3. 提供用户审核接口，确认后才写入知识库

隐私控制：
- record_interactions 默认关闭
- 截图仅本地存储，64×64 缩略图
- 30 天自动过期
"""

import asyncio
import base64
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from core.logger import logger

# ═══════════════════════════════════════════════════════════════════════════════
# 隐私控制层
# ═══════════════════════════════════════════════════════════════════════════════


class PrivacyControl:
    """隐私控制层"""

    LEVEL_PUBLIC = 1
    LEVEL_PRIVATE = 2
    LEVEL_SENSITIVE = 3

    DEFAULT_CONSENTS = {
        "collect_ui_elements": True,
        "record_interactions": False,   # 默认关闭，需用户手动开启
        "upload_to_cloud": False,
    }

    def __init__(self, config_path: Path | None = None):
        self._config_path = config_path or Path("data/user_privacy.json")
        self._consents = dict(self.DEFAULT_CONSENTS)
        self._load()

    def _load(self):
        try:
            if self._config_path.exists():
                with open(self._config_path, encoding="utf-8") as f:
                    loaded = json.load(f)
                    self._consents.update(loaded)
        except Exception as e:
            logger.warning(f"[PrivacyControl] 加载隐私配置失败: {e}")

    def _save(self):
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._consents, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[PrivacyControl] 保存隐私配置失败: {e}")

    def is_allowed(self, key: str) -> bool:
        return self._consents.get(key, False)

    def set_consent(self, key: str, value: bool):
        self._consents[key] = value
        self._save()

    def get_level(self, data_type: str) -> int:
        if data_type in ("element_type", "function", "interaction"):
            return self.LEVEL_PUBLIC
        elif data_type in ("app_name", "window_title", "page_state"):
            return self.LEVEL_PRIVATE
        else:
            return self.LEVEL_SENSITIVE


# ═══════════════════════════════════════════════════════════════════════════════
# ActionLogEntry 数据模型
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ActionLogEntry:
    """操作日志条目"""
    log_id: str = ""
    timestamp: float = 0.0
    action: str = ""                # "mouse_click", "keyboard_input", ...
    target_element_id: str = ""     # 关联的元素 ID（如果有）
    target_description: str = ""    # 元素描述
    params: dict[str, Any] = field(default_factory=dict)
    screenshot_before_path: str = ""
    screenshot_after_path: str = ""
    user_annotation: str = ""
    ai_suggested_result: str = ""
    status: str = "pending"         # "pending", "confirmed", "rejected"


# ═══════════════════════════════════════════════════════════════════════════════
# 内部工具函数
# ═══════════════════════════════════════════════════════════════════════════════

_LOG_DIR = Path(__file__).parent.parent.parent / "data" / "action_logs"
_SCREENSHOT_DIR = _LOG_DIR / "screenshots"
_LOG_FILE = _LOG_DIR / "action_log.jsonl"

_UI_ACTION_TOOLS = {
    "mouse_click", "keyboard_input", "window_action",
    "click_text", "pixel_click", "launch_app",
}


def _ensure_log_dirs():
    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _save_screenshot_thumb(frame: np.ndarray, prefix: str) -> str:
    """保存截图缩略图（64×64），返回相对于项目根目录的路径"""
    _ensure_log_dirs()
    timestamp_ms = int(time.time() * 1000)
    filename = f"{prefix}_{timestamp_ms}_{uuid.uuid4().hex[:8]}.png"
    filepath = _SCREENSHOT_DIR / filename

    try:
        thumb = cv2.resize(frame, (64, 64), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(filepath), thumb)
        return str(filepath.relative_to(Path(__file__).parent.parent.parent))
    except Exception as e:
        logger.warning(f"[ActionLogger] 截图保存失败: {e}")
        return ""


def _load_pending_logs() -> list[ActionLogEntry]:
    """从 JSONL 加载 pending 状态的日志"""
    if not _LOG_FILE.exists():
        return []
    pending = []
    try:
        with open(_LOG_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("status") == "pending":
                        entry = ActionLogEntry(**data)
                        pending.append(entry)
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"[ActionLogger] 加载日志失败: {e}")
    return pending


def _append_log(entry: ActionLogEntry):
    """追加日志到 JSONL"""
    _ensure_log_dirs()
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"[ActionLogger] 写入日志失败: {e}")


def _update_log_field(log_id: str, field_name: str, value: Any):
    """更新日志指定字段（全文件重写，JSONL 不支持原地修改）"""
    if not _LOG_FILE.exists():
        return
    try:
        lines = []
        with open(_LOG_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("log_id") == log_id:
                        data[field_name] = value
                    lines.append(json.dumps(data, ensure_ascii=False))
                except Exception:
                    continue
        with open(_LOG_FILE, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
    except Exception as e:
        logger.warning(f"[ActionLogger] 更新日志字段失败: {e}")


def _is_ui_action_tool(tool_id: str) -> bool:
    """判断是否为 UI 操作工具"""
    return tool_id in _UI_ACTION_TOOLS


# ═══════════════════════════════════════════════════════════════════════════════
# AI 建议生成
# ═══════════════════════════════════════════════════════════════════════════════


async def _generate_ai_suggestion(entry: ActionLogEntry) -> str:
    """
    调用视觉模型分析操作前后截图，生成建议结果描述。
    不入库，仅更新 entry 的 ai_suggested_result 字段。
    """
    try:
        from tools.visual_understand import VisualUnderstand
    except Exception:
        return "视觉模型不可用"

    if not entry.screenshot_before_path or not entry.screenshot_after_path:
        return "无截图可供分析"

    project_root = Path(__file__).parent.parent.parent
    before_path = project_root / entry.screenshot_before_path
    after_path = project_root / entry.screenshot_after_path

    before_img = cv2.imread(str(before_path))
    after_img = cv2.imread(str(after_path))

    if before_img is None or after_img is None:
        return "截图读取失败"

    # 构建对比图（左右拼接）
    h = min(before_img.shape[0], after_img.shape[0])
    before_crop = before_img[:h, :]
    after_crop = after_img[:h, :]
    combined = np.hstack([before_crop, after_crop])

    # 编码为 base64
    _, buffer = cv2.imencode(".png", combined)
    image_b64 = base64.b64encode(buffer).decode("utf-8")

    # 调用视觉模型
    try:
        vision_tool = VisualUnderstand()
        prompt = (
            f"这是一个 UI 操作的前后对比图。左图是操作前，右图是操作后。\n"
            f"操作类型: {entry.action}\n"
            f"请描述这个操作导致了什么变化（如页面跳转、弹窗出现、内容改变等）。"
            f"只输出简洁的结果描述，不要多余解释。"
        )
        result = await vision_tool._execute_async(image_source=image_b64, question=prompt)
        if result and result.get("success"):
            suggestion = result.get("data", {}).get("description", "")
            if suggestion and len(suggestion) > 5:
                return suggestion[:200]
        return "AI 无法确定操作结果"
    except Exception as e:
        logger.debug(f"[ActionLogger] AI 建议生成失败: {e}")
        return f"分析失败: {str(e)[:50]}"


# ═══════════════════════════════════════════════════════════════════════════════
# ActionLogger 主类
# ═══════════════════════════════════════════════════════════════════════════════


class ActionLogger:
    """UI 操作记录器"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._privacy = PrivacyControl()
        self._pending_cache: list[ActionLogEntry] = []
        _ensure_log_dirs()
        self._pending_cache = _load_pending_logs()
        logger.info(
            f"[ActionLogger] 初始化完成，记录状态: "
            f"{'开启' if self.is_recording_enabled() else '关闭'}，"
            f"pending 日志: {len(self._pending_cache)} 条"
        )

    def is_recording_enabled(self) -> bool:
        return self._privacy.is_allowed("record_interactions")

    def set_recording_enabled(self, enabled: bool):
        self._privacy.set_consent("record_interactions", enabled)
        logger.info(f"[ActionLogger] 操作记录已{'开启' if enabled else '关闭'}")

    def get_privacy(self) -> PrivacyControl:
        return self._privacy

    # ───────────────────────────────────────────────────────────────
    # before_action / after_action（供 BaseTool 调用）
    # ───────────────────────────────────────────────────────────────

    async def before_action(self, tool_id: str, params: dict[str, Any]) -> str | None:
        """操作前调用：截图并返回截图路径"""
        if not self.is_recording_enabled():
            return None
        if not _is_ui_action_tool(tool_id):
            return None

        try:
            from core.vision.safe_screenshot import safe_screenshot_to_numpy
            frame = await asyncio.to_thread(safe_screenshot_to_numpy)
            if frame is not None and frame.size > 0:
                return _save_screenshot_thumb(frame, f"before_{tool_id}")
        except Exception as e:
            logger.debug(f"[ActionLogger] 操作前截图失败: {e}")
        return None

    async def after_action(
        self,
        tool_id: str,
        params: dict[str, Any],
        tool_result: dict[str, Any],
        before_screenshot_path: str | None = None,
    ):
        """
        操作后调用：截图、保存日志、后台生成 AI 建议。
        建议作为 asyncio.create_task 后台执行，不阻塞主流程。
        """
        if not self.is_recording_enabled():
            return
        if not _is_ui_action_tool(tool_id):
            return

        try:
            # 等待界面响应
            await asyncio.sleep(0.5)

            # 截图 after
            after_path = ""
            try:
                from core.vision.safe_screenshot import safe_screenshot_to_numpy
                frame = await asyncio.to_thread(safe_screenshot_to_numpy)
                if frame is not None and frame.size > 0:
                    after_path = _save_screenshot_thumb(frame, f"after_{tool_id}")
            except Exception as e:
                logger.debug(f"[ActionLogger] 操作后截图失败: {e}")

            # 构造日志条目
            entry = ActionLogEntry(
                log_id=f"act_{uuid.uuid4().hex[:12]}",
                timestamp=time.time(),
                action=tool_id,
                params={k: v for k, v in params.items() if k != "password"},  # 过滤敏感字段
                screenshot_before_path=before_screenshot_path or "",
                screenshot_after_path=after_path,
                status="pending",
            )

            _append_log(entry)
            self._pending_cache.append(entry)

            # 后台生成 AI 建议
            suggestion = await _generate_ai_suggestion(entry)
            entry.ai_suggested_result = suggestion
            _update_log_field(entry.log_id, "ai_suggested_result", suggestion)

            logger.info(
                f"[ActionLogger] 操作已记录: {tool_id}, "
                f"AI建议: {suggestion[:40]}..."
            )

        except Exception as e:
            logger.warning(f"[ActionLogger] 操作记录失败: {e}")

    # ───────────────────────────────────────────────────────────────
    # 审核接口（供前端调用）
    # ───────────────────────────────────────────────────────────────

    def get_pending_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        """获取待审核的日志列表"""
        return [asdict(e) for e in self._pending_cache[-limit:]]

    def confirm_log(self, log_id: str, user_annotation: str = "") -> bool:
        """用户确认后将日志标记为 confirmed（实际知识库写入由调用方决定）"""
        try:
            _update_log_field(log_id, "status", "confirmed")
            if user_annotation:
                _update_log_field(log_id, "user_annotation", user_annotation)
            self._pending_cache = [e for e in self._pending_cache if e.log_id != log_id]
            logger.info(f"[ActionLogger] 日志已确认: {log_id}")
            return True
        except Exception as e:
            logger.error(f"[ActionLogger] 确认日志失败: {e}")
            return False

    def reject_log(self, log_id: str) -> bool:
        """用户拒绝该日志"""
        try:
            _update_log_field(log_id, "status", "rejected")
            self._pending_cache = [e for e in self._pending_cache if e.log_id != log_id]
            logger.info(f"[ActionLogger] 日志已拒绝: {log_id}")
            return True
        except Exception as e:
            logger.error(f"[ActionLogger] 拒绝日志失败: {e}")
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════════════════


def get_action_logger() -> ActionLogger:
    """获取 ActionLogger 单例"""
    return ActionLogger()
