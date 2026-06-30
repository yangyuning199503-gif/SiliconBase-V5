#!/usr/bin/env python3
"""
ExperienceAdapters - 7个数据源适配器

所有适配器把各自模块的数据转换成 ExperienceEvent，publish 到 ExperienceBus。

适配器列表：
1. ToolExperienceAdapter      - 工具执行结果（事件驱动）
2. RLHFExperienceAdapter      - 用户点赞/点踩/星级（文件轮询）
3. SensorExperienceAdapter    - 传感器数据（SystemState轮询）
4. MemoryExperienceAdapter    - 记忆访问/晋升（数据库轮询）
5. EvolutionExperienceAdapter - 进化经验（内存轮询）
6. ReflectExperienceAdapter   - 反思策略（内存轮询）
7. TradeExperienceAdapter     - 交易盈亏（WebSocket/轮询）

设计原则：
- 不改动现有模块代码，只消费已有的事件/文件/状态
- 每个适配器独立运行，互不影响
- 异常被吞掉，不阻塞主循环
"""

import asyncio
import contextlib
import json
import time
from pathlib import Path
from typing import Any

from core.consciousness.experience_bus import ExperienceBus, ExperienceEvent
from core.diagnostic import safe_create_task
from core.logger import logger
from core.sync.event_bus import Event


# ═══════════════════════════════════════════════════════════════════════
# 基类
# ═══════════════════════════════════════════════════════════════════════
class BaseExperienceAdapter:
    """适配器基类"""

    INTERVAL = 30  # 默认轮询间隔（秒）

    def __init__(self, bus: ExperienceBus):
        self.bus = bus
        self._running = False
        self._task: asyncio.Task | None = None
        self._event_count = 0

    async def start(self):
        """启动适配器"""
        self._running = True
        self._task = safe_create_task(self._loop(), name="_loop")
        logger.info(f"[ExperienceAdapter] {self.__class__.__name__} 已启动")

    async def stop(self):
        """停止适配器"""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self):
        """主循环：定期调用 _collect"""
        while self._running:
            try:
                await self._collect()
            except Exception as e:
                logger.debug(f"[ExperienceAdapter] {self.__class__.__name__} 采集异常: {e}")
            await asyncio.sleep(self.INTERVAL)

    async def _collect(self):
        """子类实现：采集数据并publish到bus"""
        raise NotImplementedError

    async def _publish(self, event: ExperienceEvent):
        """安全发布"""
        success = await self.bus.publish(event)
        if success:
            self._event_count += 1


