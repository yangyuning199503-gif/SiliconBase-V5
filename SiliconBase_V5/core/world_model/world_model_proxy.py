#!/usr/bin/env python3  # 指定Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文字符
"""  # 多行文档字符串开始
WorldModel代理模块 - 实现torch的延迟加载和优雅降级  # 模块名称和核心功能

功能:  # 功能列表标题
1. 自动检测PyTorch可用性  # 功能1：检测PyTorch是否安装
2. 提供降级实现(DummyWorldModel)以支持无torch环境  # 功能2：降级实现
3. 保持与原有API 100%兼容  # 功能3：API兼容性保证
4. 支持配置开关控制  # 功能4：通过配置控制启用/禁用

使用方式:  # 使用示例标题
    from core.world_model.world_model_proxy import get_world_model, WorldModel  # 导入函数和类

    wm = get_world_model()  # 获取世界模型实例（代理）
    result = wm.predict_detailed(perception, tool_id, params)  # 调用预测方法
"""  # 文档字符串结束
import json  # 导入JSON模块，用于数据持久化
import logging  # 导入日志模块，用于记录状态信息
import time  # 导入时间模块，用于时间戳
from pathlib import Path  # 导入Path类，用于路径操作
from typing import Any  # 导入类型提示相关类

logger = logging.getLogger(__name__)  # 获取当前模块的日志记录器实例

# ============ Torch可用性检测 ============
_TORCH_AVAILABLE = None  # 全局变量：缓存PyTorch可用性检测结果，None表示未检测

def is_torch_available() -> bool:
    """检测torch是否可用，使用全局缓存避免重复检测"""
    global _TORCH_AVAILABLE  # 声明使用全局变量
    if _TORCH_AVAILABLE is None:  # 如果尚未检测
        # 首先检查环境变量强制禁用
        import os  # 导入os模块，用于读取环境变量
        if os.environ.get('SILICONBASE_DISABLE_TORCH', '').lower() in ('1', 'true', 'yes'):  # 检查禁用标志
            _TORCH_AVAILABLE = False  # 设置不可用标志
            logger.info("[WorldModel] PyTorch disabled by environment variable")  # 记录日志
            return _TORCH_AVAILABLE  # 返回结果

        import importlib.util
        if importlib.util.find_spec("torch") is not None:
            _TORCH_AVAILABLE = True
            logger.debug("[WorldModel] PyTorch detected")
        else:
            _TORCH_AVAILABLE = False
            logger.info("[WorldModel] PyTorch not available, world model disabled")
    return _TORCH_AVAILABLE  # 返回缓存的检测结果


# ============ 配置检查 ============
def is_world_model_enabled() -> bool:
    """检查配置是否启用世界模型，默认启用"""
    try:  # 异常处理块
        from core.config import config  # 导入配置模块
        return config.is_feature_enabled("world_model")  # 读取 features.world_model.enabled
    except Exception:  # 捕获任何异常（配置模块不存在等）
        return True  # 默认启用


def is_training_enabled() -> bool:
    """检查配置是否启用训练，默认启用"""
    try:  # 异常处理块
        from core.config import config  # 导入配置模块
        return config.is_feature_enabled("world_model")  # 与模型开关保持一致
    except Exception:  # 捕获任何异常
        return True  # 默认启用


