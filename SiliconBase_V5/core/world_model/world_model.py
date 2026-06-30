#!/usr/bin/env python3  # 指定Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文字符
"""  # 多行文档字符串开始
世界模型 - 硅基生命的核心认知引擎 V2.0 (Transformer Edition)  # 模块名称和版本

设计理念：  # 设计理念说明
- 学习行动-结果映射，预测未来状态  # 核心能力1：学习因果关系
- 反事实推理："如果我当时这样做会怎样"  # 核心能力2：反事实推理
- 行动评估：预测不同行动的预期收益和风险  # 核心能力3：行动评估
- 与底座深度集成：感知状态、工具效果、任务结果  # 核心能力4：系统集成
- 在线学习：每次工具调用后实时更新  # 核心能力5：在线学习
- MCTS规划：使用蒙特卡洛树搜索进行行动规划  # 核心能力6：规划能力

架构 V2.0：  # 架构组成说明
- 状态编码器：将底座感知编码为向量  # 组件1：状态编码器
- Transformer动态模型：使用自注意力预测下一状态  # 组件2：Transformer模型
- 结果预测器：预测任务成功率、奖励和完成状态  # 组件3：结果预测器
- 想象引擎：模拟多步行动序列  # 组件4：想象引擎
- MCTS规划器：基于世界模型的蒙特卡洛树搜索  # 组件5：MCTS规划器
"""  # 文档字符串结束

import numpy as np  # 导入NumPy，用于数值计算和数组操作

try:
    import torch  # 导入PyTorch深度学习框架
    import torch.nn as nn  # 导入PyTorch神经网络模块
    import torch.nn.functional as F  # 导入PyTorch函数式API
    import torch.optim as optim  # 导入PyTorch优化器模块
    TORCH_AVAILABLE = True
except Exception:  # PyTorch 未安装时提供降级桩
    torch = None  # type: ignore[assignment]

    class _DummyModule:
        pass

    class _DummyNN:
        Module = _DummyModule

        class TransformerEncoderLayer:
            pass

        class TransformerEncoder:
            pass

        class Linear:
            pass

        class Sequential:
            pass

        class MSELoss:
            pass

        class BCELoss:
            pass

    class _DummyOptim:
        class Adam:
            pass

        class lr_scheduler:
            class StepLR:
                def step(self):
                    pass

    class _DummyF:
        @staticmethod
        def binary_cross_entropy(*args, **kwargs):
            pass

        @staticmethod
        def normalize(*args, **kwargs):
            pass

        @staticmethod
        def relu(*args, **kwargs):
            pass

        @staticmethod
        def softmax(*args, **kwargs):
            pass

    nn = _DummyNN()  # type: ignore[assignment]
    F = _DummyF()  # type: ignore[assignment]
    optim = _DummyOptim()  # type: ignore[assignment]
    TORCH_AVAILABLE = False
import asyncio  # 异步IO，用于后台任务调度
import contextlib
import json  # 导入JSON模块，用于数据序列化
import math  # 导入数学模块，用于位置编码计算
import random  # 导入随机模块，用于MCTS的随机选择
import time  # 导入时间模块，用于时间戳和休眠
from collections import defaultdict, deque  # 导入双端队列（经验池）和默认字典
from datetime import datetime  # 导入日期时间类，用于时间特征编码
from pathlib import Path  # 导入Path类，用于路径操作
from threading import Lock as ThreadLock  # 保留给同步方法（observe_tool_execution等）使用
from typing import Any  # 导入类型提示

from core.logger import logger  # 从core.logger导入日志记录器
from core.memory.memory_service import get_memory_service  # 【P1-迁移】异步记忆服务入口
from core.memory.memory_source import MemorySource  # Agent-4: 导入MemorySource枚举
from core.sync.event_bus import event_bus  # 【ExperienceBus】事件总线

# 【魔法数字修复】导入全局常量
try:
    from core.constants import MCTSConfig, TimeFeatures, WindowLimits
except ImportError as e:
    logger.error(f"[WorldModel] 导入常量失败: {e}")
    # 定义 fallback 常量值
    class TimeFeatures:
        HOURS_PER_DAY = 24.0
        MINUTES_PER_HOUR = 60.0
        DAYS_PER_WEEK = 7.0
    class WindowLimits:
        MAX_WINDOW_COUNT = 10
        MAX_PROCESS_COUNT = 100
    class MCTSConfig:
        DEFAULT_SIMULATIONS = 50


class StateEncoder:
    """
    将底座的复杂状态编码为固定维度的向量
    输入：感知数据、任务信息、环境状态
    输出：state_vector (state_dim,)
    """
    def __init__(self, state_dim: int = 128):  # 构造函数，默认状态维度128
        self.state_dim = state_dim  # 存储状态维度
        self.cache = {}  # 初始化缓存字典，用于缓存编码结果

    def encode(self, perception: dict[str, Any], task_context: dict[str, Any] | None = None,
               emotional_state: dict[str, Any] | None = None) -> np.ndarray:
        """
        编码当前状态

        Args:
            perception: 感知数据（窗口、进程、资源等）
            task_context: 任务上下文（当前执行的工具、目标等）
            emotional_state: 情绪状态（能量、好奇心等）

        Returns:
            state_vector: 状态向量
        """
        # 特征提取
        features = []  # 初始化特征列表

        # 1. 感知特征 (32维)
        window_count = len(perception.get('windows', []))  # 获取窗口数量，默认空列表
        process_count = len(perception.get('processes', []))  # 获取进程数量
        cpu_usage = perception.get('cpu_percent', 0) / 100.0  # CPU使用率归一化到0-1
        memory_usage = perception.get('memory_percent', 0) / 100.0  # 内存使用率归一化

        # 活跃应用类型编码（使用简单的one-hot思路）
        active_apps = self._encode_active_apps(perception.get('windows', []))  # 编码活跃应用类型

        features.extend([  # 扩展特征列表
            window_count / WindowLimits.MAX_WINDOW_COUNT,  # 窗口数量归一化（假设最大10个）
            process_count / WindowLimits.MAX_PROCESS_COUNT,  # 进程数量归一化（假设最大100个）
            cpu_usage,  # CPU使用率（已归一化）
            memory_usage,  # 内存使用率（已归一化）
        ])
        features.extend(active_apps[:28])  # 添加活跃应用特征，截取前28维，总共32维

        # 2. 任务上下文特征 (32维)
        task_features = self._encode_task_context(task_context)  # 编码任务上下文
        features.extend(task_features)  # 添加到特征列表

        # 3. 情绪状态特征 (16维)
        if emotional_state:  # 如果提供了情绪状态
            features.extend([  # 添加情绪特征
                emotional_state.get('energy', 5) / 10.0,  # 能量值归一化（默认5/10）
                emotional_state.get('curiosity', 5) / 10.0,  # 好奇心归一化
                emotional_state.get('satisfaction', 5) / 10.0,  # 满意度归一化
            ])
        else:  # 未提供情绪状态
            features.extend([0.5, 0.5, 0.5])  # 使用默认值0.5
        features.extend([0] * 13)  # 填充到16维，补13个0

        # 4. 时间特征 (8维)
        now = datetime.now()  # 获取当前时间
        features.extend([  # 添加时间特征
            now.hour / TimeFeatures.HOURS_PER_DAY,  # 小时归一化（0-24）
            now.minute / TimeFeatures.MINUTES_PER_HOUR,  # 分钟归一化（0-60）
            now.weekday() / TimeFeatures.DAYS_PER_WEEK,  # 星期归一化（0-7）
        ])
        features.extend([0] * 5)  # 填充到8维，补5个0

        # 5. 历史成功/失败特征 (8维)
        recent_results = task_context.get('recent_results', []) if task_context else []  # 获取最近结果
        if recent_results:  # 如果有历史结果
            success_rate = sum(recent_results[-10:]) / min(len(recent_results), 10)  # 计算最近10次的成功率
            features.extend([success_rate, len(recent_results) / 100.0])  # 添加成功率和结果数量
        else:  # 无历史结果
            features.extend([0.5, 0])  # 默认成功率0.5，数量0
        features.extend([0] * 6)  # 填充到8维，补6个0

        # 6. 填充到目标维度
        while len(features) < self.state_dim:  # 如果特征维度不足
            features.append(0)  # 补0填充

        return np.array(features[:self.state_dim], dtype=np.float32)  # 截取目标维度，转为float32数组返回

    def _encode_active_apps(self, windows: list[dict]) -> list[float]:
        """编码活跃应用类型"""
        app_types = defaultdict(float)  # 使用默认字典统计各类应用数量

        for win in windows:  # 遍历所有窗口
            title = win.get('title', '').lower()  # 获取窗口标题并转为小写
            # 根据标题关键词判断应用类型
            if any(kw in title for kw in ['browser', 'chrome', 'edge', 'firefox']):  # 浏览器关键词
                app_types['browser'] += 1  # 浏览器类型计数+1
            elif any(kw in title for kw in ['code', 'vscode', 'pycharm', 'idea']):  # IDE关键词
                app_types['ide'] += 1  # IDE类型计数+1
            elif any(kw in title for kw in ['music', '网易云', 'qq音乐', 'spotify']):  # 音乐关键词
                app_types['music'] += 1  # 音乐类型计数+1
            elif any(kw in title for kw in ['video', 'movie', 'mpv', 'vlc']):  # 视频关键词
                app_types['video'] += 1  # 视频类型计数+1
            elif any(kw in title for kw in ['game', 'steam']):  # 游戏关键词
                app_types['game'] += 1  # 游戏类型计数+1
            elif any(kw in title for kw in ['doc', 'word', 'excel', 'pdf']):  # 文档关键词
                app_types['document'] += 1  # 文档类型计数+1
            elif any(kw in title for kw in ['chat', 'wechat', 'qq', 'telegram']):  # 聊天关键词
                app_types['chat'] += 1  # 聊天类型计数+1
            else:  # 其他类型
                app_types['other'] += 1  # 其他类型计数+1

        # 返回归一化的计数
        total = sum(app_types.values()) or 1  # 计算总数，避免除0，至少为1
        return [  # 返回归一化的8维向量
            app_types['browser'] / total,  # 浏览器占比
            app_types['ide'] / total,  # IDE占比
            app_types['music'] / total,  # 音乐占比
            app_types['video'] / total,  # 视频占比
            app_types['game'] / total,  # 游戏占比
            app_types['document'] / total,  # 文档占比
            app_types['chat'] / total,  # 聊天占比
            app_types['other'] / total,  # 其他占比
        ]

    def _encode_task_context(self, task_context: dict) -> list[float]:
        """编码任务上下文"""
        if not task_context:  # 如果没有任务上下文
            return [0] * 32  # 返回32维零向量

        features = []  # 初始化特征列表

        # 工具类型编码
        tool_id = task_context.get('tool_id', '')  # 获取工具ID
        tool_categories = {  # 定义工具类别映射
            'launch_app': 0, 'window': 1, 'mouse': 2, 'keyboard': 3,
            'screen': 4, 'file': 5, 'system': 6, 'web': 7
        }
        cat_id = 7  # 默认类别为'其他'（7）
        for key, val in tool_categories.items():  # 遍历类别映射
            if key in tool_id.lower():  # 检查工具ID是否包含类别关键词
                cat_id = val  # 匹配成功，设置类别ID
                break  # 退出循环

        # one-hot编码工具类别 (8维)
        tool_onehot = [0] * 8  # 初始化8维零向量
        tool_onehot[cat_id] = 1  # 设置对应类别为1
        features.extend(tool_onehot)  # 添加到特征列表

        # 任务目标编码（简单哈希）(8维)
        goal = task_context.get('goal', '')  # 获取任务目标
        goal_hash = hash(goal) % 8  # 对目标字符串哈希，取模8得到0-7
        goal_onehot = [0] * 8  # 初始化8维零向量
        goal_onehot[goal_hash] = 1  # 设置对应位置为1
        features.extend(goal_onehot)  # 添加到特征列表

        # 历史尝试次数 (1维)
        attempt_count = task_context.get('attempt_count', 0)  # 获取尝试次数
        features.append(attempt_count / 10.0)  # 归一化（假设最大10次）

        # 填充
        features.extend([0] * 15)  # 补15个0，总共32维

        return features  # 返回32维特征向量


