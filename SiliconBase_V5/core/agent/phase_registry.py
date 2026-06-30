from collections.abc import Callable

from core.logger import logger

_phase_handlers: dict[str, dict] = {}


def register_phase(name: str, handler: Callable, order: int = 0):
    """阶段自注册——外迁阶段文件底部调用这个"""
    _phase_handlers[name] = {"handler": handler, "order": order}
    logger.info("[PhaseRegistry] 注册阶段: %s (order=%d)", name, order)


def get_phases() -> list[tuple]:
    """获取按顺序排列的阶段列表"""
    return sorted(_phase_handlers.items(), key=lambda x: x[1]["order"])


def clear_phases():
    _phase_handlers.clear()