# ============ 降级实现 ============
class DummyWorldModel:
    """
    虚拟世界模型 - 当torch不可用时使用
    提供相同的API但返回中性/默认值，确保系统不崩溃

    【增强版降级实现】
    即使没有PyTorch，也能提供基础功能：
    1. 基于启发式的行动建议
    2. 观察数据记录到文件
    3. 统计数据持久化
    4. 简单的工具使用历史跟踪
    """

    def __init__(self, *args, **kwargs):
        """
        构造函数，接受任意参数以兼容真实实现
        Args:
            *args: 位置参数（被忽略）
            **kwargs: 关键字参数（被忽略）
        """
        self.dummy_mode = True  # 标记为降级模式
        self.device = "cpu"  # 默认设备为CPU
        self.stats = {  # 初始化统计字典（中性值）
            'total_experiences': 0,  # 总经验数为0
            'successful_predictions': 0,  # 成功预测数为0
            'failed_predictions': 0,  # 失败预测数为0
            'average_loss': 0.0  # 平均损失为0
        }
        self.training_stats = {  # 初始化训练统计字典
            'episodes': 0,  # episode数为0
            'online_updates': 0,  # 在线更新次数为0
            'last_loss': 0.0,  # 最新损失为0
            'avg_error': 0.0  # 平均误差为0
        }

        # 增强：初始化观察记录存储
        self._observations = []  # 观察记录列表（内存缓存）
        self._tool_history = {}  # 工具使用历史统计 {tool_id: {'success': n, 'failure': n, 'total': n}}
        self._max_observations = 1000  # 最大观察记录数

        # 增强：设置数据目录
        self._data_dir = Path("data/world_model")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._observations_file = self._data_dir / "dummy_observations.json"
        self._stats_file = self._data_dir / "dummy_stats.json"

        # 增强：加载已有数据
        self._load()

        logger.info("[WorldModel] Running in DUMMY mode (torch not available)")  # 记录降级模式启动
        logger.info(f"[WorldModel] Dummy data directory: {self._data_dir}")  # 记录数据目录

    def predict(self, state, action):
        """
        降级预测方法

        Args:
            state: 状态（字典或数组）
            action: 动作

        Returns:
            (next_state, reward, done) - 中性值
        """
        import numpy as np  # 在方法内导入，避免模块级依赖
        if isinstance(state, dict):  # 如果状态是字典
            return None, 0.0, False  # 返回None状态、0奖励、False完成标志
        return np.zeros_like(state), 0.0, False  # 返回零数组、0奖励、False完成标志

    def predict_detailed(self, perception: dict, tool_id: str, params: dict,
                         task_context: dict = None) -> dict[str, Any]:
        """
        降级详细预测方法

        Args:
            perception: 感知数据字典
            tool_id: 工具ID
            params: 工具参数
            task_context: 任务上下文（可选）

        Returns:
            中性预测结果字典，confidence=0表示不可信
        """
        return {  # 返回中性预测结果
            'next_state': None,  # 无下一状态
            'success_prob': 0.5,  # 成功率50%（中性）
            'expected_reward': 0.0,  # 预期奖励0
            'risk': 0.5,  # 风险50%（中性）
            'confidence': 0.0,  # 置信度0（表示不可信）
            'done_prob': 0.5,  # 完成概率50%
            'message': 'World model unavailable (torch not installed)'  # 说明消息
        }

    def suggest_action(self, current_state, available_tools, use_mcts=True, horizon=5):
        """
        增强版降级行动建议方法

        基于工具使用历史统计提供启发式建议
        即使没有PyTorch，也能根据成功率推荐工具

        Args:
            current_state: 当前状态（感知字典或状态向量）
            available_tools: 可用工具列表
            use_mcts: 是否使用MCTS（降级模式下忽略）
            horizon: 规划horizon（降级模式下忽略）

        Returns:
            Dict或None - 包含建议信息的字典，数据不足时返回None
            {
                'type': 'heuristic',
                'best_action': 推荐工具ID,
                'score': 分数(0-1),
                'reason': 建议原因,
                'confidence': 置信度(0-1),
                'alternatives': 备选工具列表
            }
        """
        try:
            # 检查输入
            if not available_tools or not isinstance(available_tools, (list, tuple)):
                logger.debug("[WorldModel] suggest_action: 可用工具列表为空")
                return None

            # 过滤掉无效工具
            valid_tools = [t for t in available_tools if isinstance(t, str) and t]
            if not valid_tools:
                return None

            # 计算每个工具的成功率
            tool_scores = []
            for tool_id in valid_tools:
                history = self._tool_history.get(tool_id, {})
                total = history.get('total', 0)
                success = history.get('success', 0)

                if total > 0:
                    # 有历史记录：计算成功率
                    success_rate = success / total
                    # 考虑样本数量的置信度（样本越多越可信）
                    confidence = min(1.0, total / 10)  # 10次以上达到最大置信度
                    score = success_rate * confidence + 0.5 * (1 - confidence)  # 平滑处理
                else:
                    # 无历史记录：中性分数
                    score = 0.5
                    confidence = 0.0

                tool_scores.append({
                    'tool_id': tool_id,
                    'score': score,
                    'success_rate': success / total if total > 0 else 0.5,
                    'total_uses': total,
                    'confidence': confidence
                })

            # 按分数排序
            tool_scores.sort(key=lambda x: x['score'], reverse=True)

            # 获取最佳工具
            best = tool_scores[0]
            alternatives = [t['tool_id'] for t in tool_scores[1:4]]  # 最多3个备选

            # 生成建议原因
            if best['total_uses'] > 0:
                if best['success_rate'] > 0.8:
                    reason = f"{best['tool_id']} 历史成功率较高 ({best['success_rate']*100:.0f}%)"
                elif best['success_rate'] > 0.5:
                    reason = f"{best['tool_id']} 历史表现尚可 ({best['success_rate']*100:.0f}%)"
                else:
                    reason = f"{best['tool_id']} 历史成功率较低，但暂无更好选择"
            else:
                reason = "基于可用工具列表的默认推荐（无历史数据）"

            result = {
                'type': 'heuristic',
                'best_action': best['tool_id'],
                'score': best['score'],
                'reason': reason,
                'confidence': best['confidence'],
                'alternatives': alternatives,
                'all_scores': {t['tool_id']: round(t['score'], 2) for t in tool_scores}
            }

            logger.debug(f"[WorldModel] suggest_action: 推荐 {best['tool_id']} (score={best['score']:.2f})")
            return result

        except Exception as e:
            logger.warning(f"[WorldModel] suggest_action 异常: {e}")
            return None  # 异常时返回None，不中断主流程

    def get_prediction_for_prompt(self, perception: dict,
                                  proposed_tool: str,
                                  proposed_params: dict,
                                  task_context: dict = None) -> str:
        """
        降级提示词生成方法

        Args:
            perception: 感知数据
            proposed_tool: 提议的工具
            proposed_params: 提议的参数
            task_context: 任务上下文（可选）

        Returns:
            空字符串 - 降级模式下不添加预测到prompt
        """
        return ""  # 返回空字符串

    def get_prediction_dict(self, perception: dict,
                           proposed_tool: str,
                           proposed_params: dict,
                           task_context: dict = None) -> dict:
        """
        降级预测字典方法

        Args:
            perception: 感知数据
            proposed_tool: 提议的工具
            proposed_params: 提议的参数
            task_context: 任务上下文（可选）

        Returns:
            空字典
        """
        return {}  # 返回空字典

    def imagine(self, perception: dict, action_sequence: list[tuple[str, dict]],
                task_context: dict = None) -> list[dict]:
        """
        降级想象方法（反事实推理）

        Args:
            perception: 感知数据
            action_sequence: 动作序列 [(tool_id, params), ...]
            task_context: 任务上下文（可选）

        Returns:
            空列表 - 降级模式下无法想象
        """
        return []  # 返回空列表

    def evaluate_plan(self, perception: dict,
                      plan: list[tuple[str, dict]],
                      task_context: dict = None) -> dict:
        """
        降级计划评估方法

        Args:
            perception: 感知数据
            plan: 行动计划
            task_context: 任务上下文（可选）

        Returns:
            中性评估结果字典
        """
        return {  # 返回中性评估结果
            'total_expected_reward': 0,  # 总预期奖励0
            'success_probability': 0.5,  # 成功概率50%
            'risk_level': 'unknown',  # 风险等级未知
            'recommendation': 'World model unavailable - no evaluation possible',  # 说明
            'step_predictions': []  # 空步骤预测列表
        }

    def observe_tool_execution(self, tool_id: str, params: dict,
                               perception_before: dict,
                               perception_after: dict,
                               result: dict,
                               task_context: dict = None):
        """
        增强版降级观察方法 - 记录工具执行经验

        即使没有PyTorch，也记录观察数据到文件，用于启发式建议

        Args:
            tool_id: 工具ID
            params: 工具参数
            perception_before: 执行前感知
            perception_after: 执行后感知
            result: 执行结果
            task_context: 任务上下文（可选）
        """
        try:
            import time

            # 提取成功/失败信息
            success = result.get('success', False) if isinstance(result, dict) else False
            error = result.get('error') if isinstance(result, dict) else None

            # 创建观察记录
            observation = {
                'tool_id': tool_id,
                'params': self._safe_serialize_params(params),
                'success': success,
                'error': error,
                'timestamp': time.time(),
                'task_id': task_context.get('task_id') if task_context else None,
                'perception_summary': self._summarize_perception(perception_before)
            }

            # 添加到内存缓存
            self._observations.append(observation)

            # 限制缓存大小
            if len(self._observations) > self._max_observations:
                self._observations.pop(0)

            # 更新工具历史统计
            if tool_id not in self._tool_history:
                self._tool_history[tool_id] = {'success': 0, 'failure': 0, 'total': 0}

            self._tool_history[tool_id]['total'] += 1
            if success:
                self._tool_history[tool_id]['success'] += 1
            else:
                self._tool_history[tool_id]['failure'] += 1

            # 更新统计
            self.stats['total_experiences'] += 1
            if success:
                self.stats['successful_predictions'] += 1
            else:
                self.stats['failed_predictions'] += 1

            # 定期保存（每10条记录）
            if len(self._observations) % 10 == 0:
                self._save()

            logger.debug(f"[WorldModel] 记录观察: {tool_id}, 成功={success}, "
                        f"总计={self.stats['total_experiences']}")

        except Exception as e:
            # 降级模式下不应抛出异常，只记录
            logger.debug(f"[WorldModel] observe_tool_execution 记录失败: {e}")

    def _safe_serialize_params(self, params: dict) -> dict:
        """安全序列化参数（处理不可序列化的对象）"""
        if not isinstance(params, dict):
            return {'_type': str(type(params))}

        safe_params = {}
        for key, value in params.items():
            if isinstance(value, (str, int, float, bool, type(None))):
                safe_params[key] = value
            elif isinstance(value, (list, tuple)) and len(value) < 10:
                safe_params[key] = list(value)[:5]  # 只保留前5个
            else:
                safe_params[key] = str(value)[:100]  # 转为字符串并截断
        return safe_params

    def _summarize_perception(self, perception: dict) -> dict:
        """提取感知数据的关键摘要"""
        if not isinstance(perception, dict):
            return {}

        summary = {}
        try:
            # 窗口数量
            windows = perception.get('windows', [])
            summary['window_count'] = len(windows)

            # 进程数量
            processes = perception.get('processes', [])
            summary['process_count'] = len(processes)

            # 资源使用
            summary['cpu_percent'] = perception.get('cpu_percent', 0)
            summary['memory_percent'] = perception.get('memory_percent', 0)

            # 活跃应用类型
            if windows:
                titles = [w.get('title', '').lower()[:20] for w in windows[:3]]
                summary['active_apps'] = titles

        except Exception:
            pass

        return summary

    def record_observation(self, tool_id: str, params: dict, result: dict,
                           source: str = "user", duration: float = 0,
                           context: dict = None):
        """
        增强版降级记录方法 - 简化接口记录观察

        将简化参数转换为完整格式，调用 observe_tool_execution 进行记录

        Args:
            tool_id: 工具ID
            params: 工具参数
            result: 执行结果
            source: 来源（默认user）
            duration: 执行时长
            context: 上下文
        """
        try:

            # 构建简化的感知数据
            perception_before = {
                'windows': context.get('active_windows', []) if context else [],
                'processes': [],
                'cpu_percent': 50.0,
                'memory_percent': 50.0
            }

            perception_after = {
                'windows': context.get('active_windows', []) if context else [],
                'processes': [],
                'cpu_percent': 50.0,
                'memory_percent': 50.0,
                'last_tool_result': result
            }

            task_context = {
                'task_id': context.get('task_id') if context else None,
                'source': source,
                'duration': duration
            }

            # 调用完整接口
            self.observe_tool_execution(
                tool_id=tool_id,
                params=params,
                perception_before=perception_before,
                perception_after=perception_after,
                result=result,
                task_context=task_context
            )

            logger.debug(f"[WorldModel] record_observation: 记录 {tool_id} 来自 {source}")

        except Exception as e:
            logger.debug(f"[WorldModel] record_observation 失败: {e}")

    def online_update(self, state, action, next_state, reward, done):
        """
        增强版降级在线学习方法 - 更新统计信息

        即使没有PyTorch，也更新训练统计数据，记录学习进度

        Args:
            state: 当前状态（向量或字典）
            action: 执行的动作（向量或工具ID）
            next_state: 下一状态
            reward: 奖励值
            done: 是否完成
        """
        try:
            import time

            import numpy as np

            # 更新训练统计
            self.training_stats['online_updates'] += 1
            self.training_stats['last_loss'] = 0.0  # 降级模式下无实际损失

            # 提取动作ID用于记录
            action_id = action
            if isinstance(action, np.ndarray):
                action_id = "vector_action"
            elif hasattr(action, '__str__'):
                action_id = str(action)[:50]

            # 记录到观察列表（作为学习样本）
            update_record = {
                'action': action_id,
                'reward': float(reward) if reward else 0.0,
                'done': bool(done),
                'timestamp': time.time()
            }

            # 保存到特殊的学习记录文件
            learning_file = self._data_dir / "dummy_learning.json"
            try:
                learning_records = []
                if learning_file.exists():
                    with open(learning_file, encoding='utf-8') as f:
                        learning_records = json.load(f)

                learning_records.append(update_record)

                # 只保留最近100条
                if len(learning_records) > 100:
                    learning_records = learning_records[-100:]

                with open(learning_file, 'w', encoding='utf-8') as f:
                    json.dump(learning_records, f, ensure_ascii=False, indent=2)

            except Exception as e:
                logger.debug(f"[WorldModel] 保存学习记录失败: {e}")

            logger.debug(f"[WorldModel] online_update: 更新 #{self.training_stats['online_updates']}, "
                        f"reward={reward}, done={done}")

        except Exception as e:
            logger.debug(f"[WorldModel] online_update 失败: {e}")

    def get_training_stats(self) -> dict:
        """
        降级训练统计方法

        Returns:
            标记为dummy_mode的统计字典
        """
        return {  # 返回降级模式统计
            'dummy_mode': True,  # 标记为降级模式
            'total_episodes': 0,  # episode数为0
            'online_updates': 0,  # 在线更新次数为0
            'last_loss': 0.0,  # 最新损失为0
            'avg_prediction_error': 0.0  # 平均预测误差为0
        }

    def get_stats(self) -> dict:
        """
        降级统计方法

        Returns:
            标记为dummy_mode的统计字典
        """
        return {  # 返回降级模式统计
            'dummy_mode': True,  # 标记为降级模式
            'total_experiences': 0,  # 总经验数为0
            'successful_predictions': 0,  # 成功预测数为0
            'failed_predictions': 0,  # 失败预测数为0
            'average_loss': 0.0,  # 平均损失为0
            'device': 'cpu'  # 设备为CPU
        }

    def get_prediction_accuracy(self, test_data=None) -> float:
        """
        降级预测准确率方法

        Args:
            test_data: 测试数据（被忽略）

        Returns:
            0.0 - 降级模式下准确率为0
        """
        return 0.0  # 返回0.0

    def stop(self):
        """
        增强版降级停止方法 - 保存状态并清理资源

        即使在降级模式下，也保存统计数据到文件
        """
        try:
            self._save()
            logger.info(f"[WorldModel] Dummy模式停止，已保存 {self.stats['total_experiences']} 条经验")
        except Exception as e:
            logger.warning(f"[WorldModel] stop 保存失败: {e}")

    def _save(self):
        """
        增强版降级保存方法 - 持久化统计数据

        保存统计数据、工具历史和学习记录到JSON文件
        """
        try:
            # 保存统计数据
            stats_data = {
                'stats': self.stats,
                'training_stats': self.training_stats,
                'tool_history': self._tool_history,
                'saved_at': time.time()
            }

            with open(self._stats_file, 'w', encoding='utf-8') as f:
                json.dump(stats_data, f, ensure_ascii=False, indent=2)

            # 保存观察记录（只保留最近100条）
            recent_obs = self._observations[-100:] if self._observations else []
            with open(self._observations_file, 'w', encoding='utf-8') as f:
                json.dump(recent_obs, f, ensure_ascii=False, indent=2)

            logger.debug(f"[WorldModel] _save: 已保存到 {self._data_dir}")

        except Exception as e:
            logger.warning(f"[WorldModel] _save 失败: {e}")

    def _load(self):
        """
        增强版降级加载方法 - 恢复统计数据

        从JSON文件加载统计数据、工具历史和学习记录
        """
        try:
            # 加载统计数据
            if self._stats_file.exists():
                with open(self._stats_file, encoding='utf-8') as f:
                    stats_data = json.load(f)

                self.stats = stats_data.get('stats', self.stats)
                self.training_stats = stats_data.get('training_stats', self.training_stats)
                self._tool_history = stats_data.get('tool_history', {})

                logger.info(f"[WorldModel] _load: 已加载统计，共 {self.stats.get('total_experiences', 0)} 条经验")

            # 加载观察记录
            if self._observations_file.exists():
                with open(self._observations_file, encoding='utf-8') as f:
                    self._observations = json.load(f)

                logger.debug(f"[WorldModel] _load: 已加载 {len(self._observations)} 条观察记录")

        except Exception as e:
            logger.warning(f"[WorldModel] _load 失败: {e}")
            # 加载失败时使用默认值（已在__init__中设置）


