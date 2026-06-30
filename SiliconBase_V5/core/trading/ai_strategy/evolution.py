#!/usr/bin/env python3
"""
AI 策略进化器

核心功能：
- 回测结果 → AI 分析 → 策略改进 → 再回测
- 支持多轮迭代优化
- 自动保存进化历史
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.ai.ai_client import AIClient
from core.logger import logger

from ..backtest.ai_enhanced import AIEnhancedBacktester


@dataclass
class EvolutionRound:
    """一轮进化记录"""
    round_number: int
    strategy_params: dict[str, Any]
    backtest_result: dict[str, Any]
    ai_analysis: str
    ai_suggestions: dict[str, Any]
    fitness: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class AIStrategyEvolver:
    """
    AI 策略进化器

    自动化流程：
    1. 回测当前策略
    2. AI 分析结果
    3. AI 生成改进建议
    4. 应用建议生成新策略
    5. 重复直到满足停止条件
    """

    def __init__(self,
                 strategy_class,
                 data: pd.DataFrame,
                 max_rounds: int = 10,
                 fitness_threshold: float = 0.7):
        self.strategy_class = strategy_class
        self.data = data
        self.max_rounds = max_rounds
        self.fitness_threshold = fitness_threshold

        self.ai_client = AIClient()
        self.backtester = AIEnhancedBacktester()
        self.history: list[EvolutionRound] = []

        self.save_dir = Path("data/strategy_evolution")
        self.save_dir.mkdir(parents=True, exist_ok=True)

    async def evolve(self,
                    initial_params: dict[str, Any],
                    progress_callback: Callable[[dict], None] = None) -> dict[str, Any]:
        """
        执行策略进化

        全自动流程：回测 → AI分析 → 改进 → 循环
        """
        current_params = initial_params.copy()
        best_result = None
        best_fitness = 0.0

        logger.info(f"[StrategyEvolver] 开始进化，初始参数: {current_params}")

        for round_num in range(1, self.max_rounds + 1):
            logger.info(f"[StrategyEvolver] 第 {round_num}/{self.max_rounds} 轮")

            # 1. 回测
            strategy = self.strategy_class(current_params)
            backtest_result = self.backtester.run(self.data, strategy)
            fitness = self.backtester._calculate_fitness(backtest_result)

            # 记录最佳
            if fitness > best_fitness:
                best_fitness = fitness
                best_result = {
                    'round': round_num,
                    'params': current_params.copy(),
                    'fitness': fitness,
                    'pf': backtest_result.profit_factor,
                    'sharpe': backtest_result.sharpe_ratio
                }

            # 回调进度
            if progress_callback:
                progress_callback({
                    'round': round_num,
                    'fitness': fitness,
                    'best_fitness': best_fitness,
                    'params': current_params
                })

            # 2. 检查停止条件
            if fitness >= self.fitness_threshold:
                logger.info(f"[StrategyEvolver] 达到目标 fitness={fitness:.3f}")
                break

            if round_num == self.max_rounds:
                break

            # 3. AI 分析并生成改进
            ai_report = self.backtester.generate_ai_report(
                backtest_result,
                strategy_name=self.strategy_class.name
            )

            suggestions = await self._ask_ai_for_improvements(
                ai_report,
                current_params
            )

            # 记录本轮
            self.history.append(EvolutionRound(
                round_number=round_num,
                strategy_params=current_params.copy(),
                backtest_result={
                    'fitness': fitness,
                    'pf': backtest_result.profit_factor,
                    'sharpe': backtest_result.sharpe_ratio
                },
                ai_analysis=ai_report,
                ai_suggestions=suggestions,
                fitness=fitness
            ))

            # 4. 应用改进
            current_params = self._apply_suggestions(current_params, suggestions)

        self._save_history()

        return {
            'best_params': best_result['params'] if best_result else initial_params,
            'best_fitness': best_fitness,
            'total_rounds': len(self.history),
            'history': self.history
        }

    async def _ask_ai_for_improvements(self,
                                      ai_report: str,
                                      current_params: dict) -> dict[str, Any]:
        """询问 AI 如何改进策略"""
        prompt = f"""你是一个专业的量化交易策略优化专家。

## 当前回测结果分析
{ai_report}

## 当前策略参数
```json
{json.dumps(current_params, indent=2)}
```

## 任务
基于以上回测结果，给出具体的参数调整建议。

只返回 JSON 格式：
```json
{{
    "parameter_changes": {{
        "参数名1": 新值,
        "参数名2": 新值
    }},
    "reasoning": "为什么这样调整",
    "confidence": 0.8
}}
```"""

        try:
            response = await self.ai_client.chat(prompt)
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            else:
                return json.loads(response)
        except Exception as e:
            logger.error(f"[StrategyEvolver] AI 解析失败: {e}")
            return {'parameter_changes': {}, 'reasoning': '解析失败', 'confidence': 0.0}

    def _apply_suggestions(self,
                          current_params: dict,
                          suggestions: dict) -> dict:
        """应用 AI 建议到参数"""
        new_params = current_params.copy()
        changes = suggestions.get('parameter_changes', {})

        for param, new_value in changes.items():
            if param in new_params and self._is_valid_param_value(param, new_value):
                new_params[param] = new_value
                logger.info(f"[StrategyEvolver] 调整 {param}: {current_params[param]} -> {new_value}")

        return new_params

    def _is_valid_param_value(self, param: str, value) -> bool:
        """验证参数值是否有效"""
        if 'period' in param.lower() and isinstance(value, (int, float)):
            return 1 <= value <= 100
        if 'threshold' in param.lower() and isinstance(value, (int, float)):
            return 0 <= value <= 100
        return True

    def _save_history(self):
        """保存进化历史"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{self.strategy_class.name}_{timestamp}.json"
        filepath = self.save_dir / filename

        data = {
            'strategy': self.strategy_class.name,
            'rounds': [self._round_to_dict(r) for r in self.history]
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _round_to_dict(self, round_record: EvolutionRound) -> dict:
        return {
            'round_number': round_record.round_number,
            'strategy_params': round_record.strategy_params,
            'backtest_result': round_record.backtest_result,
            'ai_suggestions': round_record.ai_suggestions,
            'fitness': round_record.fitness
        }


# 便捷使用函数
async def evolve_strategy(strategy_class,
                         data: pd.DataFrame,
                         initial_params: dict,
                         max_rounds: int = 5) -> dict[str, Any]:
    """一键进化策略"""
    evolver = AIStrategyEvolver(strategy_class, data, max_rounds=max_rounds)
    return await evolver.evolve(initial_params)