class ActionEncoder:
    """将工具调用编码为动作向量"""

    def __init__(self, action_dim: int = 32):  # 构造函数，默认动作维度32
        self.action_dim = action_dim  # 存储动作维度
        self.tool_embeddings = {}  # 缓存工具嵌入，避免重复计算

    def encode(self, tool_id: str, params: dict) -> np.ndarray:
        """
        编码工具调用为动作向量

        Args:
            tool_id: 工具ID
            params: 工具参数

        Returns:
            action_vector: 动作向量
        """
        features = []  # 初始化特征列表

        # 1. 工具类型编码 (16维)
        tool_type = self._get_tool_type(tool_id)  # 获取工具类型ID（0-7）
        type_onehot = [0] * 8  # 初始化8维零向量
        type_onehot[tool_type] = 1  # 设置对应类型为1
        features.extend(type_onehot)  # 添加到特征列表（8维）

        # 工具ID哈希 (8维)
        tool_hash = hash(tool_id) % 8  # 对工具ID哈希取模
        tool_onehot = [0] * 8  # 初始化8维零向量
        tool_onehot[tool_hash] = 1  # 设置对应位置为1
        features.extend(tool_onehot)  # 添加到特征列表（8维）

        # 2. 参数特征 (8维)
        param_count = len(params)  # 获取参数数量
        # 检查参数中是否包含特定类型
        has_text = any(isinstance(v, str) and len(v) > 0 for v in params.values())  # 是否有非空字符串
        has_number = any(isinstance(v, (int, float)) for v in params.values())  # 是否有数字
        has_path = any(isinstance(v, str) and ('/' in v or '\\' in v) for v in params.values())  # 是否有路径

        features.extend([  # 添加参数特征（4维）
            param_count / 10.0,  # 参数数量归一化（假设最大10个）
            1.0 if has_text else 0.0,  # 是否有文本参数
            1.0 if has_number else 0.0,  # 是否有数字参数
            1.0 if has_path else 0.0,  # 是否有路径参数
        ])
        features.extend([0] * 4)  # 填充到8维，补4个0

        # 3. 填充到目标维度
        while len(features) < self.action_dim:  # 如果特征维度不足
            features.append(0)  # 补0填充

        return np.array(features[:self.action_dim], dtype=np.float32)  # 截取目标维度，转为数组返回

    def _get_tool_type(self, tool_id: str) -> int:
        """获取工具类型ID"""
        tool_lower = tool_id.lower()  # 转为小写进行匹配
        if 'launch' in tool_lower or 'app' in tool_lower:  # 应用启动类
            return 0  # 应用启动
        elif 'window' in tool_lower:  # 窗口操作类
            return 1  # 窗口操作
        elif 'mouse' in tool_lower or 'click' in tool_lower:  # 鼠标操作类
            return 2  # 鼠标操作
        elif 'keyboard' in tool_lower or 'input' in tool_lower:  # 键盘输入类
            return 3  # 键盘输入
        elif 'screen' in tool_lower or 'ocr' in tool_lower or 'shot' in tool_lower:  # 屏幕操作类
            return 4  # 屏幕操作
        elif 'file' in tool_lower:  # 文件操作类
            return 5  # 文件操作
        elif 'system' in tool_lower or 'info' in tool_lower:  # 系统操作类
            return 6  # 系统操作
        else:  # 其他类型
            return 7  # 其他


class PositionalEncoding(nn.Module):
    """位置编码 - 为Transformer提供序列位置信息"""
    def __init__(self, d_model, max_len=5000):  # 构造函数，d_model为模型维度
        super().__init__()  # 调用父类构造函数
        pe = torch.zeros(max_len, d_model)  # 初始化位置编码矩阵 [max_len, d_model]
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)  # 位置索引 [max_len, 1]
        # 计算位置编码的分母项
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)  # 偶数维使用sin
        pe[:, 1::2] = torch.cos(position * div_term)  # 奇数维使用cos
        self.register_buffer('pe', pe)  # 注册为缓冲区（不参与训练）

    def forward(self, x):
        """前向传播，添加位置编码到输入"""
        return x + self.pe[:x.size(1)].unsqueeze(0)  # 截取所需长度并广播相加


