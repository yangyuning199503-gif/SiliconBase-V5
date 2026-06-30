"""
Gamification API - 游戏化系统接口
提供用户等级、经验值、工具解锁进度等功能

功能：
1. 获取用户游戏化状态（等级、经验值、进度）
2. 获取工具分类解锁进度
3. 记录用户获得的经验值
4. 获取解锁成就列表
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# CORS 响应头
def cors_response(data: dict[str, Any]) -> JSONResponse:
    """返回带CORS头的JSON响应"""
    response = JSONResponse(content=data)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    return response

# 导入认证依赖
try:
    from api.cloud_api import get_current_user
    AUTH_AVAILABLE = True
except ImportError:
    try:
        from .cloud_api import get_current_user
        AUTH_AVAILABLE = True
    except ImportError:
        AUTH_AVAILABLE = False

        async def get_current_user() -> str | None:
            return "default_user"

router = APIRouter(prefix="/gamification", tags=["gamification"])

# 安全常量定义
MAX_XP_PER_ACTION = 100  # 单次最大经验值
VALID_XP_SOURCES = {"tool_usage", "task_complete", "achievement", "daily_login", "streak_bonus"}

# 全局锁保护文件操作
_gamification_lock = asyncio.Lock()


class RateLimiter:
    """简单内存频率限制器"""
    def __init__(self, max_calls: int = 10, window: int = 60):
        self.max_calls = max_calls
        self.window = window
        self.calls: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    async def is_allowed(self, client_id: str) -> bool:
        async with self._lock:
            now = time.time()

            # 【修复】清理所有过期记录，防止内存无限增长
            for cid in list(self.calls.keys()):
                self.calls[cid] = [t for t in self.calls[cid] if now - t < self.window]
                if not self.calls[cid]:
                    del self.calls[cid]

            if client_id not in self.calls:
                self.calls[client_id] = []

            if len(self.calls[client_id]) >= self.max_calls:
                return False

            self.calls[client_id].append(now)
            return True

# XP 添加频率限制器：每分钟最多10次
_xp_rate_limiter = RateLimiter(max_calls=10, window=60)


def _normalize_user_id(user_id: str | None) -> str:
    """
    标准化用户ID，确保一致性

    规则：
    - None/空字符串 → "default_user"
    - "console"/"anonymous"/"default" → "default_user"
    - 其他 → 原值
    """
    if not user_id or user_id in ["console", "anonymous", "default", ""]:
        return "default_user"
    return user_id


# 数据存储路径
DATA_DIR = Path(__file__).parent.parent / "data"
GAMIFICATION_FILE = DATA_DIR / "gamification.json"

# 等级配置
LEVEL_CONFIG = {
    1: {"name": "新手", "min_xp": 0, "max_xp": 100, "color": "#9E9E9E"},
    2: {"name": "进阶", "min_xp": 100, "max_xp": 300, "color": "#2196F3"},
    3: {"name": "熟练", "min_xp": 300, "max_xp": 600, "color": "#4CAF50"},
    4: {"name": "专家", "min_xp": 600, "max_xp": 1000, "color": "#9C27B0"},
    5: {"name": "大师", "min_xp": 1000, "max_xp": 1500, "color": "#FF9800"},
    6: {"name": "传说", "min_xp": 1500, "max_xp": 999999, "color": "#FFD700"},
}

# 分类解锁配置（对应 tool_categories.py 中的配置）
CATEGORY_UNLOCK_CONFIG = {
    "输入类": {"unlock_level": 1, "icon": "⌨️", "color": "#4CAF50"},
    "窗口类": {"unlock_level": 1, "icon": "🪟", "color": "#2196F3"},
    "文件类": {"unlock_level": 1, "icon": "📁", "color": "#FF9800"},
    "记忆类": {"unlock_level": 1, "icon": "🧠", "color": "#E91E63"},
    "系统类": {"unlock_level": 1, "icon": "⚙️", "color": "#607D8B"},
    "应用启动类": {"unlock_level": 1, "icon": "🚀", "color": "#8BC34A"},
    "其他": {"unlock_level": 1, "icon": "📦", "color": "#9E9E9E"},
    "网页类": {"unlock_level": 2, "icon": "🌐", "color": "#9C27B0"},
    "屏幕识别类": {"unlock_level": 2, "icon": "👁️", "color": "#00BCD4"},
    "数据处理类": {"unlock_level": 2, "icon": "📊", "color": "#3F51B5"},
    "通信类": {"unlock_level": 2, "icon": "📡", "color": "#009688"},
    "自动化类": {"unlock_level": 3, "icon": "🤖", "color": "#FF5722"},
}


def _ensure_data_dir():
    """确保数据目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_gamification_data() -> dict[str, Any]:
    """加载游戏化数据"""
    _ensure_data_dir()
    if GAMIFICATION_FILE.exists():
        try:
            with open(GAMIFICATION_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[GamificationAPI] 加载游戏化数据失败: {e}", exc_info=True)
    return {}


def _save_gamification_data(data: dict[str, Any]):
    """保存游戏化数据"""
    _ensure_data_dir()
    with open(GAMIFICATION_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def _load_gamification_data_async() -> dict[str, Any]:
    """异步加载游戏化数据"""
    return await asyncio.to_thread(_load_gamification_data)


async def _save_gamification_data_async(data: dict[str, Any]):
    """异步保存游戏化数据"""
    await asyncio.to_thread(_save_gamification_data, data)


def _get_user_data(user_id: str) -> dict[str, Any]:
    """获取用户游戏化数据"""
    # 标准化用户ID
    user_id = _normalize_user_id(user_id)

    data = _load_gamification_data()
    if user_id not in data:
        # 初始化新用户数据
        data[user_id] = {
            "level": 1,
            "xp": 0,
            "total_xp_earned": 0,
            "tools_used": {},  # tool_id -> count
            "categories_unlocked": [],
            "achievements": [],
            "created_at": time.time(),
            "last_active": time.time()
        }
        _save_gamification_data(data)
    return data[user_id]


def _calculate_level(xp: int) -> int:
    """根据经验值计算等级"""
    for level in sorted(LEVEL_CONFIG.keys(), reverse=True):
        if xp >= LEVEL_CONFIG[level]["min_xp"]:
            return level
    return 1


def _get_level_progress(xp: int) -> dict[str, Any]:
    """获取等级进度信息"""
    level = _calculate_level(xp)
    config = LEVEL_CONFIG.get(level, LEVEL_CONFIG[1])
    min_xp = config["min_xp"]
    max_xp = config["max_xp"]
    progress = ((xp - min_xp) / (max_xp - min_xp)) * 100 if max_xp > min_xp else 100

    return {
        "current_level": level,
        "current_xp": xp,
        "min_xp": min_xp,
        "max_xp": max_xp,
        "progress_percent": min(progress, 100),
        "xp_to_next": max(0, max_xp - xp),
        "level_name": config["name"],
        "level_color": config["color"]
    }


def _get_category_progress(user_level: int) -> list[dict[str, Any]]:
    """获取分类解锁进度"""
    result = []
    for category, config in CATEGORY_UNLOCK_CONFIG.items():
        required_level = config["unlock_level"]
        is_unlocked = user_level >= required_level
        result.append({
            "name": category,
            "icon": config["icon"],
            "color": config["color"],
            "unlock_level": required_level,
            "is_unlocked": is_unlocked,
            "progress": 100 if is_unlocked else (user_level / required_level) * 100
        })
    return result


# ============ API 端点 ============

@router.get("/status")
async def get_gamification_status(
    user_id: str = Depends(get_current_user)
):
    """
    获取用户游戏化状态

    返回：
    - 当前等级、经验值
    - 等级进度
    - 工具分类解锁状态
    - 统计信息
    """
    # 标准化用户ID
    normalized_user_id = _normalize_user_id(user_id)
    user_data = _get_user_data(normalized_user_id)
    level_progress = _get_level_progress(user_data["xp"])
    categories = _get_category_progress(level_progress["current_level"])

    # 统计已解锁分类数
    unlocked_count = sum(1 for c in categories if c["is_unlocked"])

    return {
        "success": True,
        "data": {
            "user_id": normalized_user_id,
            "level": level_progress,
            "categories": categories,
            "stats": {
                "total_tools_used": sum(user_data["tools_used"].values()),
                "unique_tools_used": len(user_data["tools_used"]),
                "categories_unlocked": unlocked_count,
                "total_categories": len(categories),
                "achievements_count": len(user_data.get("achievements", []))
            },
            "recent_activity": {
                "last_active": user_data.get("last_active"),
                "account_created": user_data.get("created_at")
            }
        }
    }


@router.get("/level")
async def get_level_info(
    user_id: str = Depends(get_current_user)
):
    """
    获取等级信息（简化版，用于顶部栏显示）
    """
    # 标准化用户ID
    normalized_user_id = _normalize_user_id(user_id)
    user_data = _get_user_data(normalized_user_id)
    progress = _get_level_progress(user_data["xp"])

    return {
        "success": True,
        "data": {
            "level": progress["current_level"],
            "level_name": progress["level_name"],
            "xp": progress["current_xp"],
            "xp_to_next": progress["xp_to_next"],
            "progress_percent": round(progress["progress_percent"], 1),
            "color": progress["level_color"]
        }
    }


@router.post("/add-xp")
async def add_experience(
    xp_amount: int,
    source: str = "tool_usage",
    user_id: str = Depends(get_current_user),
    request: Request = None
):
    """
    增加用户经验值

    参数：
    - xp_amount: 增加的经验值数量，最大100
    - source: 经验来源（tool_usage, task_complete, achievement, daily_login, streak_bonus）
    """
    # 标准化用户ID
    normalized_user_id = _normalize_user_id(user_id)

    # 频率限制检查
    if not await _xp_rate_limiter.is_allowed(normalized_user_id):
        logger.error(f"[Gamification] 经验值添加过于频繁, user: {user_id}")
        raise HTTPException(status_code=429, detail="经验值添加过于频繁，请稍后再试")

    # 验证经验值上限
    if xp_amount > MAX_XP_PER_ACTION:
        logger.error(f"[Gamification] 经验值超出上限: {xp_amount}, user: {user_id}")
        raise HTTPException(status_code=400, detail=f"经验值单次上限为 {MAX_XP_PER_ACTION}")

    # 验证经验值不能为负数
    if xp_amount < 0:
        logger.error(f"[Gamification] 经验值不能为负数: {xp_amount}, user: {user_id}")
        raise HTTPException(status_code=400, detail="经验值不能为负数")

    # 验证来源合法性
    if source not in VALID_XP_SOURCES:
        logger.error(f"[Gamification] 非法经验来源: {source}, user: {user_id}")
        raise HTTPException(status_code=400, detail=f"非法经验来源: {source}")

    # 使用锁保护并发数据操作
    async with _gamification_lock:
        data = _load_gamification_data()
        if normalized_user_id not in data:
            data[normalized_user_id] = _get_user_data(normalized_user_id)

        old_level = _calculate_level(data[normalized_user_id]["xp"])
        data[normalized_user_id]["xp"] += xp_amount
        data[normalized_user_id]["total_xp_earned"] += xp_amount
        data[normalized_user_id]["last_active"] = time.time()
        new_level = _calculate_level(data[normalized_user_id]["xp"])

        _save_gamification_data(data)

    # 检查是否升级
    level_up = new_level > old_level

    return {
        "success": True,
        "data": {
            "xp_added": xp_amount,
            "source": source,
            "new_total_xp": data[normalized_user_id]["xp"],
            "old_level": old_level,
            "new_level": new_level,
            "level_up": level_up,
            "message": f"获得 {xp_amount} 经验值！" + (" 升级了！" if level_up else "")
        }
    }


@router.post("/record-tool-usage")
async def record_tool_usage(
    tool_id: str,
    xp_earned: int = 10,
    user_id: str = Depends(get_current_user)
):
    """
    记录工具使用并获得经验值

    参数：
    - tool_id: 使用的工具ID
    - xp_earned: 获得的经验值（根据工具稀有度决定），最大100
    """
    # 标准化用户ID
    normalized_user_id = _normalize_user_id(user_id)

    # 频率限制检查
    if not await _xp_rate_limiter.is_allowed(normalized_user_id):
        logger.error(f"[Gamification] 经验值添加过于频繁, user: {user_id}")
        raise HTTPException(status_code=429, detail="经验值添加过于频繁，请稍后再试")

    # 验证经验值上限
    if xp_earned > MAX_XP_PER_ACTION:
        logger.error(f"[Gamification] 经验值超出上限: {xp_earned}, user: {user_id}")
        raise HTTPException(status_code=400, detail=f"经验值单次上限为 {MAX_XP_PER_ACTION}")

    # 验证经验值不能为负数
    if xp_earned < 0:
        logger.error(f"[Gamification] 经验值不能为负数: {xp_earned}, user: {user_id}")
        raise HTTPException(status_code=400, detail="经验值不能为负数")

    # 使用锁保护并发数据操作
    async with _gamification_lock:
        data = _load_gamification_data()
        if normalized_user_id not in data:
            data[normalized_user_id] = _get_user_data(normalized_user_id)

        # 记录工具使用次数
        if tool_id not in data[normalized_user_id]["tools_used"]:
            data[normalized_user_id]["tools_used"][tool_id] = 0
        data[normalized_user_id]["tools_used"][tool_id] += 1

        # 增加经验值
        old_level = _calculate_level(data[normalized_user_id]["xp"])
        data[normalized_user_id]["xp"] += xp_earned
        data[normalized_user_id]["total_xp_earned"] += xp_earned
        data[normalized_user_id]["last_active"] = time.time()
        new_level = _calculate_level(data[normalized_user_id]["xp"])

        _save_gamification_data(data)

    level_up = new_level > old_level

    return {
        "success": True,
        "data": {
            "tool_id": tool_id,
            "xp_earned": xp_earned,
            "tool_use_count": data[normalized_user_id]["tools_used"][tool_id],
            "new_total_xp": data[normalized_user_id]["xp"],
            "level_up": level_up,
            "new_level": new_level if level_up else None
        }
    }


@router.get("/categories")
async def get_category_unlock_status(
    user_id: str = Depends(get_current_user)
):
    """
    获取工具分类解锁状态
    """
    # 标准化用户ID
    normalized_user_id = _normalize_user_id(user_id)
    user_data = _get_user_data(normalized_user_id)
    level = _calculate_level(user_data["xp"])
    categories = _get_category_progress(level)

    return {
        "success": True,
        "data": {
            "current_level": level,
            "categories": categories
        }
    }


@router.get("/achievements")
async def get_achievements(
    user_id: str = Depends(get_current_user)
):
    """
    获取用户成就列表
    """
    # 标准化用户ID
    normalized_user_id = _normalize_user_id(user_id)
    user_data = _get_user_data(normalized_user_id)

    # 计算可以获得的成就
    available_achievements = _calculate_achievements(user_data)

    return {
        "success": True,
        "data": {
            "earned": user_data.get("achievements", []),
            "available": available_achievements,
            "total_earned": len(user_data.get("achievements", [])),
            "total_available": len(available_achievements)
        }
    }


def _calculate_achievements(user_data: dict[str, Any]) -> list[dict[str, Any]]:
    """计算用户可获得的成就"""
    achievements = []
    tools_used = user_data.get("tools_used", {})
    total_uses = sum(tools_used.values())
    unique_tools = len(tools_used)

    # 工具使用相关成就
    if total_uses >= 1:
        achievements.append({
            "id": "first_tool",
            "name": "初次尝试",
            "description": "第一次使用工具",
            "icon": "🔧",
            "earned": True
        })

    if total_uses >= 10:
        achievements.append({
            "id": "tool_user",
            "name": "工具使用者",
            "description": "累计使用工具10次",
            "icon": "🛠️",
            "earned": True
        })

    if total_uses >= 100:
        achievements.append({
            "id": "tool_master",
            "name": "工具大师",
            "description": "累计使用工具100次",
            "icon": "⚡",
            "earned": True
        })

    if unique_tools >= 5:
        achievements.append({
            "id": "tool_explorer",
            "name": "工具探索者",
            "description": "使用过5种不同的工具",
            "icon": "🔍",
            "earned": True
        })

    if unique_tools >= 20:
        achievements.append({
            "id": "tool_collector",
            "name": "工具收藏家",
            "description": "使用过20种不同的工具",
            "icon": "📚",
            "earned": True
        })

    # 等级相关成就
    level = _calculate_level(user_data.get("xp", 0))
    if level >= 3:
        achievements.append({
            "id": "level_3",
            "name": "进阶用户",
            "description": "达到等级3",
            "icon": "⭐",
            "earned": True
        })

    if level >= 5:
        achievements.append({
            "id": "level_5",
            "name": "专家用户",
            "description": "达到等级5",
            "icon": "🌟",
            "earned": True
        })

    return achievements


@router.get("/leaderboard")
async def get_leaderboard(
    limit: int = 10,
    user_id: str = Depends(get_current_user)
):
    """
    获取排行榜
    """
    # 标准化用户ID
    normalized_user_id = _normalize_user_id(user_id)

    data = _load_gamification_data()

    # 构建排行榜
    leaderboard = []
    for uid, user_data in data.items():
        progress = _get_level_progress(user_data.get("xp", 0))
        leaderboard.append({
            "user_id": uid,
            "level": progress["current_level"],
            "level_name": progress["level_name"],
            "xp": user_data.get("xp", 0),
            "total_tools_used": sum(user_data.get("tools_used", {}).values()),
            "is_current_user": uid == normalized_user_id
        })

    # 按经验值排序
    leaderboard.sort(key=lambda x: x["xp"], reverse=True)

    # 添加排名
    for i, entry in enumerate(leaderboard, 1):
        entry["rank"] = i

    return {
        "success": True,
        "data": {
            "leaderboard": leaderboard[:limit],
            "current_user_rank": next(
                (entry["rank"] for entry in leaderboard if entry["is_current_user"]),
                None
            )
        }
    }


# 处理 CORS 预检请求 (OPTIONS)
@router.options("/{path:path}")
async def options_handler(path: str):
    """处理所有 OPTIONS 预检请求"""
    print(f"[Gamification API] 收到 OPTIONS 请求: /{path}")
    from fastapi.responses import Response
    response = Response(content="")
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Requested-With"
    response.headers["Access-Control-Max-Age"] = "600"
    return response