# ============ 代理类 ============
class WorldModelProxy:
    """
    世界模型代理 - 自动选择实际实现或降级实现

    使用单例模式，确保全局只有一个实例
    通过__getattr__将所有方法调用转发到后端
    """

    _instance = None  # 类变量：单例实例引用
    _backend = None  # 类变量：后端实现引用（实际WorldModel或DummyWorldModel）
    _initialized = False  # 类变量：初始化标志

    def __new__(cls, *args, **kwargs):
        """
        重写new方法实现单例模式

        Args:
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            WorldModelProxy单例实例
        """
        if cls._instance is None:  # 如果实例不存在
            cls._instance = super().__new__(cls)  # 创建实例
        return cls._instance  # 返回实例

    def __init__(self, *args, **kwargs):
        """
        构造函数

        Args:
            *args: 位置参数，传递给后端
            **kwargs: 关键字参数，传递给后端
        """
        if self._initialized:  # 如果已初始化
            return  # 直接返回，避免重复初始化
        self._initialized = True  # 标记为已初始化

        # 决定使用哪个后端
        self._init_backend(*args, **kwargs)  # 初始化后端

    def _init_backend(self, *args, **kwargs):
        """
        初始化后端实现
        根据PyTorch可用性和配置决定使用哪个后端

        Args:
            *args: 传递给后端构造函数的参数
            **kwargs: 传递给后端构造函数的参数
        """
        if self._backend is not None:  # 如果后端已初始化
            return  # 直接返回

        torch_ok = is_torch_available()  # 检查PyTorch可用性
        enabled = is_world_model_enabled()  # 检查配置是否启用

        if torch_ok and enabled:  # 如果PyTorch可用且配置启用
            try:  # 尝试加载实际实现
                # 延迟导入实际实现
                from core.world_model.world_model import WorldModel  # 导入真实后端
                self._backend = WorldModel(*args, **kwargs)  # 创建真实后端实例
                logger.info("[WorldModel] Using PyTorch backend (TransformerWorldModel)")  # 记录日志
            except Exception as e:  # 捕获加载失败异常
                logger.error(f"[WorldModel] Failed to load PyTorch backend: {e}")  # 记录错误
                logger.info("[WorldModel] Falling back to DummyWorldModel")  # 记录降级
                self._backend = DummyWorldModel(*args, **kwargs)  # 使用降级实现
        else:  # PyTorch不可用或配置禁用
            self._backend = DummyWorldModel(*args, **kwargs)  # 使用降级实现
            if not torch_ok:  # 如果PyTorch不可用
                logger.info("[WorldModel] Reason: PyTorch not available")  # 记录原因
            if not enabled:  # 如果配置禁用
                logger.info("[WorldModel] Reason: Disabled in config")  # 记录原因

    def __getattr__(self, name):
        """
        代理所有方法调用到后端
        这是核心代理逻辑，将所有未定义的属性/方法调用转发到实际后端

        Args:
            name: 属性/方法名

        Returns:
            后端的属性/方法
        """
        if self._backend is None:  # 如果后端未初始化
            self._init_backend()  # 初始化后端
        return getattr(self._backend, name)  # 获取后端的属性/方法

    @property  # 属性装饰器
    def available(self) -> bool:
        """
        检查是否使用真实后端（非降级）

        Returns:
            True表示使用真实后端，False表示使用降级实现
        """
        return not isinstance(self._backend, DummyWorldModel)  # 检查后端类型

    @property  # 属性装饰器
    def dummy_mode(self) -> bool:
        """
        检查是否处于降级模式

        Returns:
            True表示处于降级模式，False表示使用真实后端
        """
        return isinstance(self._backend, DummyWorldModel)  # 检查后端类型


