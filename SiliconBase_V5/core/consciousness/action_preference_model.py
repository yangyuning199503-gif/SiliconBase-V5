#!/usr/bin/env python3
"""
行动偏好预测模型 - 思维层的在线学习网络

设计目标：
- 小型轻量网络，输入24维，输出1维预期收益
- 权重随经验持续更新，数据越多决策越精准
- 冷启动保护：数据不足时自动降级为硬编码规则
- 全部在CPU上运行，不依赖GPU

手眼脑协同架构中的"脑"组件：
- 眼睛（视觉）→ _get_vision_state_vector() → 8维输入
- 动机（内在状态）→ _get_motivation_vector() → 4维输入
- 历史（经验）→ _get_history_vector() → 4维输入
- 候选动作 → _extract_action_features() → 8维输入
- 输出：预期收益（0~1），指导行动选择
"""

import json
import time
from collections import deque
from pathlib import Path

import numpy as np

try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except Exception:  # PyTorch 未安装时使用降级桩
    torch = None  # type: ignore[assignment]

    class _DummyModule:
        pass

    class _DummyNN:
        Module = _DummyModule
        Linear = object
        ReLU = object
        Sigmoid = object
        Sequential = object
        MSELoss = object

        @staticmethod
        def init(*args, **kwargs):
            pass

    nn = _DummyNN()  # type: ignore[assignment]
    TORCH_AVAILABLE = False


class ActionPreferencePredictor(nn.Module):
    """
    小型在线学习网络，预测在当前状态下选择某个候选动作的预期收益。
    输入：动机(4) + 视觉状态(8) + 候选动作特征(8) + 历史偏好(4) = 24维
    输出：预期收益（0~1标量）
    """

    def __init__(self):
        super().__init__()
        self.fc = nn.Sequential(
            nn.Linear(24, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
            nn.Sigmoid()
        )
        # Xavier初始化
        for layer in self.fc:
            if isinstance(layer, nn.Linear):
                nn.init.xavier_uniform_(layer.weight)
                nn.init.zeros_(layer.bias)

    def forward(self, motivation, vision_state, action_features, history):
        x = torch.cat([motivation, vision_state, action_features, history], dim=-1)
        return self.fc(x)

    def predict_batch(self, motivation, vision_state, candidates_features, history):
        """对多个候选动作分别计算预期收益，返回排序后的(候选索引, 收益)列表"""
        scores = []
        for i, af in enumerate(candidates_features):
            score = self.forward(motivation, vision_state, af, history)
            scores.append((i, score.item()))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def save(self, filepath: str):
        torch.save(self.state_dict(), filepath)

    def load(self, filepath: str):
        self.load_state_dict(torch.load(filepath, weights_only=True))


class OnlineLearner:
    """
    在线学习管理器。
    - 维护训练缓冲区 dequeue(maxlen=500)
    - 每10条新数据触发一次轻量训练
    - 数据越多，模型权重在决策中的占比越高
    """

    def __init__(self, model: ActionPreferencePredictor, buffer_size: int = 500, persistent_path: str | None = None):
        self.model = model
        self.buffer = deque(maxlen=buffer_size)
        self.optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
        self.loss_fn = nn.MSELoss()
        self.sample_count = 0
        self.last_train_count = 0

        # 【新增】持久化配置
        self._persistent_path = Path(persistent_path) if persistent_path else None
        if self._persistent_path:
            self._persistent_path.parent.mkdir(parents=True, exist_ok=True)

    def add_sample(self, input_vector: "torch.Tensor", label: float, source: str = "unknown"):
        """写入训练样本。label=1.0表示成功，label=0.0表示失败"""
        self.buffer.append((input_vector.detach().clone(), float(label)))
        self.sample_count += 1

        # 【新增】同步追加写入磁盘（异常静默，不中断训练）
        if self._persistent_path:
            try:
                record = {
                    "timestamp": time.time(),
                    "input_vector": input_vector.detach().cpu().tolist(),
                    "label": float(label),
                    "source": source,
                    "sample_count": self.sample_count,
                }
                with open(self._persistent_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception:
                pass  # 持久化失败不中断训练流

    def should_train(self) -> bool:
        """累积10条新数据后触发训练"""
        return (self.sample_count - self.last_train_count) >= 10

    def train_step(self) -> float:
        """从缓冲区随机采样一个batch，做一步梯度下降，返回loss值"""
        if len(self.buffer) < 4:
            return 0.0

        batch_size = min(16, len(self.buffer))
        indices = np.random.choice(len(self.buffer), batch_size, replace=False)

        total_loss = 0.0
        for idx in indices:
            x, y = self.buffer[idx]
            self.optimizer.zero_grad()
            pred = self.model.fc(x.unsqueeze(0))
            loss = self.loss_fn(pred, torch.tensor([[y]], dtype=torch.float32))
            loss.backward()
            self.optimizer.step()
            total_loss += loss.item()

        self.last_train_count = self.sample_count
        return total_loss / batch_size

    def get_model_weight(self) -> float:
        """返回模型权重在决策中的占比。数据不足10条时用0.3，100条以上用1.0"""
        if self.sample_count < 10:
            return 0.3
        elif self.sample_count >= 100:
            return 1.0
        else:
            return 0.3 + 0.7 * (self.sample_count - 10) / 90.0