class TransformerWorldModel(nn.Module):
    """基于Transformer的世界模型 - 核心预测网络"""

    def __init__(self, state_dim, action_dim, hidden_dim=256, num_heads=8, num_layers=4, dropout=0.1):
        """
        构造函数
        Args:
            state_dim: 状态向量维度
            action_dim: 动作向量维度
            hidden_dim: Transformer隐藏层维度
            num_heads: 注意力头数
            num_layers: Transformer层数
            dropout: Dropout概率
        """
        super().__init__()  # 调用父类构造函数
        self.state_dim = state_dim  # 存储状态维度
        self.action_dim = action_dim  # 存储动作维度
        self.hidden_dim = hidden_dim  # 存储隐藏层维度

        # 状态和行动嵌入层 - 将输入向量投影到隐藏维度
        self.state_embed = nn.Linear(state_dim, hidden_dim)  # 状态嵌入线性层
        self.action_embed = nn.Linear(action_dim, hidden_dim)  # 动作嵌入线性层

        # Transformer编码器
        encoder_layer = nn.TransformerEncoderLayer(  # 定义Transformer编码器层
            d_model=hidden_dim,  # 模型维度
            nhead=num_heads,  # 注意力头数
            dim_feedforward=hidden_dim * 4,  # 前馈网络维度（4倍隐藏层）
            dropout=dropout,  # Dropout概率
            batch_first=True  # 输入格式为[batch, seq, feature]
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)  # 堆叠多层

        # 位置编码
        self.pos_encoding = PositionalEncoding(hidden_dim)  # 初始化位置编码模块

        # 预测头 - 下一状态预测
        self.next_state_pred = nn.Sequential(  # 顺序容器
            nn.Linear(hidden_dim, hidden_dim),  # 线性层
            nn.LayerNorm(hidden_dim),  # 层归一化
            nn.ReLU(),  # ReLU激活
            nn.Dropout(dropout),  # Dropout正则化
            nn.Linear(hidden_dim, state_dim)  # 输出层，输出状态维度
        )
        # 预测头 - 奖励预测
        self.reward_pred = nn.Sequential(  # 顺序容器
            nn.Linear(hidden_dim, hidden_dim // 2),  # 降维线性层
            nn.ReLU(),  # ReLU激活
            nn.Linear(hidden_dim // 2, 1)  # 输出层，输出标量奖励
        )
        # 预测头 - 结束标志预测
        self.done_pred = nn.Sequential(  # 顺序容器
            nn.Linear(hidden_dim, hidden_dim // 2),  # 降维线性层
            nn.ReLU(),  # ReLU激活
            nn.Linear(hidden_dim // 2, 1)  # 输出层，输出完成概率
        )

    def forward(self, state, action):
        """
        前向传播
        Args:
            state: 状态张量 [batch, state_dim]
            action: 动作张量 [batch, action_dim]
        Returns:
            next_state: 预测的下一状态 [batch, state_dim]
            reward: 预测的奖励 [batch, 1]
            done: 预测的完成概率 [batch, 1]
        """
        # 嵌入 - 将输入投影到隐藏维度
        state_emb = self.state_embed(state)  # 状态嵌入 [batch, hidden_dim]
        action_emb = self.action_embed(action)  # 动作嵌入 [batch, hidden_dim]

        # 拼接序列: [batch, 2, hidden]
        seq = torch.stack([state_emb, action_emb], dim=1)  # 在第1维堆叠，形成序列
        seq = self.pos_encoding(seq)  # 添加位置编码

        # Transformer处理
        out = self.transformer(seq)  # [batch, 2, hidden_dim]

        # 取序列的平均池化作为输出
        pooled = out.mean(dim=1)  # [batch, hidden_dim]

        next_state = self.next_state_pred(pooled)  # 预测下一状态
        reward = self.reward_pred(pooled)  # 预测奖励
        done = torch.sigmoid(self.done_pred(pooled))  # 预测完成概率，使用sigmoid激活

        return next_state, reward, done  # 返回三个预测结果

    def get_attention_weights(self, state, action):
        """获取注意力权重用于可视化（当前为占位实现）"""
        state_emb = self.state_embed(state)  # 状态嵌入
        action_emb = self.action_embed(action)  # 动作嵌入
        seq = torch.stack([state_emb, action_emb], dim=1)  # 拼接序列
        seq = self.pos_encoding(seq)  # 添加位置编码

        # 使用forward hook获取注意力权重

        def hook_fn(module, input, output):
            # 保存注意力权重
            pass  # 当前为占位实现

        # 注册hook并前向传播
        hooks = []  # 存储hook句柄
        for layer in self.transformer.layers:  # 遍历所有Transformer层
            hook = layer.self_attn.register_forward_hook(hook_fn)  # 注册hook
            hooks.append(hook)  # 保存句柄

        out = self.transformer(seq)  # 前向传播

        # 移除hooks
        for hook in hooks:  # 遍历所有hook
            hook.remove()  # 移除hook

        return out  # 返回输出


class WorldModelNet(nn.Module):
    """
    世界模型网络（向后兼容的包装器）
    底层使用TransformerWorldModel
    """

    def __init__(self, state_dim: int, action_dim: int, hidden_dim: int = 256):
        """
        构造函数
        Args:
            state_dim: 状态维度
            action_dim: 动作维度
            hidden_dim: 隐藏层维度
        """
        super().__init__()  # 调用父类构造函数
        self.transformer_model = TransformerWorldModel(  # 创建Transformer模型实例
            state_dim=state_dim,  # 状态维度
            action_dim=action_dim,  # 动作维度
            hidden_dim=hidden_dim,  # 隐藏层维度
            num_heads=8,  # 8个注意力头
            num_layers=4,  # 4层Transformer
            dropout=0.1  # Dropout概率0.1
        )

    def forward(self, state, action):
        """
        前向传播，保持与旧接口兼容
        返回: (next_state, outcome) 其中 outcome = [success_prob, reward, done]
        """
        next_state, reward, done = self.transformer_model(state, action)  # 调用底层模型
        # 将输出组合成旧格式：outcome包含 [success_prob, reward_mapped, done]
        reward_mapped = torch.sigmoid(reward)  # 映射到[0,1]
        outcome = torch.cat([  # 拼接三个值
            torch.sigmoid(done),  # 作为success_prob
            reward_mapped,  # 奖励
            1 - done  # risk作为done的补数
        ], dim=-1)
        return next_state, outcome  # 返回兼容格式的输出


class MCTSNode:
    """MCTS树节点 - 用于蒙特卡洛树搜索"""

    def __init__(self, state, parent=None, action=None, reward=0, done=False):
        """
        构造函数
        Args:
            state: 节点状态
            parent: 父节点（根节点为None）
            action: 到达此节点的动作
            reward: 即时奖励
            done: 是否结束
        """
        self.state = state  # 节点状态
        self.parent = parent  # 父节点引用
        self.action = action  # 到达此节点的动作
        self.reward = reward  # 即时奖励
        self.done = done  # 是否结束
        self.children = {}  # 子节点字典：动作->节点
        self.visits = 0  # 访问次数
        self.value = 0  # 累计价值
        self.depth = parent.depth + 1 if parent else 0  # 节点深度
        self.untried_actions = None  # 未尝试的动作列表

    def select_child(self, exploration_weight):
        """使用UCB1算法选择子节点"""
        best_score = -float('inf')  # 初始化最佳分数为负无穷
        best_child = None  # 初始化最佳子节点

        for _action, child in self.children.items():  # 遍历所有子节点
            if child.visits == 0:  # 如果子节点未被访问
                score = float('inf')  # 给予无限分数，鼓励探索
            else:  # 已访问过的节点
                exploitation = child.value / child.visits  # 利用项：平均价值
                exploration = exploration_weight * math.sqrt(math.log(self.visits) / child.visits)  # 探索项
                score = exploitation + exploration  # UCB1分数 = 利用 + 探索

            if score > best_score:  # 如果当前分数更高
                best_score = score  # 更新最佳分数
                best_child = child  # 更新最佳子节点

        return best_child  # 返回最佳子节点

    def expand(self, action, next_state, reward, done):
        """扩展新节点"""
        child = MCTSNode(next_state, self, action, reward, done)  # 创建子节点
        self.children[action] = child  # 添加到子节点字典
        return child  # 返回新创建的子节点

    def backpropagate(self, value):
        """反向传播价值 - 从叶节点更新到根节点"""
        self.visits += 1  # 访问次数+1
        self.value += value + self.reward  # 累加价值（包含即时奖励）
        if self.parent:  # 如果有父节点
            self.parent.backpropagate(value)  # 递归更新父节点

    def is_fully_expanded(self):
        """检查是否已完全扩展（所有动作都已尝试）"""
        return len(self.untried_actions) == 0 if self.untried_actions else True  # 未尝试列表为空则已完全扩展

    def is_terminal(self, horizon):
        """检查是否到达终止状态（完成或达到深度限制）"""
        return self.done or self.depth >= horizon  # 完成标志为True或深度超过horizon

    def get_best_action(self):
        """返回访问次数最多的动作（用于最终决策）"""
        if not self.children:  # 如果没有子节点
            return None  # 返回None
        return max(self.children.items(), key=lambda x: x[1].visits)[0]  # 返回访问次数最多的动作

    def get_action_value(self, action):
        """获取某动作的Q值"""
        if action not in self.children:  # 如果动作不在子节点中
            return 0  # 返回0
        child = self.children[action]  # 获取子节点
        if child.visits == 0:  # 如果未被访问
            return 0  # 返回0
        return child.value / child.visits  # 返回平均价值作为Q值


class MCTSPlanner:
    """基于世界模型的蒙特卡洛树搜索规划器"""

    def __init__(self, world_model, num_simulations=100, exploration_weight=1.0):
        """
        构造函数
        Args:
            world_model: 世界模型实例，用于预测
            num_simulations: MCTS模拟次数
            exploration_weight: UCB探索权重
        """
        self.world_model = world_model  # 存储世界模型引用
        self.num_simulations = num_simulations  # 模拟次数
        self.exploration_weight = exploration_weight  # 探索权重

    def plan(self, initial_state, available_actions, horizon=5):
        """
        为给定状态规划最优动作序列

        Args:
            initial_state: 当前状态
            available_actions: 可用动作列表
            horizon: 规划horizon（最大深度）

        Returns:
            包含最优动作、动作序列、访问计数和期望价值的字典
        """
        root = MCTSNode(initial_state)  # 创建根节点

        for _ in range(self.num_simulations):  # 执行指定次数的模拟
            node = root  # 从根节点开始

            # Selection: 选择最有希望的节点（UCB1）
            while node.children and node.is_fully_expanded():  # 有子节点且已完全扩展
                node = node.select_child(self.exploration_weight)  # 选择最佳子节点

            # Expansion: 扩展新节点
            if not node.is_terminal(horizon):  # 如果不是终止节点
                action = random.choice(available_actions)  # 随机选择一个动作
                next_state, reward, done = self.world_model.predict(node.state, action)  # 预测结果
                child = node.expand(action, next_state, reward, done)  # 扩展子节点

                # Simulation: 从子节点模拟 rollout
                value = self._simulate(child, available_actions, horizon)  # 模拟获得价值

                # Backpropagation: 反向传播
                child.backpropagate(value)  # 更新访问次数和价值

        # 返回访问次数最多的动作
        best_action = root.get_best_action()  # 获取最佳动作
        action_sequence = self._extract_action_sequence(root, best_action, horizon)  # 提取动作序列

        return {  # 返回规划结果字典
            'best_action': best_action,  # 最优动作
            'action_sequence': action_sequence,  # 动作序列
            'visit_counts': {a: c.visits for a, c in root.children.items()},  # 各动作访问次数
            'expected_value': root.value / root.visits if root.visits > 0 else 0  # 期望价值
        }

    def _simulate(self, node, actions, horizon):
        """从节点进行随机模拟（rollout）"""
        state = node.state  # 当前状态
        total_reward = 0  # 累计奖励

        for step in range(horizon - node.depth):  # 模拟剩余步数
            action = random.choice(actions)  # 随机选择动作
            next_state, reward, done = self.world_model.predict(state, action)  # 预测结果
            total_reward += reward * (0.9 ** step)  # 折扣因子累加奖励

            if done:  # 如果完成
                break  # 结束模拟
            state = next_state  # 更新状态

        return total_reward  # 返回累计奖励

    def _extract_action_sequence(self, root, first_action, horizon):
        """提取从根节点到最佳叶节点的动作序列"""
        sequence = []  # 初始化序列列表
        if first_action:  # 如果存在第一个动作
            sequence.append(first_action)  # 添加到序列

            # 沿着最佳路径走
            current = root.children.get(first_action)  # 获取第一个子节点
            while current and len(sequence) < horizon:  # 未到达深度限制
                best_next = current.get_best_action()  # 获取当前节点的最佳动作
                if best_next:  # 如果存在
                    sequence.append(best_next)  # 添加到序列
                    current = current.children.get(best_next)  # 移动到下一节点
                else:  # 无更多动作
                    break  # 退出循环

        return sequence  # 返回动作序列


class WorldModel:
    """
    世界模型 - 硅基生命的认知核心 V2.0

    功能：
    1. 经验学习：记录并学习行动-结果映射
    2. 状态预测：预测执行动作后的状态（Transformer架构）
    3. 结果预测：预测任务成功率、奖励和完成状态
    4. 反事实推理：模拟"如果这样做会怎样"
    5. 行动建议：使用MCTS规划最优行动序列
    6. 在线学习：每次工具调用后实时更新
    """

    def __init__(self,
                 state_dim: int = 128,  # 状态向量维度，默认128
                 action_dim: int = 32,  # 动作向量维度，默认32
                 hidden_dim: int = 256,  # Transformer隐藏层维度，默认256
                 buffer_size: int = 10000,  # 经验池大小，默认10000
                 batch_size: int = 64,  # 训练批次大小，默认64
                 lr: float = 1e-3,  # 学习率，默认0.001
                 train_interval: int = 10,  # 训练间隔（经验数），默认10
                 save_dir: str = "data/world_model",  # 模型保存目录
                 enable_learning: bool = True,  # 是否启用在线学习
                 use_mcts: bool = True):  # 是否启用MCTS规划

        self.state_dim = state_dim  # 存储状态维度
        self.action_dim = action_dim  # 存储动作维度
        self.batch_size = batch_size  # 存储批次大小
        self.train_interval = train_interval  # 存储训练间隔
        self.enable_learning = enable_learning  # 存储学习开关
        self.use_mcts = use_mcts  # 存储MCTS开关

        # 编码器
        self.state_encoder = StateEncoder(state_dim)  # 创建状态编码器实例
        self.action_encoder = ActionEncoder(action_dim)  # 创建动作编码器实例

        # 经验池
        self.buffer = deque(maxlen=buffer_size)  # 创建有限长度的双端队列作为经验池
        self.episode_buffer = []  # 当前episode的临时缓冲区

        # 神经网络（Transformer架构）
        # 【P0修复】强制使用CPU，避免与Ollama在GPU上竞争导致Windows蓝屏(CLOCK_WATCHDOG_TIMEOUT)
        self.torch_available = TORCH_AVAILABLE
        if TORCH_AVAILABLE:
            self.device = torch.device("cpu")  # 强制使用CPU
            self.model = TransformerWorldModel(  # 创建Transformer模型
                state_dim=state_dim,  # 状态维度
                action_dim=action_dim,  # 动作维度
                hidden_dim=hidden_dim,  # 隐藏层维度
                num_heads=8,  # 8个注意力头
                num_layers=4,  # 4层Transformer
                dropout=0.1  # Dropout概率0.1
            ).to(self.device)  # 将模型移动到计算设备

            self.optimizer = optim.Adam(self.model.parameters(), lr=lr, weight_decay=1e-5)  # Adam优化器
            self.scheduler = optim.lr_scheduler.StepLR(self.optimizer, step_size=100, gamma=0.9)  # 学习率调度器

            # 损失函数
            self.state_loss_fn = nn.MSELoss()  # 状态预测的MSE损失
            self.reward_loss_fn = nn.MSELoss()  # 奖励预测的MSE损失
            self.done_loss_fn = nn.BCELoss()  # 完成标志预测的二元交叉熵损失
        else:
            self.device = None
            self.model = None
            self.optimizer = None
            self.scheduler = None
            self.state_loss_fn = None
            self.reward_loss_fn = None
            self.done_loss_fn = None
            logger.warning("[WorldModel] PyTorch 不可用，世界模型将以降级模式运行")

        # 锁与线程控制
        self.lock = ThreadLock()  # 创建线程锁，保护共享数据（供同步方法使用）
        self.running = True  # 运行标志，控制训练循环
        self.train_counter = 0  # 训练计数器，达到间隔触发训练
        self.step_count = 0  # 训练步数计数器

        # 保存路径
        self.save_dir = Path(save_dir)  # 创建Path对象
        self.save_dir.mkdir(parents=True, exist_ok=True)  # 创建保存目录
        self.model_path = self.save_dir / "world_model.pth"  # 模型文件路径
        self.buffer_path = self.save_dir / "experience_buffer.json"  # 经验缓冲区文件路径

        # 统计数据
        self.stats = {  # 初始化统计字典
            'total_experiences': 0,  # 总经验数
            'successful_predictions': 0,  # 成功预测数
            'failed_predictions': 0,  # 失败预测数
            'average_loss': 0.0  # 平均损失
        }

        # 训练统计（新增）
        self.training_stats = {  # 初始化训练统计
            'episodes': 0,  # episode数量
            'online_updates': 0,  # 在线更新次数
            'last_loss': 0.0,  # 最新损失
            'avg_error': 0.0,  # 平均预测误差
            'created_at': time.time()  # 创建时间
        }

        # MCTS规划器
        if use_mcts:  # 如果启用MCTS
            self.mcts_planner = MCTSPlanner(self, num_simulations=MCTSConfig.DEFAULT_SIMULATIONS, exploration_weight=1.0)  # 创建规划器
        else:  # 禁用MCTS
            self.mcts_planner = None  # 设为None

        # 加载已有模型
        self._load()  # 调用加载方法

        # 【P0修复】恢复后台训练为原生异步任务，用 asyncio.to_thread 隔离 PyTorch 计算
        if TORCH_AVAILABLE:
            try:
                self._train_task = asyncio.get_event_loop().create_task(self._train_loop_async())
            except RuntimeError:
                # 当前线程无事件循环时（如单元测试），跳过训练任务
                self._train_task = None
        else:
            self._train_task = None

        # ── 粒子滤波：多假设状态推断引擎 ──────────────────────────────────────
        from core.estimation.state_estimator import AsyncStateEstimator
        self._estimator_engine = AsyncStateEstimator(max_workers=2)
        self._estimator_engine.register(
            name='world_model_pf',
            estimator_type='frequency_aware_particle',
            num_particles=500,
            state_dim=self.state_dim,
            initial_state_sampler=lambda: np.random.randn(self.state_dim) * 0.1,
            spectral_window=100
        )
        logger.info(f"[WorldModel] 世界模型V2.0初始化完成，设备: {self.device}，粒子滤波已注册")

    # ==================== 核心接口 ====================

    async def observe_tool_execution(self, tool_id: str, params: dict,
                               perception_before: dict,
                               perception_after: dict,
                               result: dict,
                               task_context: dict = None):
        """
        观察工具执行，记录经验

        这是与底座集成的核心接口，由 tool_manager 在每次工具调用后调用
        """
        # 编码状态
        state = self.state_encoder.encode(perception_before, task_context)  # 编码执行前状态
        next_state = self.state_encoder.encode(perception_after, task_context)  # 编码执行后状态
        action = self.action_encoder.encode(tool_id, params)  # 编码动作

        # 计算奖励
        reward = self._calculate_reward(result)  # 根据结果计算奖励
        success = result.get('success', False)  # 获取成功标志
        done = task_context.get('task_completed', False) if task_context else False  # 获取完成标志

        # 元数据
        metadata = {  # 创建元数据字典
            'tool_id': tool_id,  # 工具ID
            'timestamp': time.time(),  # 时间戳
            'task_id': task_context.get('task_id') if task_context else None,  # 任务ID
            'weight': 2.0 if (task_context and task_context.get('is_exploratory')) else 1.0,
        }

        # 添加到缓冲区
        with self.lock:  # 获取锁，保证线程安全
            self.buffer.append((state, action, next_state, reward, success, done, metadata))  # 添加到经验池
            self.episode_buffer.append((state, action, next_state, reward, success, done))  # 添加到episode缓冲
            self.train_counter += 1  # 训练计数器+1
            self.stats['total_experiences'] += 1  # 总经验数+1

            # 如果任务完成，保存episode
            if task_context and task_context.get('task_completed'):  # 检查任务完成标志
                self._save_episode()  # 保存完整episode到记忆系统

        logger.debug(f"[WorldModel] 记录经验: {tool_id}, 奖励={reward:.2f}, 成功={success}")  # 记录调试日志

        # 在线学习更新
        if self.enable_learning:  # 如果启用在线学习
            self.online_update(state, action, next_state, reward, done)  # 执行在线更新

    def online_update(self, state: np.ndarray, action: np.ndarray,
                      next_state: np.ndarray, reward: float, done: bool) -> None:
        """
        在线学习：每次工具调用后更新模型

        Args:
            state: 当前状态表示
            action: 执行的动作
            next_state: 下一状态
            reward: 奖励信号（任务成功为1，失败为-1）
            done: 是否结束
        """
        if not self.enable_learning:  # 如果未启用学习
            return  # 直接返回

        try:  # 异常处理块
            # 转换为tensor
            state_t = torch.FloatTensor(state).unsqueeze(0).to(self.device)  # 状态转张量并添加批次维
            action_t = torch.FloatTensor(action).unsqueeze(0).to(self.device)  # 动作转张量
            next_state_t = torch.FloatTensor(next_state).unsqueeze(0).to(self.device)  # 下一状态转张量
            reward_t = torch.FloatTensor([reward]).unsqueeze(0).to(self.device)  # 奖励转张量
            done_t = torch.FloatTensor([float(done)]).unsqueeze(0).to(self.device)  # done转张量

            # 预测
            pred_next, pred_reward, pred_done = self.model(state_t, action_t)  # 模型前向传播

            # 计算损失
            state_loss = self.state_loss_fn(pred_next, next_state_t)  # 状态预测损失
            reward_loss = self.reward_loss_fn(pred_reward, reward_t)  # 奖励预测损失
            done_loss = self.done_loss_fn(pred_done, done_t)  # 完成标志预测损失

            # 对比损失
            contrastive_loss = self._contrastive_loss(pred_next, next_state_t)  # 计算对比学习损失

            total_loss = state_loss + reward_loss + done_loss + 0.1 * contrastive_loss  # 总损失（加权）

            # 反向传播
            self.optimizer.zero_grad()  # 清空梯度
            total_loss.backward()  # 反向传播计算梯度
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)  # 梯度裁剪，防止爆炸
            self.optimizer.step()  # 更新参数

            # 记录训练指标
            self.training_stats['online_updates'] += 1  # 在线更新次数+1
            self.training_stats['last_loss'] = total_loss.item()  # 记录最新损失

            # 更新平均误差
            with torch.no_grad():  # 不计算梯度
                error = torch.mean((pred_next - next_state_t) ** 2).item()  # 计算MSE误差
                self.training_stats['avg_error'] = 0.99 * self.training_stats['avg_error'] + 0.01 * error  # 指数移动平均

            logger.info(f"[WorldModel] 在线更新完成，损失: {total_loss.item():.4f}")  # 记录训练信息
        except Exception as e:  # 捕获异常
            logger.error(f"[WorldModel] 在线更新失败: {e}")  # 记录错误

    def _contrastive_loss(self, pred, target, temperature=0.1):
        """对比学习损失 - InfoNCE简化版"""
        # 计算相似度
        pred_norm = F.normalize(pred, dim=1)  # L2归一化预测值
        target_norm = F.normalize(target, dim=1)  # L2归一化目标值

        # 正样本相似度
        pos_sim = torch.sum(pred_norm * target_norm, dim=1) / temperature  # 计算余弦相似度除以温度

        # 对比损失（简化版InfoNCE）
        loss = -torch.mean(torch.log(torch.exp(pos_sim) / torch.sum(torch.exp(pos_sim))))  # 计算对比损失
        return loss  # 返回损失值

    def predict(self, state: dict | np.ndarray,
                action: str | np.ndarray) -> tuple[np.ndarray, float, bool]:
        """
        预测执行动作后的结果（简化接口）

        Args:
            state: 状态向量或感知字典
            action: 动作向量或动作ID

        Returns:
            (next_state, reward, done) - 预测的下一状态、奖励和完成标志
        """
        if not TORCH_AVAILABLE or self.model is None:
            return np.zeros(self.state_dim), 0.0, False
        # 如果是字典，先编码
        if isinstance(state, dict):  # 检查状态类型
            state = self.state_encoder.encode(state, None)  # 编码状态
        if isinstance(action, str):  # 检查动作类型
            action = self.action_encoder.encode(action, {})  # 编码动作

        with torch.no_grad():  # 不计算梯度
            state_t = torch.FloatTensor(state).unsqueeze(0).to(self.device)  # 转张量
            action_t = torch.FloatTensor(action).unsqueeze(0).to(self.device)  # 转张量

            pred_next, pred_reward, pred_done = self.model(state_t, action_t)  # 模型预测

            return (  # 返回numpy数组和标量值
                pred_next.cpu().numpy().squeeze(),  # 下一状态转为numpy数组
                pred_reward.cpu().item(),  # 奖励转为Python标量
                pred_done.cpu().item() > 0.5  # 完成概率转为布尔值
            )

    def predict_detailed(self, perception: dict, tool_id: str, params: dict,
                         task_context: dict = None) -> dict:
        """
        预测执行动作后的详细结果（新接口）

        Returns:
            {
                'next_state': 预测的下一状态向量,
                'success_prob': 预测的成功率 (0-1),
                'expected_reward': 预期奖励,
                'risk': 风险系数 (0-1),
                'confidence': 预测置信度 (0-1),
                'done_prob': 任务完成概率
            }
        """
        if not TORCH_AVAILABLE or self.model is None:
            return {
                'next_state': None,
                'success_prob': 0.5,
                'expected_reward': 0.0,
                'risk': 0.5,
                'confidence': 0.0,
                'done_prob': 0.5,
                'message': 'PyTorch 不可用，无法预测'
            }

        if len(self.buffer) < 10:  # 检查经验池大小
            return {  # 数据不足返回默认结果
                'next_state': None,
                'success_prob': 0.5,
                'expected_reward': 0.0,
                'risk': 0.5,
                'confidence': 0.0,
                'done_prob': 0.5,
                'message': '数据不足，无法预测'
            }

        state = self.state_encoder.encode(perception, task_context)  # 编码状态
        action = self.action_encoder.encode(tool_id, params)  # 编码动作

        with torch.no_grad():  # 不计算梯度
            state_t = torch.FloatTensor(state).unsqueeze(0).to(self.device)  # 转张量
            action_t = torch.FloatTensor(action).unsqueeze(0).to(self.device)  # 转张量

            pred_next, pred_reward, pred_done = self.model(state_t, action_t)  # 模型预测

            next_state = pred_next.cpu().numpy().squeeze()  # 下一状态
            expected_reward = pred_reward.cpu().item()  # 预期奖励
            done_prob = pred_done.cpu().item()  # 完成概率
            # success_prob与done_prob相关但有区别
            success_prob = 0.5 + 0.5 * torch.tanh(pred_reward).cpu().item()  # 使用tanh映射到0-1
            risk = 1 - done_prob  # 风险为完成的补数

        # 计算置信度（基于训练数据量）
        confidence = min(1.0, len(self.buffer) / 1000)  # 经验越多置信度越高，上限1.0

        return {  # 返回详细预测结果
            'next_state': next_state,
            'success_prob': success_prob,
            'expected_reward': expected_reward,
            'risk': risk,
            'confidence': confidence,
            'done_prob': done_prob
        }

    def imagine(self, perception: dict, action_sequence: list[tuple[str, dict]],
                task_context: dict = None) -> list[dict]:
        """
        想象执行一系列动作后的结果（反事实推理）

        Args:
            action_sequence: [(tool_id, params), ...] 动作序列

        Returns:
            每个步骤的预测结果列表
        """
        if len(self.buffer) < 10:  # 检查经验池大小
            return []  # 数据不足返回空列表

        results = []  # 初始化结果列表
        current_perception = perception.copy()  # 复制当前感知

        for tool_id, params in action_sequence:  # 遍历动作序列
            prediction = self.predict_detailed(current_perception, tool_id, params, task_context)  # 预测单步
            results.append({  # 添加结果
                'tool_id': tool_id,
                'prediction': prediction
            })

            # 更新当前状态
            if prediction['next_state'] is not None:  # 如果预测成功
                current_perception['_world_model_state'] = prediction['next_state']  # 更新状态

        return results  # 返回预测结果列表

    def evaluate_plan(self, perception: dict[str, Any],
                      plan: list[tuple[str, dict[str, Any]]],
                      task_context: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        评估一个行动计划的预期效果

        Returns:
            {
                'total_expected_reward': 总预期奖励,
                'success_probability': 整体成功概率,
                'risk_level': 风险等级,
                'recommendation': 建议文本
            }
        """
        imagined = self.imagine(perception, plan, task_context)  # 想象执行计划

        if not imagined:  # 如果没有想象结果
            return {  # 返回默认值
                'total_expected_reward': 0,
                'success_probability': 0.5,
                'risk_level': 'unknown',
                'recommendation': '数据不足，无法评估'
            }

        # 计算整体指标
        total_reward = sum(r['prediction']['expected_reward'] for r in imagined)  # 总奖励
        cumulative_success = 1.0  # 累计成功率
        for r in imagined:  # 遍历每一步
            cumulative_success *= r['prediction']['success_prob']  # 累积乘法

        avg_risk = sum(r['prediction']['risk'] for r in imagined) / len(imagined)  # 平均风险

        # 风险等级
        if avg_risk < 0.3:  # 低风险
            risk_level = 'low'
        elif avg_risk < 0.6:  # 中等风险
            risk_level = 'medium'
        else:  # 高风险
            risk_level = 'high'

        # 生成建议
        if cumulative_success > 0.8 and total_reward > 0:  # 高成功率高收益
            recommendation = "计划看起来可行，建议执行"
        elif cumulative_success < 0.3:  # 低成功率
            recommendation = "成功概率较低，建议调整计划"
        elif total_reward < 0:  # 负收益
            recommendation = "预期收益为负，建议重新考虑"
        else:  # 其他情况
            recommendation = "计划有风险，谨慎执行"

        return {  # 返回评估结果
            'total_expected_reward': total_reward,
            'success_probability': cumulative_success,
            'risk_level': risk_level,
            'step_predictions': imagined,
            'recommendation': recommendation
        }

    def get_prediction_for_prompt(self, perception: dict,
                                  proposed_tool: str,
                                  proposed_params: dict,
                                  task_context: dict = None) -> str:
        """
        获取世界模型预测，格式化为提示词片段

        这是与世界模型集成的核心接口，让AI能看到预测结果

        Returns:
            格式化的提示词文本
        """
        # 数据不足时返回空
        if len(self.buffer) < 10:  # 检查经验池大小
            return ""  # 数据不足返回空字符串

        try:  # 异常处理
            # 获取详细预测
            pred = self.predict_detailed(perception, proposed_tool, proposed_params, task_context)

            # 查找类似经验
            similar = self._find_similar_experiences(proposed_tool, limit=2)  # 查找2条类似经验

            # 格式化提示词
            lines = ["【世界模型预测】"]  # 初始化提示词列表

            # 成功率预测
            success_rate = pred['success_prob'] * 100  # 转为百分比
            if success_rate > 80:  # 高成功率
                lines.append(f"✅ 预测成功率: {success_rate:.0f}% (高)")
            elif success_rate > 50:  # 中等成功率
                lines.append(f"⚠️ 预测成功率: {success_rate:.0f}% (中)")
            else:  # 低成功率
                lines.append(f"❌ 预测成功率: {success_rate:.0f}% (低)")

            # 风险等级
            risk = pred['risk']
            if risk > 0.6:  # 高风险
                lines.append("🚨 风险等级: 高")
            elif risk > 0.3:  # 中等风险
                lines.append("⚡ 风险等级: 中")

            # 置信度
            conf = pred['confidence'] * 100  # 转为百分比
            if conf < 30:  # 低置信度
                lines.append(f"📊 置信度: {conf:.0f}% (样本不足)")

            # 类似经验
            if similar:  # 如果存在类似经验
                lines.append("")  # 空行
                lines.append("【相关经验】")  # 标题
                for i, exp in enumerate(similar, 1):  # 遍历经验
                    status = "✓" if exp.get('success') else "✗"  # 成功/失败标记
                    tool = exp.get('tool_id', 'unknown')  # 工具ID
                    lines.append(f"  {i}. [{status}] {tool}")  # 格式化经验

            return "\n".join(lines)  # 用换行符连接所有行

        except Exception as e:  # 捕获异常
            logger.debug(f"[WorldModel] 生成预测提示词失败: {e}")  # 记录调试日志
            return ""  # 返回空字符串

    def get_prediction_dict(self, perception: dict,
                           proposed_tool: str,
                           proposed_params: dict,
                           task_context: dict = None) -> dict:
        """
        获取世界模型预测，返回结构化数据

        Returns:
            {
                "confidence": 85,  # 成功率百分比
                "suggestion": "建议先备份文件再操作",
                "risk": "可能覆盖现有文件",
                "similar_tasks": 3  # 相似任务数量
            }
            如果数据不足或出错，返回空字典
        """
        # 数据不足时返回空
        if len(self.buffer) < 10:  # 检查经验池大小
            return {}  # 返回空字典

        try:  # 异常处理
            # 获取详细预测
            pred = self.predict_detailed(perception, proposed_tool, proposed_params, task_context)

            # 查找类似经验
            similar = self._find_similar_experiences(proposed_tool, limit=10)  # 查找10条类似经验

            # 构建结构化数据
            confidence = int(pred.get('success_prob', 0.5) * 100)  # 成功率转百分比整数
            risk_score = pred.get('risk', 0.5)  # 获取风险分数

            # 根据风险等级生成建议
            if risk_score > 0.6:  # 高风险
                suggestion = "风险较高，建议先备份数据或寻找替代方案"
            elif risk_score > 0.3:  # 中等风险
                suggestion = "操作需谨慎，建议确认参数正确"
            elif confidence > 80:  # 高成功率
                suggestion = "历史成功率较高，可以执行"
            elif confidence > 50:  # 中等成功率
                suggestion = "建议先测试小规模操作"
            else:  # 低成功率
                suggestion = "历史成功率较低，建议寻找替代方案"

            # 生成风险提示
            if risk_score > 0.6:  # 高风险
                risk_text = "高风险操作，可能导致数据丢失或系统异常"
            elif risk_score > 0.3:  # 中等风险
                risk_text = "中等风险，需要注意操作细节"
            else:  # 低风险
                risk_text = "低风险操作"

            return {  # 返回结构化数据
                "confidence": confidence,
                "suggestion": suggestion,
                "risk": risk_text,
                "similar_tasks": len(similar)  # 相似任务数量
            }

        except Exception as e:  # 捕获异常
            logger.debug(f"[WorldModel] 生成预测数据失败: {e}")  # 记录调试日志
            return {}  # 返回空字典

    def _find_similar_experiences(self, tool_id: str, limit: int = 3) -> list[dict]:
        """查找类似工具的经验"""
        similar = []  # 初始化相似经验列表
        with self.lock:  # 获取锁
            # 从buffer中找相同工具的经验
            for exp in reversed(self.buffer):  # 倒序遍历（最新的优先）
                if len(similar) >= limit:  # 达到限制数量
                    break  # 退出循环
                metadata = exp[6] if len(exp) > 6 else {}  # 获取元数据
                if metadata.get('tool_id') == tool_id:  # 工具ID匹配
                    similar.append({  # 添加到列表
                        'tool_id': tool_id,
                        'success': exp[4],  # success flag
                        'reward': exp[3],   # reward
                    })
        return similar  # 返回相似经验列表

    def suggest_action(self, current_state: dict | np.ndarray,
                       available_tools: list[str],
                       use_mcts: bool = True,
                       horizon: int = 5) -> dict[str, Any] | None:
        """
        基于世界模型建议下一步动作

        Args:
            current_state: 当前状态表示（感知字典或状态向量）
            available_tools: 可用工具列表
            use_mcts: 是否使用MCTS规划
            horizon: 规划horizon
        """
        if not self.model:  # 检查模型是否存在
            return None  # 无模型返回None

        # 将感知编码为状态向量（如果需要）
        if isinstance(current_state, dict):  # 如果是字典
            state_vector = self.state_encoder.encode(current_state, None)  # 编码状态
        else:  # 已是向量
            state_vector = current_state  # 直接使用

        if use_mcts and self.mcts_planner and len(self.buffer) >= 10:  # 使用MCTS条件（降级激活）
            # 使用MCTS规划
            plan_result = self.mcts_planner.plan(
                state_vector,
                available_tools,
                horizon=horizon
            )
            return {  # 返回MCTS规划结果
                'type': 'mcts_plan',
                'best_action': plan_result['best_action'],
                'action_sequence': plan_result['action_sequence'],
                'confidence': min(plan_result['expected_value'], 1.0),
                'alternatives': list(plan_result['visit_counts'].keys())[:3]
            }
        else:  # 简单预测逻辑
            if len(self.buffer) < 100 or not available_tools:  # 检查条件
                return None  # 条件不足返回None

            best_tool = None  # 初始化最佳工具
            best_score = -float('inf')  # 初始化最佳分数

            for tool_id in available_tools[:5]:  # 只评估前5个工具
                action = self.action_encoder.encode(tool_id, {})  # 编码动作
                with torch.no_grad():  # 不计算梯度
                    state_t = torch.FloatTensor(state_vector).unsqueeze(0).to(self.device)  # 转张量
                    action_t = torch.FloatTensor(action).unsqueeze(0).to(self.device)  # 转张量
                    pred_next, pred_reward, pred_done = self.model(state_t, action_t)  # 预测

                    success_prob = 0.5 + 0.5 * torch.tanh(pred_reward).cpu().item()  # 成功率
                    risk = 1 - pred_done.cpu().item()  # 风险
                    expected_reward = pred_reward.cpu().item()  # 预期奖励
                    score = success_prob - risk + expected_reward  # 综合分数

                if score > best_score:  # 如果分数更高
                    best_score = score  # 更新最佳分数
                    best_tool = tool_id  # 更新最佳工具

            if best_tool:  # 如果找到最佳工具
                return {  # 返回建议
                    'type': 'simple',
                    'best_action': best_tool,
                    'score': best_score,
                    'reason': f"基于历史经验，{best_tool} 在当前状态下成功率较高"
                }
            return None  # 未找到返回None

    def get_training_stats(self) -> dict:
        """获取训练统计信息"""
        return {  # 返回训练统计字典
            'total_episodes': self.training_stats.get('episodes', 0),  # 总episodes
            'online_updates': self.training_stats.get('online_updates', 0),  # 在线更新次数
            'last_loss': self.training_stats.get('last_loss', 0),  # 最新损失
            'avg_prediction_error': self.training_stats.get('avg_error', 0),  # 平均预测误差
            'model_age_hours': (time.time() - self.training_stats.get('created_at', time.time())) / 3600,  # 模型年龄（小时）
            'buffer_size': len(self.buffer),  # 经验池大小
            'total_experiences': self.stats['total_experiences']  # 总经验数
        }

    def get_prediction_accuracy(self, test_data: list[tuple]) -> float:
        """计算预测准确率"""
        if not test_data:  # 检查测试数据
            return 0.0  # 无数据返回0

        correct = 0  # 正确计数
        total = 0  # 总计数

        with torch.no_grad():  # 不计算梯度
            for state, action, next_state in test_data:  # 遍历测试数据
                state_t = torch.FloatTensor(state).unsqueeze(0).to(self.device)  # 转张量
                action_t = torch.FloatTensor(action).unsqueeze(0).to(self.device)  # 转张量
                next_state_t = torch.FloatTensor(next_state).unsqueeze(0).to(self.device)  # 转张量

                pred_next, _, _ = self.model(state_t, action_t)  # 预测
                error = torch.mean((pred_next - next_state_t) ** 2).item()  # 计算MSE误差
                if error < 0.1:  # 阈值0.1
                    correct += 1  # 正确+1
                total += 1  # 总计+1

        return correct / total if total > 0 else 0.0  # 返回准确率

    # ==================== 训练与保存 ====================

    async def _train_loop_async(self):
        """后台训练异步任务 - 持续训练模型（PyTorch 计算用 to_thread 隔离）"""
        # 【修复】添加连续错误计数器
        consecutive_errors = 0  # 连续错误计数
        max_consecutive_errors = 5  # 最大允许连续错误数

        while self.running:  # 当运行标志为True
            try:  # 异常处理
                await asyncio.sleep(2)  # 休眠2秒（协程安全）
                if self.train_counter >= self.train_interval:  # 检查是否达到训练间隔
                    # PyTorch 计算放入线程池，不阻塞事件循环
                    loss = await asyncio.to_thread(self._train_step)
                    self.train_counter = 0  # 重置计数器
                    self.step_count += 1  # 步数+1
                    # 【修复】成功执行后重置错误计数器
                    consecutive_errors = 0  # 重置错误计数

                    # 定期保存（文件 I/O 同样隔离到线程池）
                    if self.step_count % 100 == 0:  # 每100步
                        await asyncio.to_thread(self._save)
                        logger.info(f"[WorldModel] 已训练 {self.step_count} 步，最新loss: {loss:.4f}")  # 记录日志
            except Exception as e:  # 捕获异常
                # 【修复】异常保护：记录错误并增加计数器
                consecutive_errors += 1  # 错误计数+1
                logger.error(f"[WorldModel] 训练循环异常 ({consecutive_errors}/{max_consecutive_errors}): {e}")  # 记录错误

                # 【修复】连续错误过多时暂停训练
                if consecutive_errors >= max_consecutive_errors:  # 检查是否超过最大错误数
                    logger.critical("[WorldModel] 连续错误过多，暂停训练循环")  # 记录严重错误
                    self.running = False  # 停止运行
                    break  # 退出循环

                # 【修复】异常后休眠5秒避免CPU占满
                await asyncio.sleep(5)  # 休眠5秒（协程安全）

    def _train_step(self) -> float:
        """训练一步 - 从经验池采样并更新模型"""
        with self.lock:  # 获取锁
            if len(self.buffer) < self.batch_size:  # 检查经验池大小
                return 0.0  # 不足返回0

            # 随机采样
            indices = np.random.choice(len(self.buffer), self.batch_size, replace=False)  # 随机选择索引
            batch = [self.buffer[i] for i in indices]  # 获取批次数据
            states, actions, next_states, rewards, successes, dones, metadatas = zip(*batch, strict=False)  # 解包数据

            # 转为张量并移动到设备
            states = torch.FloatTensor(np.array(states)).to(self.device)
            actions = torch.FloatTensor(np.array(actions)).to(self.device)
            next_states = torch.FloatTensor(np.array(next_states)).to(self.device)
            rewards_t = torch.FloatTensor(rewards).unsqueeze(1).to(self.device)
            dones_t = torch.FloatTensor([float(d) for d in dones]).unsqueeze(1).to(self.device)
            weights_t = torch.FloatTensor([m.get('weight', 1.0) for m in metadatas]).unsqueeze(1).to(self.device)

        # 前向传播
        self.optimizer.zero_grad()  # 清空梯度
        pred_next_states, pred_rewards, pred_dones = self.model(states, actions)  # 模型预测

        # 计算损失（探索性数据加权）
        state_loss = ((pred_next_states - next_states) ** 2 * weights_t).mean()  # 状态损失
        reward_loss = ((pred_rewards - rewards_t) ** 2 * weights_t).mean()  # 奖励损失
        done_loss = (F.binary_cross_entropy(pred_dones, dones_t, reduction='none') * weights_t).mean()  # 完成标志损失

        # 总损失
        loss = state_loss + 0.5 * reward_loss + 0.3 * done_loss  # 加权总损失

        # 反向传播
        loss.backward()  # 计算梯度
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)  # 梯度裁剪
        self.optimizer.step()  # 更新参数

        # 更新学习率
        self.scheduler.step()  # 学习率调度

        self.stats['average_loss'] = 0.99 * self.stats['average_loss'] + 0.01 * loss.item()  # 更新平均损失

        return loss.item()  # 返回损失值

    def _calculate_reward(self, result: dict) -> float:
        """计算奖励值 - 根据执行结果计算"""
        if result.get('success'):  # 如果成功
            return 1.0  # 返回正奖励
        elif result.get('error_code'):  # 如果有错误码
            return -0.5  # 返回负奖励
        else:  # 其他情况
            return 0.0  # 返回0

    async def _save_episode_async(self):
        """保存完整的episode到长期记忆"""
        if not self.episode_buffer:  # 检查episode缓冲区
            return  # 为空直接返回

        # 计算episode统计
        rewards = [e[4] for e in self.episode_buffer]  # 提取奖励
        dones = [e[5] for e in self.episode_buffer]  # 提取完成标志

        episode_data = {  # 构建episode数据
            'timestamp': time.time(),  # 时间戳
            'steps': len(self.episode_buffer),  # 步数
            'total_reward': sum(rewards),  # 总奖励
            'completed': any(dones),  # 是否完成
        }

        # 保存到记忆系统
        try:
            ms = await get_memory_service()
            await ms.add_memory(
                user_id="default",
                content=json.dumps(episode_data),
                memory_type="world_model_episode",
                layer="evolve",
                scene="world_model",
                rating=int(episode_data['total_reward'] > 0),
                source=MemorySource.EVOLUTION
            )
        except Exception as e:
            logger.error(f"保存episode失败: {e}")

        # 清空episode缓冲区
        self.episode_buffer = []  # 重置为空列表

        # 更新训练统计
        self.training_stats['episodes'] += 1  # episode数+1

    def _save_episode(self):
        """同步入口：调度异步保存episode"""
        try:
            loop = asyncio.get_event_loop()
            asyncio.run_coroutine_threadsafe(self._save_episode_async(), loop)
        except Exception as e:
            logger.error(f"调度保存episode失败: {e}")

    def _save(self):
        """保存模型和缓冲区"""
        if not TORCH_AVAILABLE or self.model is None:
            return
        try:  # 异常处理
            # 保存模型状态
            torch.save({  # 保存字典
                'model': self.model.state_dict(),  # 模型参数
                'optimizer': self.optimizer.state_dict(),  # 优化器状态
                'stats': self.stats,  # 统计数据
                'training_stats': self.training_stats,  # 训练统计
                'step_count': self.step_count  # 训练步数
            }, self.model_path)  # 保存路径

            # 保存经验缓冲区（只保存最近1000条）- 使用JSON替代pickle提高安全性
            import json  # 导入json
            with open(self.buffer_path, 'w', encoding='utf-8') as f:  # 打开文件写入
                json.dump(list(self.buffer)[-1000:], f, ensure_ascii=False, indent=2)  # 保存最近1000条

            logger.debug("[WorldModel] 世界模型已保存")  # 记录调试日志
        except Exception as e:  # 捕获异常
            logger.error(f"保存世界模型失败: {e}")  # 记录错误

    def _load(self):
        """加载模型和缓冲区"""
        if not TORCH_AVAILABLE or self.model is None:
            return
        if self.model_path.exists():  # 检查模型文件是否存在
            try:  # 异常处理
                checkpoint = torch.load(self.model_path, map_location=self.device)  # 加载检查点
                self.model.load_state_dict(checkpoint['model'])  # 加载模型参数
                self.optimizer.load_state_dict(checkpoint['optimizer'])  # 加载优化器状态
                self.stats = checkpoint.get('stats', self.stats)  # 加载统计
                self.training_stats = checkpoint.get('training_stats', self.training_stats)  # 加载训练统计
                self.step_count = checkpoint.get('step_count', 0)  # 加载步数
                logger.info(f"[WorldModel] 已加载世界模型，已训练 {self.step_count} 步")  # 记录日志
            except Exception as e:  # 捕获异常
                logger.error(f"加载世界模型失败: {e}")  # 记录错误

        if self.buffer_path.exists():  # 检查缓冲区文件是否存在
            try:  # 异常处理
                import json  # 导入json
                with open(self.buffer_path, encoding='utf-8') as f:  # 打开文件读取
                    loaded_buffer = json.load(f)  # 加载JSON
                    self.buffer.extend(loaded_buffer)  # 扩展到经验池
                logger.info(f"[WorldModel] 已加载 {len(self.buffer)} 条经验")  # 记录日志
            except Exception as e:  # 捕获异常
                logger.error(f"加载经验缓冲区失败: {e}")  # 记录错误

    async def stop_async(self):
        """停止训练任务并保存（异步版本）"""
        self.running = False  # 设置运行标志为False
        if self._train_task is not None:
            self._train_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._train_task
        await asyncio.to_thread(self._save)  # 保存模型（文件 I/O 隔离到线程池）

    def stop(self):
        """停止训练任务并保存（同步兼容入口）"""
        self.running = False
        if self._train_task is not None:
            self._train_task.cancel()
        self._save()  # 同步保存
        self._save_episode()  # 保存episode
        logger.info("[WorldModel] 世界模型已停止并保存")  # 记录日志

    async def record_observation(self, tool_id: str, params: dict, result: dict,
                           source: str = "user", duration: float = 0,
                           context: dict = None):
        """
        简化接口：记录工具执行观察（异步化）

        由 ToolManager 在每次工具调用后调用
        """
        try:  # 异常处理
            # 构建简化的感知数据
            perception_before = {  # 执行前感知
                'windows': context.get('active_windows', []) if context else [],  # 活动窗口
                'processes': [],  # 进程列表（简化）
                'cpu_percent': 50.0,  # CPU使用率（默认值）
                'memory_percent': 50.0  # 内存使用率（默认值）
            }

            perception_after = {  # 执行后感知
                'windows': context.get('active_windows', []) if context else [],  # 活动窗口
                'processes': [],  # 进程列表
                'cpu_percent': 50.0,  # CPU使用率
                'memory_percent': 50.0,  # 内存使用率
                'last_tool_result': result  # 最后工具结果
            }

            task_context = {  # 任务上下文
                'task_id': context.get('task_id') if context else None,  # 任务ID
                'tool_sequence': [tool_id],  # 工具序列
                'current_tool': tool_id,  # 当前工具
                'is_exploratory': context.get('is_exploratory', False) if context else False,
            }

            # 调用原有的观察方法
            await self.observe_tool_execution(
                tool_id=tool_id,
                params=params,
                perception_before=perception_before,
                perception_after=perception_after,
                result=result,
                task_context=task_context
            )
        except Exception as e:  # 捕获异常
            logger.debug(f"记录观察失败: {e}")  # 记录调试日志

    def get_stats(self) -> dict:
        """获取统计信息（向后兼容）"""
        return {  # 返回统计字典
            **self.stats,  # 展开基础统计
            'buffer_size': len(self.buffer),  # 经验池大小
            'device': str(self.device),  # 计算设备
            'learning_rate': self.optimizer.param_groups[0]['lr']  # 当前学习率
        }

    # ── 粒子滤波：多假设状态预测 ──────────────────────────────────────────────
    async def predict_with_particles(self, current_state: dict,
                                     available_tools: list[str],
                                     num_scenarios: int = 3) -> dict:
        """
        基于粒子滤波的多假设状态预测。

        返回状态估计、不确定性、前 N 种可能场景。
        用于替代纯经验攒够逻辑，提供概率化决策支持。
        """
        if not self._estimator_engine.has('world_model_pf'):
            return {
                'estimated_state': None,
                'uncertainty': 1.0,
                'scenarios': [],
                'message': '粒子滤波未注册'
            }

        try:
            # 编码当前状态为观测向量
            state_vector = self.state_encoder.encode(current_state, {})

            # 更新频谱模型（直接操作实例，无需线程池）
            pf = self._estimator_engine.get('world_model_pf')
            if hasattr(pf, 'update_spectral_model'):
                pf.update_spectral_model(state_vector)

            # 似然：基于当前状态与粒子距离的指数衰减
            def _likelihood_fn(particle, observation):
                diff = particle - observation
                dist_sq = np.sum(diff ** 2)
                return np.exp(-0.5 * dist_sq / (self.state_dim * 0.1))

            # 执行 predict-update 循环（predict 已由 FrequencyAwareParticleFilter 覆盖为频谱转移）
            await self._estimator_engine.predict_async(
                'world_model_pf',
                A_or_transition=None,
                Q_or_process_noise=np.eye(self.state_dim) * 0.01
            )
            result = await self._estimator_engine.update_async(
                'world_model_pf',
                observation=state_vector,
                H_or_observation_fn=_likelihood_fn,
                R_or_observation_noise=np.eye(self.state_dim) * 0.1
            )

            # 反思驱动修正（示例：根据最近历史误差调整高权重粒子）
            correction_hint = None
            if hasattr(self, '_recent_prediction_errors') and self._recent_prediction_errors:
                avg_err = np.mean(self._recent_prediction_errors[-5:])
                if avg_err > 0.2:
                    correction_hint = {
                        'bias_direction': -np.sign(np.mean(self._recent_prediction_errors[-3:])),
                        'bias_magnitude': 0.02
                    }

            # 重采样（含反思修正）
            def _resample():
                pf_local = self._estimator_engine.get('world_model_pf')
                pf_local.resample(method='residual', correction_hint=correction_hint)
                if hasattr(self, '_recent_prediction_errors') and len(self._recent_prediction_errors) >= 5:
                    pf_local.adjust_particle_count(self._recent_prediction_errors)
            import asyncio
            await asyncio.to_thread(_resample)

            # 获取完整粒子分布
            full_result = await self._estimator_engine.get_state_async('world_model_pf')
            particles = full_result.get('particles')
            weights = full_result.get('weights')

            # 提取前 N 种高权重场景（按权重聚类）
            scenarios = []
            if particles is not None and weights is not None:
                # 简单策略：取权重最高的 num_scenarios 个粒子作为代表性场景
                top_indices = np.argsort(weights)[::-1][:num_scenarios]
                for idx in top_indices:
                    scenarios.append({
                        'state_vector': particles[:, idx].tolist(),
                        'weight': float(weights[idx]),
                        'tool_hint': available_tools[idx % len(available_tools)] if available_tools else None
                    })

            estimated_state = result.get('state')
            uncertainty = float(np.trace(result.get('covariance', np.eye(self.state_dim))))

            return {
                'estimated_state': estimated_state.flatten().tolist() if estimated_state is not None else None,
                'uncertainty': uncertainty,
                'scenarios': scenarios,
                'neff': full_result.get('neff', 0.0),
                'message': f'粒子滤波预测完成，有效粒子数: {full_result.get("neff", 0):.1f}'
            }
        except Exception as e:
            logger.error(f"[WorldModel] 粒子滤波预测失败: {e}", exc_info=True)
            return {
                'estimated_state': None,
                'uncertainty': 1.0,
                'scenarios': [],
                'message': f'粒子滤波预测出错: {str(e)}'
            }

    # ==================== P0断裂点#1修复：AgentLoop核心集成接口 ====================

    async def predict_action_outcomes(self, current_state: dict, proposed_actions: list[dict]) -> dict:
        """
        预测多个行动的后果（P0断裂点#1修复核心接口）

        Args:
            current_state: 当前状态（来自working_memory.get_context()）
            proposed_actions: 提议的行动列表，每项包含tool_id和params

        Returns:
            {
                'predictions': [
                    {
                        'tool_id': str,
                        'params': Dict,
                        'success_prob': float,  # 成功率 0-1
                        'risk': float,  # 风险 0-1
                        'expected_reward': float,
                        'confidence': float,  # 置信度
                        'recommendation': str  # 建议文本
                    },
                    ...
                ],
                'best_action_index': int,  # 最佳行动索引
                'overall_risk': float  # 整体风险
            }
        """
        if len(self.buffer) < 10:  # 数据不足
            return {
                'predictions': [],
                'best_action_index': -1,
                'overall_risk': 0.5,
                'message': '数据不足，无法预测'
            }

        predictions = []
        best_index = 0
        best_score = -float('inf')
        max_risk = 0.0

        for idx, action in enumerate(proposed_actions):
            tool_id = action.get('tool_id', '')
            params = action.get('params', {})

            # 获取详细预测（PyTorch 计算隔离到线程池，不阻塞事件循环）
            pred = await asyncio.to_thread(
                self.predict_detailed, current_state, tool_id, params
            )

            # 计算综合分数（成功率 - 风险 + 奖励）
            score = pred['success_prob'] - pred['risk'] + pred['expected_reward']

            # 生成建议文本
            if pred['success_prob'] > 0.8 and pred['risk'] < 0.3:
                recommendation = "✅ 推荐执行"
            elif pred['risk'] > 0.7:
                recommendation = "🚨 高风险，建议验证"
            elif pred['success_prob'] < 0.3:
                recommendation = "❌ 成功率低，建议替代方案"
            else:
                recommendation = "⚠️ 谨慎执行"

            prediction = {
                'tool_id': tool_id,
                'params': params,
                'success_prob': pred['success_prob'],
                'risk': pred['risk'],
                'expected_reward': pred['expected_reward'],
                'confidence': pred['confidence'],
                'recommendation': recommendation
            }
            predictions.append(prediction)

            # 更新最佳行动
            if score > best_score:
                best_score = score
                best_index = idx

            # 更新最大风险
            max_risk = max(max_risk, pred['risk'])

        result = {
            'predictions': predictions,
            'best_action_index': best_index,
            'overall_risk': max_risk,
            'message': f'分析了{len(predictions)}个行动的预测结果'
        }
        # 【ExperienceBus】世界模型预测事件
        with contextlib.suppress(Exception):
            event_bus.emit("world_model:predicted", {
                "num_actions": len(predictions),
                "best_index": best_index,
                "overall_risk": max_risk,
                "timestamp": time.time(),
            })
        return result

    async def mcts_plan(self, current_state: dict, goal: str = None, iterations: int = 100) -> dict:
        """
        使用MCTS规划最优路径（P0断裂点#1修复核心接口）

        Args:
            current_state: 当前状态（来自working_memory.get_context()）
            goal: 目标描述
            iterations: MCTS模拟次数，默认100

        Returns:
            {
                'optimal_path': List[Dict],  # 最优行动序列
                'path_description': str,  # 路径描述文本
                'expected_success': float,  # 预期成功率
                'total_risk': float,  # 累积风险
                'alternatives': List[Dict]  # 替代路径
            }
        """
        # 检查MCTS是否可用
        if not self.use_mcts or self.mcts_planner is None:
            return {
                'optimal_path': [],
                'path_description': 'MCTS规划器未启用',
                'expected_success': 0.5,
                'total_risk': 0.5,
                'alternatives': []
            }

        # 检查数据量是否足够
        if len(self.buffer) < 10:
            return {
                'optimal_path': [],
                'path_description': '经验数据不足，需要至少10条经验才能进行MCTS规划',
                'expected_success': 0.5,
                'total_risk': 0.5,
                'alternatives': []
            }

        try:
            # 编码当前状态
            state_vector = self.state_encoder.encode(current_state, {'goal': goal})

            # 获取可用工具列表（从历史经验中推断）
            available_tools = self._get_available_tools_from_experience()

            if not available_tools:
                return {
                    'optimal_path': [],
                    'path_description': '无法获取可用工具列表',
                    'expected_success': 0.5,
                    'total_risk': 0.5,
                    'alternatives': []
                }

            # 设置MCTS模拟次数
            original_simulations = self.mcts_planner.num_simulations
            self.mcts_planner.num_simulations = iterations

            # 执行MCTS规划（CPU 密集型模拟隔离到线程池，不阻塞事件循环）
            plan_result = await asyncio.to_thread(
                self.mcts_planner.plan,
                initial_state=state_vector,
                available_actions=available_tools,
                horizon=5  # 规划5步
            )

            # 恢复原始模拟次数
            self.mcts_planner.num_simulations = original_simulations

            # 构建最优路径
            optimal_path = []
            for action in plan_result['action_sequence']:
                optimal_path.append({
                    'tool_id': action,
                    'purpose': f'向目标"{goal}"推进' if goal else '执行最优行动'
                })

            # 生成路径描述
            if optimal_path:
                path_desc = f"MCTS规划最优路径（{iterations}次模拟）：\n"
                for i, step in enumerate(optimal_path[:5], 1):  # 最多显示5步
                    path_desc += f"  第{i}步: {step['tool_id']}\n"
                if len(optimal_path) > 5:
                    path_desc += f"  ... 共{len(optimal_path)}步"
            else:
                path_desc = "MCTS未能规划出有效路径"

            # 计算预期成功率和总风险
            expected_success = min(plan_result['expected_value'], 1.0) if plan_result.get('expected_value') else 0.5
            total_risk = 1.0 - expected_success

            # 构建替代路径（从visit_counts中选择）
            alternatives = []
            sorted_actions = sorted(
                plan_result['visit_counts'].items(),
                key=lambda x: x[1],
                reverse=True
            )[1:4]  # 排除最佳，取2-4名

            for action, visits in sorted_actions:
                alternatives.append({
                    'tool_id': action,
                    'visit_count': visits,
                    'expected_value': plan_result.get('expected_value', 0)
                })

            result = {
                'optimal_path': optimal_path,
                'path_description': path_desc,
                'expected_success': expected_success,
                'total_risk': total_risk,
                'alternatives': alternatives,
                'mcts_iterations': iterations
            }
            # 【ExperienceBus】MCTS 规划事件
            with contextlib.suppress(Exception):
                event_bus.emit("world_model:mcts_planned", {
                    "expected_success": expected_success,
                    "total_risk": total_risk,
                    "path_length": len(optimal_path),
                    "iterations": iterations,
                    "timestamp": time.time(),
                })
            return result

        except Exception as e:
            logger.error(f"[WorldModel] MCTS规划失败: {e}")
            # 【ExperienceBus】MCTS 失败事件
            with contextlib.suppress(Exception):
                event_bus.emit("world_model:mcts_planned", {
                    "expected_success": 0.0,
                    "total_risk": 1.0,
                    "error": str(e),
                    "timestamp": time.time(),
                })
            return {
                'optimal_path': [],
                'path_description': f'MCTS规划出错: {str(e)}',
                'expected_success': 0.5,
                'total_risk': 0.5,
                'alternatives': []
            }

    def _get_available_tools_from_experience(self) -> list[str]:
        """从历史经验中提取可用工具列表"""
        tools = set()
        with self.lock:
            for exp in reversed(self.buffer):
                if len(tools) >= 20:  # 最多取20个工具
                    break
                metadata = exp[6] if len(exp) > 6 else {}
                tool_id = metadata.get('tool_id')
                if tool_id:
                    tools.add(tool_id)
        return list(tools)

    def get_state_importance(self, state: dict) -> float:
        """
        评估状态重要性（P0断裂点#1修复核心接口）

        Args:
            state: 状态字典

        Returns:
            重要性分数 0-1
        """
        importance = 0.0

        # 1. 检查是否有活跃任务
        if state.get('task_context', {}).get('goal'):
            importance += 0.3

        # 2. 检查是否有工具在执行
        if state.get('current_tool'):
            importance += 0.3

        # 3. 检查是否有错误状态
        recent_results = state.get('recent_results', [])
        if recent_results and not recent_results[-1]:
            importance += 0.2  # 最近有失败，重要性增加

        # 4. 检查是否是新会话
        if state.get('session_age', 0) < 60:  # 会话开始1分钟内
            importance += 0.2

        return min(importance, 1.0)

    def format_world_model_section(self, predictions: dict, best_path: dict, working_memory) -> str:
        """
        格式化世界模型输出为提示词片段（P0断裂点#1修复核心接口）

        Args:
            predictions: predict_action_outcomes的输出
            best_path: mcts_plan的输出
            working_memory: 工作记忆对象

        Returns:
            格式化的提示词文本
        """
        lines = []

        # 行动后果预测
        if predictions.get('predictions'):
            lines.append("【工具成功率预测】")
            for _i, pred in enumerate(predictions['predictions'][:3], 1):
                lines.append(f"  {pred['tool_id']}: 成功率{pred['success_prob']*100:.0f}% 风险{pred['risk']*100:.0f}%")

            best_idx = predictions.get('best_action_index', -1)
            if best_idx >= 0 and best_idx < len(predictions['predictions']):
                best = predictions['predictions'][best_idx]
                lines.append(f"  推荐: {best['tool_id']}")

        # MCTS规划路径
        if best_path.get('optimal_path'):
            lines.append(f"【规划路径】{best_path['path_description']}")

        # 高风险警告
        overall_risk = predictions.get('overall_risk', 0)
        if overall_risk > 0.7:
            lines.append("[高风险] 预测风险>70%，先验证再执行")
        elif overall_risk > 0.4:
            lines.append(f"[中度风险] 预测风险{overall_risk*100:.0f}%，谨慎执行")

        if lines:
            return "【世界模型预测】\n" + "\n".join(lines)
        return ""


# 单例模式
_world_model_instance = None  # 全局单例实例

def get_world_model() -> WorldModel:
    """获取世界模型单例"""
    global _world_model_instance  # 声明使用全局变量
    if _world_model_instance is None:  # 检查是否已创建
        _world_model_instance = WorldModel()  # 创建实例
    return _world_model_instance  # 返回实例


# ═══════════════════════════════════════════════════════════════════════════════
# P0断裂点#1修复：世界模型管理器 - 供AgentLoop使用
# ═══════════════════════════════════════════════════════════════════════════════

class WorldModelManager:
    """
    世界模型管理器 - AgentLoop的核心决策支持接口

    将世界模型功能封装为AgentLoop易于使用的形式，
    确保世界模型成为每轮决策的核心输入。
    """

    def __init__(self):
        self.world_model = get_world_model()
        self._last_predictions = None
        self._last_plan = None
        self._last_state_hash = None
        self._cache_ttl = 5.0  # 缓存有效期5秒
        self._last_update_time = 0

    async def predict_action_outcomes(self, current_state: dict, proposed_actions: list[dict]) -> dict:
        """
        预测多个行动的后果

        Args:
            current_state: 当前状态
            proposed_actions: 提议的行动列表

        Returns:
            预测结果字典
        """
        return await self.world_model.predict_action_outcomes(current_state, proposed_actions)

    async def mcts_plan(self, current_state: dict, goal: str = None, iterations: int = 100) -> dict:
        """
        使用MCTS规划最优路径

        Args:
            current_state: 当前状态
            goal: 目标描述
            iterations: MCTS模拟次数

        Returns:
            规划结果字典
        """
        return await self.world_model.mcts_plan(current_state, goal, iterations)

    def get_state_importance(self, state: dict) -> float:
        """
        评估状态重要性

        Args:
            state: 状态字典

        Returns:
            重要性分数 0-1
        """
        return self.world_model.get_state_importance(state)

    async def get_prediction_for_decision(self, working_memory, planned_tools: list[dict] = None) -> str:
        """
        为AgentLoop决策生成世界模型预测提示词（核心接口）

        Args:
            working_memory: 工作记忆对象
            planned_tools: 计划使用的工具列表

        Returns:
            格式化的提示词文本
        """
        # 构建当前状态
        current_state = self._build_state_from_working_memory(working_memory)

        # 获取目标
        goal = None
        if hasattr(working_memory, 'goal'):
            goal = working_memory.goal
        elif hasattr(working_memory, 'user_intent_snapshot'):
            goal = working_memory.user_intent_snapshot

        # 1. 获取行动后果预测
        predictions = {}
        if planned_tools:
            predictions = await self.predict_action_outcomes(current_state, planned_tools)
            self._last_predictions = predictions

        # 2. 获取MCTS规划路径
        best_path = await self.mcts_plan(current_state, goal, iterations=100)
        self._last_plan = best_path

        # 3. 格式化输出
        return self.world_model.format_world_model_section(predictions, best_path, working_memory)

    def _build_state_from_working_memory(self, working_memory) -> dict:
        """从工作记忆构建状态字典"""
        state = {
            'task_context': {},
            'execution_history': [],
            'current_tool': None,
            'recent_results': []
        }

        # 提取任务上下文
        if hasattr(working_memory, 'goal'):
            state['task_context']['goal'] = working_memory.goal

        # 提取执行历史
        if hasattr(working_memory, 'messages'):
            for msg in working_memory.messages:
                if msg.get('role') == 'system' and '执行' in msg.get('content', ''):
                    state['execution_history'].append(msg.get('content', ''))

        # 提取当前工具
        if hasattr(working_memory, 'current_tool'):
            state['current_tool'] = working_memory.current_tool

        return state

    async def should_skip_execution(self, tool_id: str, params: dict, working_memory) -> tuple[bool, str]:
        """
        根据世界模型预测判断是否应跳过执行（高风险检查）

        Args:
            tool_id: 工具ID
            params: 工具参数
            working_memory: 工作记忆

        Returns:
            (是否跳过, 原因)
        """
        current_state = self._build_state_from_working_memory(working_memory)

        predictions = await self.predict_action_outcomes(current_state, [{
            'tool_id': tool_id,
            'params': params
        }])

        if not predictions.get('predictions'):
            return False, "无法获取预测"

        pred = predictions['predictions'][0]

        # 高风险判断
        if pred['risk'] > 0.8 and pred['confidence'] > 0.5:
            return True, f"风险过高({pred['risk']*100:.0f}%)，建议先验证"

        # 低成功率判断
        if pred['success_prob'] < 0.2 and pred['confidence'] > 0.5:
            return True, f"成功率过低({pred['success_prob']*100:.0f}%)，建议替代方案"

        return False, "预测风险可接受"


# 世界模型管理器单例
_world_model_manager_instance = None

def get_world_model_manager() -> WorldModelManager:
    """获取世界模型管理器单例"""
    global _world_model_manager_instance
    if _world_model_manager_instance is None:
        _world_model_manager_instance = WorldModelManager()
    return _world_model_manager_instance


# ═══════════════════════════════════════════════════════════════════════════════
# 文件总结性注释
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# 本文件是SiliconBase V5系统的核心认知引擎——世界模型（World Model），模拟硅基生命的"心智"能力。
# 它通过深度学习（Transformer架构）学习环境状态与行动之间的动态关系，使AI能够：
# 1. 预测执行动作后的结果
# 2. 评估不同行动的风险和收益
# 3. 进行反事实推理（"如果当时这样做会怎样"）
# 4. 使用MCTS规划最优行动序列
#
# 【核心组件】
# 1. StateEncoder（状态编码器）:
#    - 将复杂的感知数据（窗口、进程、CPU/内存使用率等）编码为128维固定向量
#    - 特征包括：感知特征(32维)、任务上下文(32维)、情绪状态(16维)、时间特征(8维)、历史结果(8维)
#    - 应用类型识别：浏览器、IDE、音乐、视频、游戏、文档、聊天等
#
# 2. ActionEncoder（动作编码器）:
#    - 将工具调用编码为32维动作向量
#    - 特征包括：工具类型one-hot(8维)、工具ID哈希(8维)、参数特征(8维)
#    - 工具类型：应用启动、窗口操作、鼠标、键盘、屏幕、文件、系统、其他
#
# 3. TransformerWorldModel（Transformer世界模型）:
#    - 核心神经网络，使用Transformer架构学习状态转移 dynamics
#    - 输入：当前状态 + 动作
#    - 输出：下一状态预测、奖励预测、完成标志预测
#    - 结构：状态/动作嵌入层 → Transformer编码器(4层,8头) → 三个预测头
#
# 4. MCTSPlanner（MCTS规划器）:
#    - 基于蒙特卡洛树搜索的行动规划器
#    - Selection（选择）：使用UCB1算法选择最有希望的节点
#    - Expansion（扩展）：扩展未尝试的动作
#    - Simulation（模拟）：随机rollout评估价值
#    - Backpropagation（反向传播）：更新节点访问次数和价值
#
# 5. WorldModel（世界模型主类）:
#    - 封装所有功能，提供统一接口
#    - 经验池管理（deque，最大10000条）
#    - 在线学习（每次工具调用后实时更新）
#    - 后台训练线程（每10条经验触发训练）
#    - 模型保存/加载（PyTorch格式）
#
# 【关联文件】
# - core/tool_manager.py: 调用observe_tool_execution()记录每次工具执行经验
# - core/agent_loop.py: 调用get_prediction_for_prompt()获取预测增强提示词
# - core/intrinsic_motivation.py: 使用预测误差计算新奇度（内在动机）
# - core/world_model_proxy.py: 代理层，提供降级支持（世界模型不可用时）
# - core/config.py: 提供配置参数
# - core/memory.py: 保存完整episode到长期记忆
# - core/logger.py: 日志记录
#
# 【数据流向】
#
# 学习流向（经验收集）:
#   ToolManager执行工具 → observe_tool_execution() → 编码状态/动作 → 经验池
#   → 在线更新模型 → 后台训练线程定期批量训练
#
# 预测流向（推理使用）:
#   Agent循环请求预测 → predict_detailed() → 编码输入 → Transformer推理
#   → 解码预测结果 → 格式化为提示词 → 提供给LLM
#
# 规划流向（行动规划）:
#   需要规划时 → MCTSPlanner.plan() → 多次模拟预测 → 选择最优动作序列
#
# 【达到的效果】
# 1. 经验学习：从每次工具执行中学习，持续改进预测准确性
# 2. 状态预测：给定当前状态和行动，预测下一状态（想象能力）
# 3. 风险评估：预测行动的成功概率和风险等级
# 4. 反事实推理：模拟"如果当时这样做会怎样"，支持决策反思
# 5. 行动规划：使用MCTS规划多步最优行动序列
# 6. 在线适应：实时学习新环境，无需离线训练
#
# 【异常处理策略】
# - 数据不足（buffer<10）：返回默认预测（成功率0.5，置信度0）
# - 在线更新异常：捕获并记录，不影响主流程
# - 训练循环异常：连续错误计数，超过5次暂停训练
# - 保存/加载异常：记录错误，使用默认初始化
# - 预测异常：返回空结果或默认值
#
# ═══════════════════════════════════════════════════════════════════════════════
