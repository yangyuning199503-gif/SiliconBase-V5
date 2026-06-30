#!/usr/bin/env python3
"""
视觉标签本地缓存 - LabelCache

设计目标：
- 固化 "(应用名, 描述) -> 坐标" 的映射关系
- 看到一次就记住，下次同一应用中寻找同类元素时优先命中缓存
- 支持 TTL（默认24小时）和持久化存储

使用方式：
    from core.vision.label_cache import get_label_cache
    cache = get_label_cache()
    await cache.set("chrome", "搜索框", [100, 200, 300, 400])
    result = await cache.get("chrome", "搜索框")
    # -> [100, 200, 300, 400] 或 None
"""

import json
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_TTL_SECONDS = 86400  # 24小时
CACHE_FILE_PATH = Path("data/vision_label_cache.json")


class LabelCache:
    """
    视觉标签本地缓存

    存储格式（内存 + JSON文件）：
    {
        "chrome:搜索框": {
            "bbox": [100, 200, 300, 400],
            "created_at": 1234567890.0,
            "ttl": 86400,
            "hit_count": 5,
            "dominant_app": "chrome.exe",
            "tags": ["input", "search"],
            "description": "顶部搜索框",
            "source": "vision"
        }
    }
    """

    def __init__(self, cache_path: Path | None = None, ttl: int = DEFAULT_TTL_SECONDS):
        self._cache: dict[str, dict[str, Any]] = {}
        self._ttl = ttl
        self._cache_path = cache_path or CACHE_FILE_PATH
        self._lock = threading.RLock()
        self._logger = None
        self._dirty = False
        self._load()

    def _get_logger(self):
        if self._logger is None:
            try:
                from core.logger import logger
                self._logger = logger
            except Exception:
                import logging
                self._logger = logging.getLogger("LabelCache")
        return self._logger

    def _make_key(self, app_name: str, description: str) -> str:
        """生成缓存键：app_name:description（统一小写）"""
        a = (app_name or "unknown").strip().lower()
        d = (description or "").strip().lower()
        return f"{a}:{d}"

    def _load(self):
        """从本地 JSON 文件加载缓存（兼容旧格式）"""
        try:
            if self._cache_path.exists():
                with open(self._cache_path, encoding="utf-8") as f:
                    raw = json.load(f)
                now = time.time()
                kept = 0
                expired = 0
                for k, v in raw.items():
                    if not isinstance(v, dict):
                        continue
                    created = v.get("created_at", 0)
                    ttl = v.get("ttl", self._ttl)
                    if now - created > ttl:
                        expired += 1
                        continue
                    self._cache[k] = v
                    kept += 1
                self._get_logger().info(
                    f"[LabelCache] 加载缓存: 保留 {kept} 条, 丢弃过期 {expired} 条"
                )
        except json.JSONDecodeError as e:
            self._get_logger().warning(
                f"[LabelCache] 缓存文件 JSON 损坏，将删除并重新初始化: {e}"
            )
            try:
                self._cache_path.unlink()
                self._get_logger().info("[LabelCache] 已删除损坏的缓存文件")
            except Exception as del_err:
                self._get_logger().warning(f"[LabelCache] 删除损坏缓存文件失败: {del_err}")
            self._cache = {}
        except Exception as e:
            self._get_logger().warning(f"[LabelCache] 加载缓存失败: {e}")
            self._cache = {}

    def _save(self):
        """将缓存保存到本地 JSON 文件（延迟写，非每次 set 都写）"""
        if not self._dirty:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
            self._dirty = False
        except Exception as e:
            self._get_logger().warning(f"[LabelCache] 保存缓存失败: {e}")

    def get(self, app_name: str, description: str) -> list[int] | None:
        """
        从缓存读取坐标

        Returns:
            [x1, y1, x2, y2] 或 None（未命中或已过期）
        """
        key = self._make_key(app_name, description)
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            now = time.time()
            created = entry.get("created_at", 0)
            ttl = entry.get("ttl", self._ttl)
            if now - created > ttl:
                # 过期，删除
                del self._cache[key]
                self._dirty = True
                self._get_logger().debug(f"[LabelCache] 缓存过期删除: {key}")
                return None
            # 命中
            entry["hit_count"] = entry.get("hit_count", 0) + 1
            self._dirty = True
            self._get_logger().info(
                f"[LabelCache] 缓存命中: app={app_name}, desc={description}, "
                f"bbox={entry.get('bbox')}, hits={entry['hit_count']}"
            )
            return entry.get("bbox")

    def set(
        self,
        app_name: str,
        description: str,
        bbox: list[int],
        ttl: int | None = None
    ):
        """
        写入缓存

        Args:
            app_name: 当前前台应用名（如 chrome.exe）
            description: 元素描述（如"搜索框"）
            bbox: [x1, y1, x2, y2]
            ttl: 自定义过期时间（秒），默认24小时
        """
        key = self._make_key(app_name, description)
        with self._lock:
            self._cache[key] = {
                "bbox": list(bbox),
                "created_at": time.time(),
                "ttl": ttl if ttl is not None else self._ttl,
                "hit_count": 0,
                "dominant_app": app_name,
            }
            self._dirty = True
            self._get_logger().info(
                f"[LabelCache] 缓存写入: app={app_name}, desc={description}, bbox={bbox}"
            )
            # 每写入10次触发一次持久化
            if len(self._cache) % 10 == 0:
                self._save()

    def set_with_tags(
        self,
        app_name: str,
        description: str,
        bbox: list[int],
        tags: list[str],
        tag_description: str,
        source: str = "vision",
        ttl: int | None = None,
    ):
        """
        写入带完整标签信息的缓存

        Args:
            app_name: 当前前台应用名
            description: 元素描述（用于生成缓存键）
            bbox: [x1, y1, x2, y2]
            tags: 标签列表
            tag_description: 标签定义描述
            source: 来源标识（如 "uia"/"vision"/"llm"），默认 "vision"
            ttl: 自定义过期时间（秒），默认24小时
        """
        key = self._make_key(app_name, description)
        with self._lock:
            self._cache[key] = {
                "bbox": list(bbox),
                "tags": list(tags),
                "description": str(tag_description),
                "source": str(source),
                "created_at": time.time(),
                "ttl": ttl if ttl is not None else self._ttl,
                "hit_count": 0,
                "dominant_app": app_name,
            }
            self._dirty = True
            self._get_logger().info(
                f"[LabelCache] 缓存写入(含标签): app={app_name}, desc={description}, "
                f"bbox={bbox}, tags={tags}, source={source}"
            )
            if len(self._cache) % 10 == 0:
                self._save()

    def get_full(self, app_name: str, description: str) -> dict[str, Any] | None:
        """
        从缓存读取完整信息（含标签、描述、来源等）

        Returns:
            {
                "bbox": [x1, y1, x2, y2],
                "tags": [...],
                "description": str,
                "source": str,
                "hit_count": int,
                "dominant_app": str,
            }
            或 None（未命中或已过期）
        """
        key = self._make_key(app_name, description)
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            now = time.time()
            created = entry.get("created_at", 0)
            ttl = entry.get("ttl", self._ttl)
            if now - created > ttl:
                del self._cache[key]
                self._dirty = True
                self._get_logger().debug(f"[LabelCache] 缓存过期删除: {key}")
                return None
            entry["hit_count"] = entry.get("hit_count", 0) + 1
            self._dirty = True
            self._get_logger().info(
                f"[LabelCache] 缓存命中(完整): app={app_name}, desc={description}, "
                f"hits={entry['hit_count']}"
            )
            return {
                "bbox": entry.get("bbox"),
                "tags": entry.get("tags"),
                "description": entry.get("description"),
                "source": entry.get("source"),
                "hit_count": entry.get("hit_count"),
                "dominant_app": entry.get("dominant_app"),
            }

    def update_tags(
        self,
        app_name: str,
        description: str,
        tags: list[str],
        tag_description: str,
    ) -> bool:
        """
        给已有缓存条目追加/更新标签

        Args:
            tags: 要追加的标签列表（会去重合并）
            tag_description: 新的标签定义描述（非空时更新）

        Returns:
            True 表示更新成功，False 表示条目不存在或已过期
        """
        key = self._make_key(app_name, description)
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return False
            now = time.time()
            created = entry.get("created_at", 0)
            ttl = entry.get("ttl", self._ttl)
            if now - created > ttl:
                del self._cache[key]
                self._dirty = True
                self._get_logger().debug(f"[LabelCache] 缓存过期删除: {key}")
                return False
            # 合并标签
            if tags:
                existing = set(entry.get("tags", []))
                existing.update(tags)
                entry["tags"] = list(existing)
            # 更新描述
            if tag_description:
                entry["description"] = str(tag_description)
            entry["hit_count"] = entry.get("hit_count", 0) + 1
            self._dirty = True
            self._get_logger().info(
                f"[LabelCache] 标签更新: app={app_name}, desc={description}, "
                f"tags={entry.get('tags')}, desc={entry.get('description')}"
            )
            return True

    def clear(self):
        """清空全部缓存"""
        with self._lock:
            self._cache.clear()
            self._dirty = True
            self._save()
            self._get_logger().info("[LabelCache] 缓存已清空")

    def stats(self) -> dict[str, Any]:
        """返回缓存统计信息"""
        with self._lock:
            total = len(self._cache)
            total_hits = sum(v.get("hit_count", 0) for v in self._cache.values())
            return {
                "total_entries": total,
                "total_hits": total_hits,
                "cache_path": str(self._cache_path),
                "ttl_seconds": self._ttl,
            }

    def flush(self):
        """立即持久化缓存到磁盘"""
        with self._lock:
            self._save()


# ── 全局单例 ──
_label_cache_instance: LabelCache | None = None


def get_label_cache() -> LabelCache:
    """获取 LabelCache 单例"""
    global _label_cache_instance
    if _label_cache_instance is None:
        _label_cache_instance = LabelCache()
    return _label_cache_instance