# ============ 兼容接口 ============
# 保持与原有 get_world_model() 函数兼容
_world_model_instance = None  # 全局变量：缓存get_world_model返回的实例

def get_world_model(*args, **kwargs):
    """
    获取世界模型实例（代理）

    这是原有的入口函数，保持完全兼容
    返回WorldModelProxy单例实例

    Args:
        *args: 传递给WorldModelProxy的参数
        **kwargs: 传递给WorldModelProxy的参数

    Returns:
        WorldModelProxy实例（单例）
    """
    global _world_model_instance  # 声明使用全局变量
    if _world_model_instance is None:  # 如果实例不存在
        _world_model_instance = WorldModelProxy(*args, **kwargs)  # 创建实例
    return _world_model_instance  # 返回实例


# 保持 WorldModel 类名兼容（用于类型检查和现有代码）
WorldModel = WorldModelProxy  # 将WorldModel指向WorldModelProxy，保持兼容


# ============ 便捷函数 ============
def get_world_model_status() -> dict[str, Any]:
    """
    获取世界模型状态信息

    用于诊断和监控世界模型的运行状态

    Returns:
        状态字典，包含以下键：
        - torch_available: PyTorch是否可用
        - enabled: 配置是否启用
        - training_enabled: 训练是否启用
        - dummy_mode: 是否处于降级模式
        - backend_type: 后端类型（dummy或pytorch）
    """
    return {  # 返回状态字典
        'torch_available': is_torch_available(),  # PyTorch可用性
        'enabled': is_world_model_enabled(),  # 配置启用状态
        'training_enabled': is_training_enabled(),  # 训练启用状态
        'dummy_mode': not (is_torch_available() and is_world_model_enabled()),  # 是否降级模式
        'backend_type': 'dummy' if not is_torch_available() else 'pytorch'  # 后端类型
    }