# ═══════════════════════════════════════════════════════════════════════
# 适配器1：工具执行结果（事件驱动）
# ═══════════════════════════════════════════════════════════════════════
class ToolExperienceAdapter(BaseExperienceAdapter):
    """
    监听 event_bus 的 tool:executed 事件。

    事件格式：{
        "tool_id": str,
        "params": dict,
        "success": bool,
        "result": Any,
        "error_code": str,
        "duration": float,
        "timestamp": float,
        "source": str,
        "user_id": str
    }
    """
    INTERVAL = 999999  # 事件驱动，不需要轮询

    def __init__(self, bus: ExperienceBus):
        super().__init__(bus)
        self._handler_registered = False

    async def start(self):
        """订阅 event_bus 的 tool:executed 事件"""
        self._running = True
        try:
            from core.sync.event_bus import event_bus
            event_bus.subscribe("tool:executed", self._on_tool_executed)
            logger.info("[ExperienceAdapter] ToolExperienceAdapter 已订阅 tool:executed")
            self._handler_registered = True
        except Exception as e:
            logger.warning(f"[ExperienceAdapter] ToolExperienceAdapter 订阅失败: {e}")

    def _on_tool_executed(self, event: Event):
        """工具执行事件回调"""
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            success = event_data.get("success", False)
            duration = event_data.get("duration", 0.0)
            error_code = event_data.get("error_code")

            # outcome计算：成功=1.0，失败=0.0
            # 如果失败但有错误码，根据错误码类型微调
            if success:
                outcome = 1.0
            else:
                outcome = 0.0
                # 某些错误码代表"用户取消"或"权限不足"，不算完全失败
                if error_code in ("PERMISSION_DENIED", "USER_CANCELLED", "TOOL_TIMEOUT"):
                    outcome = 0.3

            # 耗时奖励：快速执行（<1秒）额外+0.05
            if success and duration < 1.0:
                outcome = min(1.0, outcome + 0.05)
            # 耗时惩罚：慢执行（>10秒）-0.1
            elif success and duration > 10.0:
                outcome = max(0.0, outcome - 0.1)

            safe_create_task(self._publish(ExperienceEvent(
                source="tool",
                event_type="executed",
                timestamp=event_data.get("timestamp", time.time()),
                action=event_data.get("tool_id", "unknown"),
                outcome=outcome,
                weight=1.0,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[ToolAdapter] 处理事件异常: {e}")

    async def _collect(self):
        pass  # 事件驱动，不需要轮询


# ═══════════════════════════════════════════════════════════════════════
# 适配器2：RLHF 用户反馈（文件轮询）
# ═══════════════════════════════════════════════════════════════════════
class RLHFExperienceAdapter(BaseExperienceAdapter):
    """
    定期扫描 core/data/rlhf/*.jsonl 文件，读取用户反馈。

    反馈类型：
    - response_feedback.jsonl: 点赞/点踩 + 文字评论
    - task_feedback.jsonl: 1-5星评分 + 文字评论
    """
    INTERVAL = 30  # 每30秒扫描一次

    def __init__(self, bus: ExperienceBus):
        super().__init__(bus)
        self._last_positions: dict[str, int] = {}
        self._data_dir = Path("core/data/rlhf")

    async def _collect(self):
        if not self._data_dir.exists():
            return

        for filename in ["response_feedback.jsonl", "task_feedback.jsonl"]:
            filepath = self._data_dir / filename
            if not filepath.exists():
                continue

            try:
                await self._scan_file(filepath)
            except Exception as e:
                logger.debug(f"[RLHFAdapter] 扫描 {filename} 异常: {e}")

    async def _scan_file(self, filepath: Path):
        """扫描文件的增量内容"""
        last_pos = self._last_positions.get(str(filepath), 0)
        current_size = filepath.stat().st_size

        if current_size <= last_pos:
            return  # 没有新内容

        # 如果文件被截断（rotate），重置位置
        if current_size < last_pos:
            last_pos = 0

        # 异步读取新行
        loop = asyncio.get_event_loop()
        lines = await loop.run_in_executor(None, self._read_lines, filepath, last_pos)

        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                event = self._parse_record(record)
                if event:
                    await self._publish(event)
            except Exception:
                pass

        # 更新位置
        self._last_positions[str(filepath)] = current_size

    def _read_lines(self, filepath: Path, offset: int) -> list:
        """同步读取文件新行"""
        with open(filepath, encoding="utf-8") as f:
            f.seek(offset)
            return f.readlines()

    def _parse_record(self, record: dict) -> ExperienceEvent | None:
        """解析单条反馈记录"""
        feedback_type = record.get("feedback_type", "")

        if "task" in record:
            # task_feedback.jsonl 格式
            score = record.get("feedback_score", 3)  # 1-5
            outcome = (score - 1) / 4.0  # 归一化到 0~1
            action = record.get("task_id", "task")
            raw = record
        elif "response" in record or "feedback_type" in record:
            # response_feedback.jsonl 格式
            if feedback_type == "positive":
                outcome = 1.0
            elif feedback_type == "negative":
                outcome = 0.0
            else:
                return None
            action = record.get("response_id", "response")
            raw = record
        else:
            return None

        return ExperienceEvent(
            source="rlhf",
            event_type="user_feedback",
            timestamp=record.get("timestamp", time.time()),
            action=action,
            outcome=outcome,
            weight=1.5,  # 用户反馈权重更高
            raw_data=raw
        )


# ═══════════════════════════════════════════════════════════════════════
# 适配器3：传感器数据（SystemState轮询）
# ═══════════════════════════════════════════════════════════════════════
class SensorExperienceAdapter(BaseExperienceAdapter):
    """
    定期从 SystemState 读取传感器数据，计算环境变化评分。
    同时订阅 PerceptionBus 动态事件（window_changed, process_monitor等）。

    关注指标：
    - CPU/内存负载变化
    - 前台应用切换
    - 窗口数量变化
    - 进程异常
    """
    INTERVAL = 10  # 每10秒采样一次

    def __init__(self, bus: ExperienceBus):
        super().__init__(bus)
        self._last_snapshot: dict | None = None
        self._handler_registered = False

    async def start(self):
        """启动轮询 + 订阅动态事件"""
        await super().start()
        try:
            from core.sync.event_bus import event_bus
            event_bus.subscribe("context:window_changed", self._on_window_changed)
            event_bus.subscribe("context:process_changed", self._on_process_changed)
            logger.info("[ExperienceAdapter] SensorExperienceAdapter 已订阅 PerceptionBus 事件")
            self._handler_registered = True
        except Exception as e:
            logger.warning(f"[ExperienceAdapter] SensorExperienceAdapter 订阅失败: {e}")

    def _on_window_changed(self, event: Event):
        """窗口变化事件回调"""
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            safe_create_task(self._publish(ExperienceEvent(
                source="sensor",
                event_type="window_changed",
                timestamp=time.time(),
                context={"window_title": event_data.get("window_title", ""), "app": event_data.get("app", "")},
                action="window_switch",
                outcome=0.6,  # 中性偏正面，用户活跃
                weight=0.5,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[SensorAdapter] 处理窗口事件异常: {e}")

    def _on_process_changed(self, event: Event):
        """进程变化事件回调"""
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            safe_create_task(self._publish(ExperienceEvent(
                source="sensor",
                event_type="process_changed",
                timestamp=time.time(),
                context={"process_name": event_data.get("process_name", "")},
                action="process_event",
                outcome=0.5,
                weight=0.3,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[SensorAdapter] 处理进程事件异常: {e}")

    async def _collect(self):
        try:
            from core.runtime import system_state

            # 读取当前系统状态
            cpu = system_state.get_sync("system.cpu_percent", 0)
            memory = system_state.get_sync("system.memory_percent", 0)
            vision_tags = system_state.get_sync("consciousness.vision_tags", [])
            alert = system_state.get_sync("vision.alert", {})
            dominant_app = system_state.get_sync("vision.dominant_app", "")

            snapshot = {
                "cpu": cpu,
                "memory": memory,
                "vision_count": len(vision_tags),
                "alert_level": alert.get("level", ""),
                "dominant_app": dominant_app,
                "timestamp": time.time(),
            }

            if self._last_snapshot is None:
                self._last_snapshot = snapshot
                return

            # 计算变化评分
            outcome = self._compute_outcome(self._last_snapshot, snapshot)

            if outcome != 0.5:  # 只有有变化时才发布
                await self._publish(ExperienceEvent(
                    source="sensor",
                    event_type="environment_change",
                    timestamp=snapshot["timestamp"],
                    action=f"app:{dominant_app}",
                    outcome=outcome,
                    weight=0.5,  # 传感器权重较低
                    raw_data={"before": self._last_snapshot, "after": snapshot}
                ))

            self._last_snapshot = snapshot
        except Exception as e:
            logger.debug(f"[SensorAdapter] 采集异常: {e}")

    def _compute_outcome(self, before: dict, after: dict) -> float:
        """计算环境变化的结果评分"""
        score = 0.5  # 中性基线

        # CPU 突增 = 负面（0.3）
        cpu_delta = after.get("cpu", 0) - before.get("cpu", 0)
        if cpu_delta > 30:
            score -= 0.2

        # 告警出现 = 负面（0.2）
        if after.get("alert_level") and not before.get("alert_level"):
            score -= 0.3

        # 应用切换 = 中性偏正面（0.6），用户活跃
        if after.get("dominant_app") != before.get("dominant_app"):
            score += 0.1

        # 视觉元素增多 = 正面（0.7），内容丰富
        vision_delta = after.get("vision_count", 0) - before.get("vision_count", 0)
        if vision_delta > 5:
            score += 0.1

        return max(0.0, min(1.0, score))


# ═══════════════════════════════════════════════════════════════════════
# 适配器4：记忆系统（数据库轮询）
# ═══════════════════════════════════════════════════════════════════════
class MemoryExperienceAdapter(BaseExperienceAdapter):
    """
    定期查询记忆系统，获取最近记忆的创建/访问/评分变化。

    关注指标：
    - 新记忆的平均评分
    - 记忆的访问频率
    - 记忆的晋升/遗忘
    """
    INTERVAL = 60  # 每60秒查询一次

    def __init__(self, bus: ExperienceBus):
        super().__init__(bus)
        self._last_query_time = time.time() - 3600  # 初始查询过去1小时

    async def _collect(self):
        try:
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()

            # 查询最近创建的记忆
            recent_memories = await ms.search_similar(
                query="recent memories",
                top_k=10
            )

            if not recent_memories:
                return

            total_rating = 0.0
            total_score = 0.0
            count = 0

            for mem in recent_memories:
                meta = mem.get("metadata", {})
                rating = meta.get("rating", 0)
                value = meta.get("value_assessment", {})
                overall = value.get("overall_score", 0.5) if isinstance(value, dict) else 0.5

                total_rating += rating / 10.0  # rating 是 0-10
                total_score += overall
                count += 1

            if count == 0:
                return

            avg_rating = total_rating / count
            avg_score = total_score / count

            # 记忆质量 = 评分 × 价值评分
            outcome = (avg_rating + avg_score) / 2.0

            await self._publish(ExperienceEvent(
                source="memory",
                event_type="memory_quality",
                timestamp=time.time(),
                action=f"recent_{count}_memories",
                outcome=outcome,
                weight=0.8,
                raw_data={"avg_rating": avg_rating, "avg_score": avg_score, "count": count}
            ))

        except Exception as e:
            logger.debug(f"[MemoryAdapter] 采集异常: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 适配器5：进化系统（内存轮询）
# ═══════════════════════════════════════════════════════════════════════
class EvolutionExperienceAdapter(BaseExperienceAdapter):
    """
    定期从进化引擎获取最新经验记录。

    关注指标：
    - 新经验的 effectiveness 评分
    - 策略的 success_rate 变化
    """
    INTERVAL = 60  # 每60秒查询一次

    async def _collect(self):
        try:
            from core.evolution.evolution import get_evolution_engine
            engine = get_evolution_engine()

            if not engine or not hasattr(engine, "experiences"):
                return

            experiences = getattr(engine, "experiences", [])
            if not experiences:
                return

            # 只取最近10条
            recent = list(experiences)[-10:]

            total_effectiveness = 0.0
            total_value = 0.0
            count = 0

            for exp in recent:
                eff = getattr(exp, "effectiveness", 0.5)
                val = getattr(exp, "value_score", 0.5)
                total_effectiveness += eff
                total_value += val
                count += 1

            if count == 0:
                return

            outcome = (total_effectiveness / count + total_value / count) / 2.0

            await self._publish(ExperienceEvent(
                source="evolution",
                event_type="experience_learned",
                timestamp=time.time(),
                action=f"learned_{count}_experiences",
                outcome=outcome,
                weight=1.0,
                raw_data={"avg_effectiveness": total_effectiveness / count, "count": count}
            ))

        except Exception as e:
            logger.debug(f"[EvolutionAdapter] 采集异常: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 适配器6：反思系统（内存轮询）
# ═══════════════════════════════════════════════════════════════════════
class ReflectExperienceAdapter(BaseExperienceAdapter):
    """
    定期从反思系统获取最新策略模式。

    关注指标：
    - 策略模式的 success_rate
    - 反思的 quality_score
    """
    INTERVAL = 120  # 每120秒查询一次（反思不频繁）

    async def _collect(self):
        try:
            from core.reflector.reflector import get_reflector
            reflector = get_reflector()

            if not reflector:
                return

            # 获取策略模式
            patterns = []
            if hasattr(reflector, "strategy_patterns"):
                patterns = list(reflector.strategy_patterns.values())[-5:]
            elif hasattr(reflector, "_strategy_patterns"):
                patterns = list(reflector._strategy_patterns.values())[-5:]

            if not patterns:
                return

            total_success_rate = 0.0
            count = 0

            for p in patterns:
                sr = getattr(p, "success_rate", 0.5)
                total_success_rate += sr
                count += 1

            outcome = total_success_rate / count if count > 0 else 0.5

            await self._publish(ExperienceEvent(
                source="reflect",
                event_type="strategy_updated",
                timestamp=time.time(),
                action=f"updated_{count}_patterns",
                outcome=outcome,
                weight=1.0,
                raw_data={"avg_success_rate": outcome, "count": count}
            ))

        except Exception as e:
            logger.debug(f"[ReflectAdapter] 采集异常: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 适配器7：交易系统（WebSocket/轮询）
# ═══════════════════════════════════════════════════════════════════════
class TradeExperienceAdapter(BaseExperienceAdapter):
    """
    定期从交易系统获取最新交易结果。

    关注指标：
    - 最近交易的盈亏
    - 决策正确率
    """
    INTERVAL = 60  # 每60秒查询一次

    async def _collect(self):
        try:
            from core.btc_integration.ai_trading_manager import get_ai_trading_manager
            manager = get_ai_trading_manager()

            if not manager:
                return

            # 尝试获取最近的交易记录
            recent_trades = []
            if hasattr(manager, "trade_history"):
                recent_trades = list(manager.trade_history)[-5:]
            elif hasattr(manager, "_trade_history"):
                recent_trades = list(manager._trade_history)[-5:]

            if not recent_trades:
                return

            total_pnl = 0.0
            win_count = 0
            count = 0

            for trade in recent_trades:
                pnl = trade.get("pnl", 0) if isinstance(trade, dict) else getattr(trade, "pnl", 0)
                total_pnl += pnl
                if pnl > 0:
                    win_count += 1
                count += 1

            if count == 0:
                return

            # 胜率归一化到 0~1
            win_rate = win_count / count
            # 盈亏作为辅助信号：盈利>0 → 加分，亏损<0 → 减分
            pnl_signal = 0.5
            if total_pnl > 0:
                pnl_signal = min(1.0, 0.5 + total_pnl / 100.0)  # 假设100U为参考
            elif total_pnl < 0:
                pnl_signal = max(0.0, 0.5 + total_pnl / 100.0)

            outcome = (win_rate + pnl_signal) / 2.0

            await self._publish(ExperienceEvent(
                source="trade",
                event_type="trade_result",
                timestamp=time.time(),
                action=f"trades_{count}_win{win_count}",
                outcome=outcome,
                weight=0.8,
                raw_data={"total_pnl": total_pnl, "win_rate": win_rate, "count": count}
            ))

        except Exception as e:
            logger.debug(f"[TradeAdapter] 采集异常: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 适配器管理器：一键启动/停止所有适配器
# ═══════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════
# 适配器8：AgentLoop执行轨迹（事件驱动）
# ═══════════════════════════════════════════════════════════════════════
class AgentLoopExperienceAdapter(BaseExperienceAdapter):
    """
    订阅 agent_loop:hook_triggered 事件（仅用于调试/审计）。

    agent_loop:task_completed 不再通过 event_bus 转发，而是由 AgentLoop
    直接发布到当前用户的 ExperienceBus，避免重复计数。
    """
    INTERVAL = 999999

    def __init__(self, bus: ExperienceBus):
        super().__init__(bus)
        self._handler_registered = False

    async def start(self):
        self._running = True
        try:
            from core.sync.event_bus import event_bus
            event_bus.subscribe("agent_loop:hook_triggered", self._on_hook_triggered)
            logger.info("[ExperienceAdapter] AgentLoopExperienceAdapter 已订阅 hook_triggered")
            self._handler_registered = True
        except Exception as e:
            logger.warning(f"[ExperienceAdapter] AgentLoopAdapter 订阅失败: {e}")

    def _on_hook_triggered(self, event: Event):
        event_data = event.data
        try:
            hook_point = event_data.get("hook_point", "unknown")
            handler_count = event_data.get("handler_count", 0)
            safe_create_task(self._publish(ExperienceEvent(
                source="agent_loop",
                event_type="hook_triggered",
                timestamp=event_data.get("timestamp", time.time()),
                context={"session_id": event_data.get("session_id", "")},
                action=f"hook_{hook_point}",
                outcome=0.6 if handler_count > 0 else 0.3,
                weight=0.5,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[AgentLoopAdapter] 处理Hook事件异常: {e}")

    async def _collect(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
# 适配器9：对话系统（事件驱动）
# ═══════════════════════════════════════════════════════════════════════
class DialogueExperienceAdapter(BaseExperienceAdapter):
    """订阅 dialogue:voice_degraded / ptt_toggled / input_handled"""
    INTERVAL = 999999

    def __init__(self, bus: ExperienceBus):
        super().__init__(bus)
        self._handler_registered = False

    async def start(self):
        self._running = True
        try:
            from core.sync.event_bus import event_bus
            event_bus.subscribe("dialogue:voice_degraded", self._on_voice_degraded)
            event_bus.subscribe("dialogue:ptt_toggled", self._on_ptt_toggled)
            event_bus.subscribe("dialogue:input_handled", self._on_input_handled)
            logger.info("[ExperienceAdapter] DialogueExperienceAdapter 已订阅")
            self._handler_registered = True
        except Exception as e:
            logger.warning(f"[ExperienceAdapter] DialogueAdapter 订阅失败: {e}")

    def _on_voice_degraded(self, event: Event):
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            safe_create_task(self._publish(ExperienceEvent(
                source="dialogue",
                event_type="voice_degraded",
                timestamp=event_data.get("timestamp", time.time()),
                context={"user_id": event_data.get("user_id", ""), "session_id": event_data.get("session_id", "")},
                action="voice_to_text",
                outcome=0.2,  # 语音降级是负面信号
                weight=0.8,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[DialogueAdapter] 处理降级事件异常: {e}")

    def _on_ptt_toggled(self, event: Event):
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            active = event_data.get("active", False)
            safe_create_task(self._publish(ExperienceEvent(
                source="dialogue",
                event_type="ptt_toggled",
                timestamp=event_data.get("timestamp", time.time()),
                context={"user_id": event_data.get("user_id", "")},
                action="ptt_on" if active else "ptt_off",
                outcome=0.6 if active else 0.5,
                weight=0.3,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[DialogueAdapter] 处理PTT事件异常: {e}")

    def _on_input_handled(self, event: Event):
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            safe_create_task(self._publish(ExperienceEvent(
                source="dialogue",
                event_type="input_handled",
                timestamp=event_data.get("timestamp", time.time()),
                context={"user_id": event_data.get("user_id", ""), "session_id": event_data.get("session_id", ""), "input_mode": event_data.get("input_mode", "")},
                action="handle_input",
                outcome=0.7,  # 成功处理输入是正面信号
                weight=0.5,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[DialogueAdapter] 处理输入事件异常: {e}")

    async def _collect(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
# 适配器10：安全系统（事件驱动）
# ═══════════════════════════════════════════════════════════════════════
class SafetyExperienceAdapter(BaseExperienceAdapter):
    """订阅 safety:assessment / confirmation / accident"""
    INTERVAL = 999999

    def __init__(self, bus: ExperienceBus):
        super().__init__(bus)
        self._handler_registered = False

    async def start(self):
        self._running = True
        try:
            from core.sync.event_bus import event_bus
            event_bus.subscribe("safety:assessment", self._on_assessment)
            event_bus.subscribe("safety:confirmation", self._on_confirmation)
            event_bus.subscribe("safety:accident", self._on_accident)
            logger.info("[ExperienceAdapter] SafetyExperienceAdapter 已订阅")
            self._handler_registered = True
        except Exception as e:
            logger.warning(f"[ExperienceAdapter] SafetyAdapter 订阅失败: {e}")

    def _on_assessment(self, event: Event):
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            risk_level = event_data.get("risk_level", "SAFE")
            outcome = {"SAFE": 0.8, "NOTICE": 0.6, "CONFIRM": 0.4, "BLOCK": 0.1}.get(risk_level, 0.5)
            safe_create_task(self._publish(ExperienceEvent(
                source="safety",
                event_type="risk_assessment",
                timestamp=event_data.get("timestamp", time.time()),
                context={"user_id": event_data.get("user_id", ""), "tool_name": event_data.get("tool_name", "")},
                action=f"risk_{risk_level}",
                outcome=outcome,
                weight=0.7,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[SafetyAdapter] 处理评估事件异常: {e}")

    def _on_confirmation(self, event: Event):
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            confirmed = event_data.get("confirmed", False)
            safe_create_task(self._publish(ExperienceEvent(
                source="safety",
                event_type="user_confirmation",
                timestamp=event_data.get("timestamp", time.time()),
                context={"user_id": event_data.get("user_id", ""), "tool_name": event_data.get("tool_name", "")},
                action="confirmed" if confirmed else "denied",
                outcome=0.7 if confirmed else 0.3,
                weight=0.9,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[SafetyAdapter] 处理确认事件异常: {e}")

    def _on_accident(self, event: Event):
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            safe_create_task(self._publish(ExperienceEvent(
                source="safety",
                event_type="accident",
                timestamp=event_data.get("timestamp", time.time()),
                context={"user_id": event_data.get("user_id", ""), "tool_name": event_data.get("tool_name", "")},
                action="tool_accident",
                outcome=0.1,  # 事故是强负面信号
                weight=1.2,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[SafetyAdapter] 处理事故事件异常: {e}")

    async def _collect(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
# 适配器11：意图系统（事件驱动）
# ═══════════════════════════════════════════════════════════════════════
class IntentExperienceAdapter(BaseExperienceAdapter):
    """订阅 intent:tool_executed"""
    INTERVAL = 999999

    def __init__(self, bus: ExperienceBus):
        super().__init__(bus)
        self._handler_registered = False

    async def start(self):
        self._running = True
        try:
            from core.sync.event_bus import event_bus
            event_bus.subscribe("intent:tool_executed", self._on_tool_executed)
            event_bus.subscribe("intent:moral_blocked", self._on_moral_blocked)
            logger.info("[ExperienceAdapter] IntentExperienceAdapter 已订阅")
            self._handler_registered = True
        except Exception as e:
            logger.warning(f"[ExperienceAdapter] IntentAdapter 订阅失败: {e}")

    def _on_tool_executed(self, event: Event):
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            success = event_data.get("success", False)
            safe_create_task(self._publish(ExperienceEvent(
                source="intent",
                event_type="tool_executed",
                timestamp=event_data.get("timestamp", time.time()),
                context={"session_id": event_data.get("session_id", ""), "tool_id": event_data.get("tool_id", "")},
                action=event_data.get("tool_id", "unknown"),
                outcome=1.0 if success else 0.2,
                weight=0.8,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[IntentAdapter] 处理事件异常: {e}")

    def _on_moral_blocked(self, event: Event):
        event_data = event.data
        try:
            safe_create_task(self._publish(ExperienceEvent(
                source="intent",
                event_type="moral_blocked",
                timestamp=event_data.get("timestamp", time.time()),
                context={"session_id": event_data.get("session_id", ""), "tool_id": event_data.get("tool_id", "")},
                action="moral_block",
                outcome=0.2,  # 道德拦截是负面信号（用户想做但被阻止）
                weight=1.0,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[IntentAdapter] 处理道德拦截事件异常: {e}")

    async def _collect(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
# 适配器12：工作流系统（事件驱动）
# ═══════════════════════════════════════════════════════════════════════
class WorkflowExperienceAdapter(BaseExperienceAdapter):
    """订阅 workflow:step_completed"""
    INTERVAL = 999999

    def __init__(self, bus: ExperienceBus):
        super().__init__(bus)
        self._handler_registered = False

    async def start(self):
        self._running = True
        try:
            from core.sync.event_bus import event_bus
            event_bus.subscribe("workflow:step_completed", self._on_step_completed)
            event_bus.subscribe("workflow:step_failed", self._on_step_failed)
            logger.info("[ExperienceAdapter] WorkflowExperienceAdapter 已订阅")
            self._handler_registered = True
        except Exception as e:
            logger.warning(f"[ExperienceAdapter] WorkflowAdapter 订阅失败: {e}")

    def _on_step_completed(self, event: Event):
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            safe_create_task(self._publish(ExperienceEvent(
                source="workflow",
                event_type="step_completed",
                timestamp=event_data.get("timestamp", time.time()),
                context={"workflow_id": event_data.get("workflow_id", ""), "execution_id": event_data.get("execution_id", "")},
                action="workflow_step",
                outcome=0.7,
                weight=0.6,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[WorkflowAdapter] 处理事件异常: {e}")

    def _on_step_failed(self, event: Event):
        event_data = event.data
        try:
            safe_create_task(self._publish(ExperienceEvent(
                source="workflow",
                event_type="step_failed",
                timestamp=event_data.get("timestamp", time.time()),
                context={"workflow_id": event_data.get("workflow_id", ""), "step_id": event_data.get("step_id", "")},
                action="workflow_step_fail",
                outcome=0.2,  # 步骤失败是负面信号
                weight=0.8,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[WorkflowAdapter] 处理失败事件异常: {e}")

    async def _collect(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
# 适配器13：实时干预系统（事件驱动）
# ═══════════════════════════════════════════════════════════════════════
class InterventionExperienceAdapter(BaseExperienceAdapter):
    """订阅 intervention:submitted / applied"""
    INTERVAL = 999999

    def __init__(self, bus: ExperienceBus):
        super().__init__(bus)
        self._handler_registered = False

    async def start(self):
        self._running = True
        try:
            from core.sync.event_bus import event_bus
            event_bus.subscribe("intervention:submitted", self._on_submitted)
            event_bus.subscribe("intervention:applied", self._on_applied)
            logger.info("[ExperienceAdapter] InterventionExperienceAdapter 已订阅")
            self._handler_registered = True
        except Exception as e:
            logger.warning(f"[ExperienceAdapter] InterventionAdapter 订阅失败: {e}")

    def _on_submitted(self, event: Event):
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            safe_create_task(self._publish(ExperienceEvent(
                source="intervention",
                event_type="submitted",
                timestamp=event_data.get("timestamp", time.time()),
                context={"task_id": event_data.get("task_id", ""), "intervention_type": event_data.get("intervention_type", "")},
                action="user_intervention",
                outcome=0.5,
                weight=0.7,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[InterventionAdapter] 处理提交事件异常: {e}")

    def _on_applied(self, event: Event):
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            preserved = event_data.get("preserved", 0)
            discarded = event_data.get("discarded", 0)
            outcome = 0.7 if preserved > discarded else 0.4 if discarded > preserved else 0.5
            safe_create_task(self._publish(ExperienceEvent(
                source="intervention",
                event_type="applied",
                timestamp=event_data.get("timestamp", time.time()),
                context={"task_id": event_data.get("task_id", ""), "adaptation": event_data.get("adaptation", "")},
                action="adaptation_applied",
                outcome=outcome,
                weight=0.8,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[InterventionAdapter] 处理应用事件异常: {e}")

    async def _collect(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
# 适配器14：子代理系统（事件驱动）
# ═══════════════════════════════════════════════════════════════════════
class SubAgentExperienceAdapter(BaseExperienceAdapter):
    """订阅 subagent:delegated"""
    INTERVAL = 999999

    def __init__(self, bus: ExperienceBus):
        super().__init__(bus)
        self._handler_registered = False

    async def start(self):
        self._running = True
        try:
            from core.sync.event_bus import event_bus
            event_bus.subscribe("subagent:delegated", self._on_delegated)
            event_bus.subscribe("subagent:pipeline_completed", self._on_pipeline_completed)
            logger.info("[ExperienceAdapter] SubAgentExperienceAdapter 已订阅")
            self._handler_registered = True
        except Exception as e:
            logger.warning(f"[ExperienceAdapter] SubAgentAdapter 订阅失败: {e}")

    def _on_delegated(self, event: Event):
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            status = event_data.get("status", "unknown")
            outcome = 0.8 if status == "SUCCESS" else 0.3 if status == "FAILED" else 0.5
            safe_create_task(self._publish(ExperienceEvent(
                source="subagent",
                event_type="delegated",
                timestamp=event_data.get("timestamp", time.time()),
                context={"agent_name": event_data.get("agent_name", "")},
                action=f"delegate_{status}",
                outcome=outcome,
                weight=0.7,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[SubAgentAdapter] 处理事件异常: {e}")

    def _on_pipeline_completed(self, event: Event):
        event_data = event.data
        try:
            total = event_data.get("total_tasks", 0)
            success = event_data.get("success_count", 0)
            outcome = success / total if total > 0 else 0.5
            safe_create_task(self._publish(ExperienceEvent(
                source="subagent",
                event_type="pipeline_completed",
                timestamp=event_data.get("timestamp", time.time()),
                context={"total_tasks": total, "success_count": success},
                action="pipeline_complete",
                outcome=outcome,
                weight=0.8,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[SubAgentAdapter] 处理流水线事件异常: {e}")

    async def _collect(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
# 适配器15：世界模型系统（事件驱动）
# ═══════════════════════════════════════════════════════════════════════
class WorldModelExperienceAdapter(BaseExperienceAdapter):
    """订阅 world_model:predicted"""
    INTERVAL = 999999

    def __init__(self, bus: ExperienceBus):
        super().__init__(bus)
        self._handler_registered = False

    async def start(self):
        self._running = True
        try:
            from core.sync.event_bus import event_bus
            event_bus.subscribe("world_model:predicted", self._on_predicted)
            event_bus.subscribe("world_model:mcts_planned", self._on_mcts_planned)
            logger.info("[ExperienceAdapter] WorldModelExperienceAdapter 已订阅")
            self._handler_registered = True
        except Exception as e:
            logger.warning(f"[ExperienceAdapter] WorldModelAdapter 订阅失败: {e}")

    def _on_predicted(self, event: Event):
        # 兼容 Event 对象和 dict
        event_data = event.data
        try:
            overall_risk = event_data.get("overall_risk", 0.5)
            outcome = max(0.0, min(1.0, 1.0 - overall_risk))  # 风险越低越好
            safe_create_task(self._publish(ExperienceEvent(
                source="world_model",
                event_type="predicted",
                timestamp=event_data.get("timestamp", time.time()),
                context={"num_actions": event_data.get("num_actions", 0), "best_index": event_data.get("best_index", -1)},
                action="predict_outcomes",
                outcome=outcome,
                weight=0.6,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[WorldModelAdapter] 处理事件异常: {e}")

    def _on_mcts_planned(self, event: Event):
        event_data = event.data
        try:
            expected_success = event_data.get("expected_success", 0.5)
            path_length = event_data.get("path_length", 0)
            outcome = max(0.0, min(1.0, expected_success))  # MCTS预期成功率直接作为outcome
            safe_create_task(self._publish(ExperienceEvent(
                source="world_model",
                event_type="mcts_planned",
                timestamp=event_data.get("timestamp", time.time()),
                context={"path_length": path_length, "iterations": event_data.get("iterations", 0)},
                action="mcts_plan",
                outcome=outcome,
                weight=0.7,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[WorldModelAdapter] 处理MCTS事件异常: {e}")

    async def _collect(self):
        pass


# ═══════════════════════════════════════════════════════════════════════
# 适配器19：语音系统（事件驱动）
# ═══════════════════════════════════════════════════════════════════════
class VoiceExperienceAdapter(BaseExperienceAdapter):
    """订阅 voice:wake_word_detected / voice:tts_failed"""
    INTERVAL = 999999

    def __init__(self, bus: ExperienceBus):
        super().__init__(bus)
        self._handler_registered = False

    async def start(self):
        self._running = True
        try:
            from core.sync.event_bus import event_bus
            event_bus.subscribe("voice:wake_word_detected", self._on_wake_word)
            event_bus.subscribe("voice:tts_failed", self._on_tts_failed)
            logger.info("[ExperienceAdapter] VoiceExperienceAdapter 已订阅")
            self._handler_registered = True
        except Exception as e:
            logger.warning(f"[ExperienceAdapter] VoiceAdapter 订阅失败: {e}")

    def _on_wake_word(self, event: Event):
        event_data = event.data
        try:
            safe_create_task(self._publish(ExperienceEvent(
                source="voice",
                event_type="wake_word_detected",
                timestamp=event_data.get("timestamp", time.time()),
                context={"wake_words": event_data.get("wake_words", []), "detected_text": event_data.get("detected_text", "")},
                action="wake_word",
                outcome=0.8,
                weight=0.6,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[VoiceAdapter] 处理唤醒事件异常: {e}")

    def _on_tts_failed(self, event: Event):
        event_data = event.data
        try:
            safe_create_task(self._publish(ExperienceEvent(
                source="voice",
                event_type="tts_failed",
                timestamp=event_data.get("timestamp", time.time()),
                context={"engine": event_data.get("engine", ""), "error": event_data.get("error", "")},
                action="tts_failure",
                outcome=0.1,
                weight=0.9,
                raw_data=event_data
            )))
        except Exception as e:
            logger.debug(f"[VoiceAdapter] 处理TTS失败事件异常: {e}")

    async def _collect(self):
        pass

# ═══════════════════════════════════════════════════════════════════════
# 适配器16：成本管理（轮询）
# ═══════════════════════════════════════════════════════════════════════
class CostExperienceAdapter(BaseExperienceAdapter):
    """
    定期轮询 CostManager，获取 API 调用成本和预算状态。
    """
    INTERVAL = 60  # 每60秒轮询一次

    async def _collect(self):
        try:
            from core.cost.cost_manager import cost_manager
            stats = cost_manager.get_usage_stats(user_id="default", start_date=None, end_date=None)

            if "error" in stats:
                return

            total_cost = stats.get("overall", {}).get("total_cost", 0)
            total_requests = stats.get("overall", {}).get("total_requests", 0)

            # 成本归一化：假设 $5/天为正常上限，超过则负面
            outcome = max(0.0, min(1.0, 1.0 - total_cost / 5.0))

            await self._publish(ExperienceEvent(
                source="cost",
                event_type="usage_stats",
                timestamp=time.time(),
                context={"total_cost": total_cost, "total_requests": total_requests},
                action=f"cost_{total_cost:.2f}",
                outcome=outcome,
                weight=0.5,
                raw_data=stats
            ))
        except Exception as e:
            logger.debug(f"[CostAdapter] 采集异常: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 适配器17：行为识别（轮询）
# ═══════════════════════════════════════════════════════════════════════
class BehaviorExperienceAdapter(BaseExperienceAdapter):
    """
    定期轮询 BehaviorRecognizer，获取行为类型分布。
    """
    INTERVAL = 120  # 每120秒轮询一次

    async def _collect(self):
        try:
            from core.monitoring.behavior_recognizer import get_behavior_recognizer
            recognizer = get_behavior_recognizer()

            if not recognizer:
                return

            history = getattr(recognizer, "_behavior_history", [])
            if not history:
                return

            recent = list(history)[-10:]
            risk_scores = []
            for bh in recent:
                risk = getattr(bh, "risk_level", "low")
                score = {"low": 0.8, "medium": 0.5, "high": 0.2}.get(risk, 0.5)
                risk_scores.append(score)

            avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 0.5

            await self._publish(ExperienceEvent(
                source="behavior",
                event_type="behavior_analysis",
                timestamp=time.time(),
                context={"recent_count": len(recent), "avg_risk": avg_risk},
                action=f"behavior_{len(recent)}_samples",
                outcome=avg_risk,
                weight=0.6,
                raw_data={"risk_scores": risk_scores}
            ))
        except Exception as e:
            logger.debug(f"[BehaviorAdapter] 采集异常: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 适配器18：经验注入器（轮询）
# ═══════════════════════════════════════════════════════════════════════
class InjectorExperienceAdapter(BaseExperienceAdapter):
    """
    定期轮询 ExperienceInjector，获取成功/失败经验比例。
    """
    INTERVAL = 120  # 每120秒轮询一次

    async def _collect(self):
        try:
            from core.evolution.experience_injector import get_experience_injector
            injector = get_experience_injector()

            if not injector:
                return

            # 尝试读取注入器的信念引擎状态
            reflector = getattr(injector, "reflector", None)
            if not reflector:
                return

            beliefs = getattr(reflector, "beliefs", [])
            if not beliefs:
                return

            success_count = sum(1 for b in beliefs if getattr(b, "confidence", 0.5) > 0.6)
            total = len(beliefs)
            outcome = success_count / total if total > 0 else 0.5

            await self._publish(ExperienceEvent(
                source="injector",
                event_type="experience_ratio",
                timestamp=time.time(),
                context={"success_count": success_count, "total": total},
                action=f"injector_{success_count}/{total}",
                outcome=outcome,
                weight=0.5,
                raw_data={"beliefs_count": total}
            ))
        except Exception as e:
            logger.debug(f"[InjectorAdapter] 采集异常: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 适配器19：会话管理（轮询）
# ═══════════════════════════════════════════════════════════════════════
class SessionExperienceAdapter(BaseExperienceAdapter):
    """
    定期轮询 SessionManager，获取会话活跃度和生命周期统计。
    """
    INTERVAL = 120  # 每120秒轮询一次

    async def _collect(self):
        try:
            from core.session.session_manager import get_session_manager
            sm = get_session_manager()
            if not sm:
                return

            # 获取活跃会话统计
            total_active, sessions = await sm.list_sessions(
                user_id="default", limit=100, status="active"
            )

            message_count = sum(s.message_count for s in sessions)
            avg_messages = message_count / len(sessions) if sessions else 0

            # outcome: 活跃会话数和消息密度反映用户参与度
            session_score = min(1.0, total_active / 5.0)
            density_score = min(1.0, avg_messages / 10.0)
            outcome = 0.5 * session_score + 0.5 * density_score

            await self._publish(ExperienceEvent(
                source="session",
                event_type="session_stats",
                timestamp=time.time(),
                context={
                    "active_sessions": total_active,
                    "total_messages": message_count,
                    "avg_messages_per_session": avg_messages
                },
                action=f"session_{total_active}_active",
                outcome=outcome,
                weight=0.4,
                raw_data={"sessions": total_active, "messages": message_count}
            ))
        except Exception as e:
            logger.debug(f"[SessionAdapter] 采集异常: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 适配器20：世界模型统计（轮询）
# ═══════════════════════════════════════════════════════════════════════
class WorldModelStatsExperienceAdapter(BaseExperienceAdapter):
    """
    定期轮询 WorldModel，获取预测统计和训练状态。
    """
    INTERVAL = 120  # 每120秒轮询一次

    async def _collect(self):
        try:
            from core.world_model.world_model import get_world_model
            wm = get_world_model()
            if not wm:
                return

            stats = getattr(wm, "stats", {})
            training = getattr(wm, "training_stats", {})

            total_exp = stats.get("total_experiences", 0)
            success = stats.get("successful_predictions", 0)
            failed = stats.get("failed_predictions", 0)
            avg_loss = stats.get("average_loss", 0.0)
            avg_error = training.get("avg_error", 0.0)

            # outcome: 预测准确率越高越好，平均误差越低越好
            total_pred = success + failed
            accuracy = success / total_pred if total_pred > 0 else 0.5
            loss_score = max(0.0, min(1.0, 1.0 - avg_loss / 2.0))
            outcome = 0.6 * accuracy + 0.4 * loss_score

            await self._publish(ExperienceEvent(
                source="world_model",
                event_type="stats",
                timestamp=time.time(),
                context={
                    "total_experiences": total_exp,
                    "accuracy": accuracy,
                    "avg_loss": avg_loss,
                    "avg_error": avg_error
                },
                action=f"wm_stats_{total_exp}",
                outcome=outcome,
                weight=0.5,
                raw_data={"stats": stats, "training": training}
            ))
        except Exception as e:
            logger.debug(f"[WorldModelStatsAdapter] 采集异常: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 适配器管理器：一键启动/停止所有适配器（更新版）
# ═══════════════════════════════════════════════════════════════════════
class ExperienceAdapterManager:
    """管理所有适配器的启动和停止"""

    def __init__(self, bus: ExperienceBus):
        self.bus = bus
        self.adapters = [
            ToolExperienceAdapter(bus),
            RLHFExperienceAdapter(bus),
            SensorExperienceAdapter(bus),
            MemoryExperienceAdapter(bus),
            EvolutionExperienceAdapter(bus),
            ReflectExperienceAdapter(bus),
            TradeExperienceAdapter(bus),
            AgentLoopExperienceAdapter(bus),
            DialogueExperienceAdapter(bus),
            SafetyExperienceAdapter(bus),
            IntentExperienceAdapter(bus),
            WorkflowExperienceAdapter(bus),
            InterventionExperienceAdapter(bus),
            SubAgentExperienceAdapter(bus),
            WorldModelExperienceAdapter(bus),
            VoiceExperienceAdapter(bus),
            CostExperienceAdapter(bus),
            BehaviorExperienceAdapter(bus),
            InjectorExperienceAdapter(bus),
            SessionExperienceAdapter(bus),
            WorldModelStatsExperienceAdapter(bus),
        ]

    async def start_all(self):
        """启动所有适配器"""
        for adapter in self.adapters:
            try:
                await adapter.start()
            except Exception as e:
                logger.warning(f"[AdapterManager] 启动 {adapter.__class__.__name__} 失败: {e}")
        logger.info(f"[AdapterManager] 已启动 {len(self.adapters)} 个适配器")

    async def stop_all(self):
        """停止所有适配器"""
        for adapter in self.adapters:
            with contextlib.suppress(Exception):
                await adapter.stop()
        logger.info("[AdapterManager] 所有适配器已停止")

    def get_stats(self) -> dict[str, Any]:
        """返回各适配器的统计信息"""
        return {
            "total_adapters": len(self.adapters),
            "adapter_stats": [
                {
                    "name": a.__class__.__name__,
                    "event_count": a._event_count,
                    "running": a._running,
                }
                for a in self.adapters
            ],
        }
