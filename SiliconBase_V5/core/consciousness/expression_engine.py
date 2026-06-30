#!/usr/bin/env python3
"""
表达引擎（ExpressionEngine）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
将内心独白转化为弱连接气泡提案。
基于情绪、驱动力、上下文，决定是否"说话"。

核心闭环：
    独白生成 → 表达评估 → 弱连接提案 → 前端气泡 → 用户点击/忽略/超时
              → 反馈调整驱动力
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class ExpressionEngine:
    """
    表达引擎：将内心独白转化为弱连接气泡提案。
    基于情绪、驱动力、上下文，决定是否"说话"。

    【P2-改造】接入 ActionPreferencePredictor，让表达决策能随反馈在线学习。
    """

    # 情绪 → 表达权重映射
    MOOD_WEIGHTS = {
        'anxious': 0.85,    # 焦虑时强烈想求助
        'frustrated': 0.80, # 沮丧时想求助
        'curious': 0.75,    # 好奇时想分享
        'bored': 0.65,      # 无聊时想找人
        'excited': 0.60,    # 兴奋时想分享
        'confused': 0.55,   # 困惑时想询问
        'neutral': 0.30,    # 平静时懒得说话
        'focused': 0.15,    # 专注时不想被打扰
        'calm': 0.20,       # 平静时不想说话
    }

    def __init__(self, cooldown_seconds: float = 60.0):
        self.cooldown_seconds = cooldown_seconds
        self.last_express_time = 0.0
        self.last_proposal_id: str | None = None
        self._last_input_vector: Any | None = None
        # 【P2】思维层学习模型（由 Consciousness 注入）
        self._action_model: Any | None = None
        self._online_learner: Any | None = None

    def set_action_model(self, model: Any | None, learner: Any | None):
        """
        注入动作偏好预测模型和在线学习器。

        由 Consciousness 在初始化后调用，共享同一个模型实例，避免重复加载。
        """
        self._action_model = model
        self._online_learner = learner
        if model is not None:
            logger.info("[ExpressionEngine] 已接入 ActionPreferencePredictor")
        else:
            logger.debug("[ExpressionEngine] 未接入 ActionPreferencePredictor，使用纯规则")

    def calculate_urge(
        self,
        mood: str,
        monologue: str,
        curiosity: float,
        mastery: float,
        autonomy: float,
        energy: float,
    ) -> float:
        """
        计算表达欲望值（0.0 ~ 1.0）。
        """
        # 1. 情绪基础权重
        mood_weight = self.MOOD_WEIGHTS.get(mood, 0.3)

        # 2. 独白内容加成（如果独白里有"想"、"建议"、"试试"等词，表达欲更强）
        content_boost = 0.0
        express_keywords = ['想', '建议', '试试', '换个', '能不能', '是不是', '为什么']
        for kw in express_keywords:
            if kw in monologue:
                content_boost += 0.08

        # 2b. 明确意图词额外加成（"我想……"等直接表达意愿）
        intent_phrases = ['我想', '我觉得应该', '我建议', '我想试试', '我想换个']
        for phrase in intent_phrases:
            if phrase in monologue:
                content_boost += 0.20
                break  # 只加一次

        content_boost = min(content_boost, 0.6)  # 封顶

        # 3. 驱动力加成（好奇心和胜任感驱动表达）
        drive_factor = curiosity * 0.5 + mastery * 0.3 + autonomy * 0.2

        # 4. 能量衰减（累了不想说话）
        energy_penalty = 0.0 if energy > 0.5 else (0.5 - energy) * 0.4

        # 5. 冷却衰减（刚说过话，暂时不想说）
        time_since_last = time.time() - self.last_express_time
        cooldown_penalty = 0.0
        if time_since_last < self.cooldown_seconds:
            cooldown_penalty = 0.5 * (1 - time_since_last / self.cooldown_seconds)

        # 规则引擎计算的表达欲望
        rule_urge = (
            mood_weight * 0.4
            + content_boost
            + drive_factor * 0.3
            - energy_penalty
            - cooldown_penalty
        )
        rule_urge = max(0.0, min(1.0, rule_urge))

        # 【P2-改造】如果学习模型可用，用模型预测当前状态下主动表达的预期收益
        model_urge = self._predict_model_urge(
            monologue, mood, curiosity, mastery, autonomy, energy
        )

        if model_urge is None:
            return rule_urge

        # 冷启动保护：数据不足时模型权重低，数据充足后逐步提高
        model_weight = 0.3
        if self._online_learner:
            model_weight = self._online_learner.get_model_weight()

        final_urge = model_urge * model_weight + rule_urge * (1 - model_weight)
        return max(0.0, min(1.0, final_urge))

    def _predict_model_urge(
        self,
        monologue: str,
        mood: str,
        curiosity: float,
        mastery: float,
        autonomy: float,
        energy: float,
    ) -> float | None:
        """
        用 ActionPreferencePredictor 预测当前状态下主动表达的预期收益。

        输入向量与 Consciousness 训练时保持一致：
        motivation(4) + vision_state(8) + action_features(8) + history(4) = 24
        """
        if self._action_model is None:
            return None

        try:
            import torch

            from core.runtime import system_state

            # motivation: 4维 [curiosity, mastery, autonomy, purpose]
            motivation = torch.tensor(
                [curiosity, mastery, autonomy, 0.5], dtype=torch.float32
            )

            # vision_state: 8维，从 SystemState 读取最近视觉标签
            vision_state = torch.zeros(8, dtype=torch.float32)
            try:
                tags = system_state.get_sync("consciousness.vision_tags", [])
                if tags:
                    total = max(len(tags), 1)
                    uia_ratio = sum(1 for t in tags if t.get("source") == "uia") / total
                    ocr_ratio = sum(1 for t in tags if t.get("source") == "ocr") / total
                    onnx_ratio = sum(1 for t in tags if t.get("source") == "onnx") / total
                    contour_ratio = sum(1 for t in tags if t.get("source") == "contour") / total
                    vision_state = torch.tensor([
                        min(total / 50.0, 1.0),
                        uia_ratio,
                        ocr_ratio,
                        onnx_ratio,
                        contour_ratio,
                        1.0 if any(t.get("alert") for t in tags) else 0.0,
                        0.5,
                        0.5,
                    ], dtype=torch.float32)
            except Exception as e:
                logger.debug(f"[ExpressionEngine] 读取视觉状态失败: {e}")

            # action_features: 8维，从独白内容提取
            mono_lower = (monologue or "").lower()
            action_features = torch.tensor([
                min(len(monologue or "") / 200.0, 1.0),
                1.0 if any(kw in mono_lower for kw in ["想", "建议", "试试"]) else 0.0,
                1.0 if any(kw in mono_lower for kw in ["焦虑", "担心", "失败"]) else 0.0,
                1.0 if any(kw in mono_lower for kw in ["好奇", "发现", "新"]) else 0.0,
                1.0 if any(kw in mono_lower for kw in ["用户", "你", "聊天"]) else 0.0,
                self.MOOD_WEIGHTS.get(mood, 0.3),
                0.5,
                0.5,
            ], dtype=torch.float32)

            # history: 4维，简化为默认分布
            history = torch.tensor([0.25, 0.25, 0.25, 0.25], dtype=torch.float32)

            # 记录输入向量，用于后续训练
            self._last_input_vector = torch.cat([
                motivation, vision_state, action_features, history
            ])

            with torch.no_grad():
                score = self._action_model.forward(
                    motivation.unsqueeze(0),
                    vision_state.unsqueeze(0),
                    action_features.unsqueeze(0),
                    history.unsqueeze(0),
                )
            return float(score.item())
        except Exception as e:
            logger.debug(f"[ExpressionEngine] 模型预测表达欲望失败: {e}")
            return None

    def should_express(self, urge: float, threshold: float = 0.45) -> bool:
        """
        是否达到表达阈值。
        """
        return urge > threshold

    async def express(
        self,
        monologue: str,
        mood: str,
        state_summary: dict[str, Any],
    ) -> str | None:
        """
        执行表达：提交弱连接气泡。
        返回 proposal_id 或 None。
        """
        try:
            # 功能开关
            try:
                from core.config import config
                if not config.get("features.weak_connection_expression.enabled", True):
                    return None
                threshold = config.get(
                    "features.weak_connection_expression.threshold", 0.45
                )
            except Exception:
                threshold = 0.45

            # 获取驱动力
            try:
                from core.strategy.intrinsic_motivation import get_intrinsic_motivation
                motivation = get_intrinsic_motivation()
                drive = motivation.evaluate_drive() if motivation else None
            except Exception as e:
                logger.debug(f"[表达] 获取驱动力失败: {e}")
                drive = None

            curiosity = getattr(drive, 'curiosity_level', 0.5) if drive else 0.5
            mastery = getattr(drive, 'mastery_level', 0.5) if drive else 0.5
            autonomy = getattr(drive, 'autonomy_level', 0.5) if drive else 0.5
            energy = getattr(drive, 'energy_level', 0.8) if drive else 0.8

            urge = self.calculate_urge(
                mood, monologue, curiosity, mastery, autonomy, energy
            )

            if not self.should_express(urge, threshold):
                logger.info(
                    f"[表达] 表达欲望 {urge:.2f} 未达阈值 {threshold}，保持沉默"
                )
                return None

            # 构建提案内容
            proposal_content = self._extract_proposal_content(monologue)

            # 提交弱连接
            proposal_id = await self._submit_to_weak_connection(
                proposal_content, mood, state_summary, urge
            )

            if proposal_id:
                self.last_express_time = time.time()
                self.last_proposal_id = proposal_id
                logger.info(
                    f"[表达] 已提交提案(id={proposal_id}), 欲望={urge:.2f}, "
                    f"内容={proposal_content[:40]}..."
                )

                # 可选：高表达欲时同时触发语音播报
                try:
                    from core.config import config
                    voice_enabled = config.get("features.weak_connection_expression.voice_announce", False)
                except Exception:
                    voice_enabled = False

                if voice_enabled and urge > 0.7:
                    try:
                        from core.sync.event_bus import event_bus
                        event_bus.emit("voice:announce", {
                            "text": proposal_content,
                            "source": "consciousness_expression",
                            "urgency": int(urge * 100),
                            "timestamp": time.time(),
                        })
                        logger.info(f"[表达] 已触发语音播报: {proposal_content[:40]}...")
                    except Exception as e:
                        logger.debug(f"[表达] 语音播报触发失败: {e}")

            return proposal_id

        except Exception as e:
            logger.error(f"[表达] 表达失败: {e}")
            return None

    def _extract_proposal_content(self, monologue: str) -> str:
        """
        从独白中提取"想做什么"作为提案内容。
        """
        # 如果独白里有"想"字，提取后面的内容
        if '想' in monologue:
            idx = monologue.index('想')
            return monologue[idx:].strip('，。 ')
        # 如果独白里有"建议"
        if '建议' in monologue:
            idx = monologue.index('建议')
            return monologue[idx:].strip('，。 ')
        # 否则用整句独白，但截短
        return monologue.strip('，。 ')[:60]

    async def _submit_to_weak_connection(
        self,
        content: str,
        mood: str,
        state_summary: dict,
        urge: float,
    ) -> str | None:
        """
        调用弱连接引擎提交提案。
        """
        try:
            from core.weak_connection.weak_connection import get_weak_connection_engine
            weak_engine = get_weak_connection_engine()

            if not weak_engine:
                logger.warning("[表达] 弱连接引擎未初始化")
                return None

            # 构建提案
            proposal_id = f"expr_{int(time.time())}_{hash(content) % 10000}"

            # 如果弱连接引擎有 submit_proposal 方法，直接调用
            if hasattr(weak_engine, 'submit_proposal'):
                await weak_engine.submit_proposal(
                    message=content,
                    context_summary=(
                        f"情绪:{mood}, "
                        f"工具失败率:{state_summary.get('tool_fail_rate', 0):.0%}, "
                        f"表达欲:{urge:.2f}"
                    ),
                    confidence=int(urge * 100),
                    proposal_id=proposal_id,
                )
                return proposal_id

            # 回退：直接 emit WebSocket 事件
            from core.sync.event_bus import event_bus
            event_bus.emit("ui:show_proposal", {
                "anchor_id": proposal_id,
                "message": content,
                "action_text": "帮我处理",
                "auto_hide": 60,
                "context_summary": f"情绪:{mood}",
                "timestamp": time.time(),
            })
            return proposal_id

        except Exception as e:
            logger.error(f"[表达] 提交弱连接失败: {e}")
            return None

    async def on_feedback(self, proposal_id: str, action: str):
        """
        接收用户反馈，调整驱动力，并训练表达偏好模型。
        action: 'clicked' | 'ignored' | 'timeout'
        """
        self._apply_feedback(proposal_id, action)

    def on_feedback_sync(self, proposal_id: str, action: str):
        """
        同步版本反馈处理，供非 async 上下文调用。
        """
        self._apply_feedback(proposal_id, action)

    def _apply_feedback(self, proposal_id: str, action: str):
        """实际反馈处理逻辑（同步，线程安全）"""
        try:
            from core.strategy.intrinsic_motivation import get_intrinsic_motivation
            motivation = get_intrinsic_motivation()
            if not motivation:
                return

            # 标签：用户点击=1.0（表达成功），忽略/超时=0.0（表达失败）
            label = 1.0 if action == 'clicked' else 0.0

            # 【P2-改造】把反馈加入动作偏好模型训练
            if (
                self._online_learner is not None
                and self._last_input_vector is not None
            ):
                try:
                    self._online_learner.add_sample(
                        self._last_input_vector, label, source=f"expression_{action}"
                    )
                    if self._online_learner.should_train():
                        loss = self._online_learner.train_step()
                        logger.info(
                            f"[ExpressionEngine] 表达偏好模型训练完成, "
                            f"loss={loss:.4f}, 样本数={self._online_learner.sample_count}"
                        )
                except Exception as e:
                    logger.debug(f"[ExpressionEngine] 模型训练失败: {e}")

            if action == 'clicked':
                # 用户认可：胜任感大幅提升，表达欲提升
                motivation.update_drive('mastery', 0.15)
                motivation.update_drive('curiosity', 0.05)
                logger.info(
                    f"[表达反馈] 用户点击提案 {proposal_id}，胜任感+0.15"
                )

            elif action == 'ignored':
                # 用户忽略：表达欲受挫，好奇心略降
                motivation.update_drive('curiosity', -0.05)
                logger.info(
                    f"[表达反馈] 用户忽略提案 {proposal_id}，好奇心-0.05"
                )

            elif action == 'timeout':
                # 超时：表达欲受挫
                motivation.update_drive('curiosity', -0.08)
                logger.info(
                    f"[表达反馈] 提案 {proposal_id} 超时，好奇心-0.08"
                )

        except Exception as e:
            logger.error(f"[表达反馈] 处理反馈失败: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# 模块级单例
# ═══════════════════════════════════════════════════════════════════════════════
_expression_engine_instance: ExpressionEngine | None = None


def get_expression_engine() -> ExpressionEngine:
    """获取 ExpressionEngine 单例实例"""
    global _expression_engine_instance
    if _expression_engine_instance is None:
        cooldown = 60.0
        try:
            from core.config import config
            cooldown = config.get(
                "features.weak_connection_expression.cooldown_seconds", 60.0
            )
        except Exception:
            pass
        _expression_engine_instance = ExpressionEngine(cooldown_seconds=cooldown)
    return _expression_engine_instance