# ============ 模块加载时的信息输出 ============
if __name__ != "__main__":  # 当模块被导入时（不是直接运行）
    # 模块被导入时记录状态
    logger.debug(f"[WorldModel] Module loaded, torch available: {is_torch_available()}")  # 记录调试日志


# ═══════════════════════════════════════════════════════════════════════════════
# 文件总结性注释
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# 本文件是SiliconBase V5系统世界模型的代理层（Proxy Layer），位于真实世界模型实现与调用者之间。
# 核心职责是实现PyTorch的延迟加载和优雅降级，确保系统在以下场景下仍能正常运行：
# 1. 无PyTorch环境的轻量级部署
# 2. 用户显式禁用深度学习功能
# 3. PyTorch安装损坏或版本不兼容
# 4. 需要隔离深度学习依赖进行测试
#
# 【核心组件】
# 1. Torch可用性检测 (is_torch_available):
#    - 全局缓存检测结果，避免重复导入尝试
#    - 支持环境变量SILICONBASE_DISABLE_TORCH强制禁用
#    - 记录详细日志便于诊断
#
# 2. 配置检查 (is_world_model_enabled/is_training_enabled):
#    - 从core.config读取配置开关
#    - 异常时默认启用，确保向后兼容
#    - 独立控制世界模型和训练功能
#
# 3. DummyWorldModel（降级实现）:
#    - 完整实现WorldModel所有公共API
#    - 返回中性值（成功率0.5、置信度0等）
#    - 静默处理观察/训练方法（pass）
#    - 标记dummy_mode便于调用者检测
#
# 4. WorldModelProxy（代理类）:
#    - 单例模式确保全局唯一实例
#    - 延迟初始化后端（首次使用时）
#    - __getattr__自动转发所有方法调用
#    - 提供available和dummy_mode属性检测状态
#
# 5. 兼容接口:
#    - get_world_model(): 原有入口函数
#    - WorldModel = WorldModelProxy: 类型别名
#    - get_world_model_status(): 状态查询函数
#
# 【后端选择逻辑】
# 初始化时按以下优先级选择后端：
#
# 条件1: PyTorch可用 AND 配置启用 → 使用PyTorch后端
#   - 尝试导入core.world_model_backend.WorldModel
#   - 成功则使用TransformerWorldModel
#   - 失败则降级到DummyWorldModel
#
# 条件2: PyTorch不可用 OR 配置禁用 → 使用DummyWorldModel
#   - 记录降级原因到日志
#   - 所有方法返回中性值
#
# 【关联文件】
# - core/world_model.py: 原始PyTorch实现（被此代理包装）
# - core/world_model_backend.py: 实际后端实现（延迟导入）
# - core/config.py: 配置模块，提供world_model.enabled等开关
# - core/tool_manager.py: 调用observe_tool_execution记录经验
# - core/agent_loop.py: 调用get_prediction_for_prompt获取预测
#
# 【数据流向】
#
# 正常流程（PyTorch可用）:
#   调用者 → WorldModelProxy.__getattr__ → 转发到PyTorch后端 → 执行预测/训练
#
# 降级流程（PyTorch不可用）:
#   调用者 → WorldModelProxy.__getattr__ → 转发到DummyWorldModel → 返回中性值
#
# 初始化流程:
#   导入模块 → is_torch_available检测 → get_world_model调用 → _init_backend选择后端
#
# 【达到的效果】
# 1. 依赖解耦: 系统可在无PyTorch环境下运行，降低部署门槛
# 2. 优雅降级: 功能受限但系统不崩溃，用户体验连续
# 3. 透明代理: 调用者无需修改代码，自动适配可用后端
# 4. 配置灵活: 支持环境变量和配置文件双重控制
# 5. 诊断友好: 详细日志记录后端选择过程，便于问题排查
#
# 【异常处理策略】
# - 导入异常: 捕获ImportError，标记torch不可用，使用降级实现
# - 配置异常: 捕获任何配置读取异常，默认启用，确保可用性
# - 后端初始化异常: 捕获Exception，记录错误，降级到DummyWorldModel
# - 代理调用异常: 不捕获，直接抛出，保持异常透传
#
# 【使用示例】
#   from core.world_model.world_model_proxy import get_world_model, WorldModel
#
#   wm = get_world_model()  # 自动选择合适的后端
#
#   # 检查是否可用
#   if wm.dummy_mode:
#       print("世界模型不可用，使用默认策略")
#
#   # 调用预测（自动转发到后端）
#   result = wm.predict_detailed(perception, tool_id, params)
#
# ═══════════════════════════════════════════════════════════════════════════════
