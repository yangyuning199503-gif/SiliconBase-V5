"""
本地模型插排 - 统一加载/卸载/热切换本地PyTorch模型
版本: V2.0 - 硅基生命底座版
核心理念: 通用插排，零硬编码，功能即插即用
"""
import gc
import logging
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ModelSlot(Enum):
    """
    模型槽位 - 插孔定义

    槽位说明:
        EMBEDDING: 向量模型 - 文本向量化，用于记忆存储和语义检索
        AUDIO_SYNTHESIS: 音频合成 - TTS语音播报，AI语音回复
        VOICE_CONVERSION: 语音转换 - 声音克隆，改变音色保留内容
        AUDIO_UNDERSTANDING: 语音理解 - 高级语音特征提取，情感分析
        WORLD_MODEL: 世界模型 - 环境预测，工具成功率预测，MCTS规划
        SENTIMENT: 情感分析 - 文本情感识别，用户情绪状态评估
    """
    EMBEDDING = "embedding"                    # 向量模型 - 记忆语义检索
    AUDIO_SYNTHESIS = "audio_synthesis"        # 音频合成 - TTS语音播报
    VOICE_CONVERSION = "voice_conversion"      # 语音转换 - 声音克隆
    AUDIO_UNDERSTANDING = "audio_understanding" # 语音理解 - 语音特征提取
    WORLD_MODEL = "world_model"                # 世界模型 - 环境预测决策
    SENTIMENT = "sentiment"                    # 情感分析 - 文本情感识别


class ModelPriority(Enum):
    """模型优先级"""
    RESIDENT = "resident"
    ONDEMAND = "ondemand"


class LocalModelCoordinator:
    """
    本地模型插排 - 单例

    职责：
    1. 根据 global.yaml 配置加载模型
    2. 支持热加载（配置变更自动重载）
    3. 显存管理：常驻/按需/自动卸载
    4. 统一接口：get_model(slot) / release_model(slot)
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._models: dict[ModelSlot, Any] = {}
        self._last_used: dict[ModelSlot, float] = {}
        self._locks: dict[ModelSlot, threading.RLock] = {
            slot: threading.RLock() for slot in ModelSlot
        }

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="ModelCoordinatorMonitor"
        )
        self._monitor_thread.start()

        logger.info("[ModelCoordinator] 本地模型插排已初始化")

    def _get_config(self, slot: ModelSlot) -> dict | None:
        """从 global.yaml 读取模型配置"""
        try:
            from core.config import config
            return config.get(f"local_models.{slot.value}")
        except Exception as e:
            logger.error(f"[ModelCoordinator] 读取配置失败: {e}")
            return None

    def get_model(self, slot: ModelSlot) -> Any | None:
        """获取模型 - 插排取电接口"""
        config = self._get_config(slot)
        if not config or not config.get("enabled", False):
            logger.debug(f"[ModelCoordinator] {slot.value} 未启用")
            return None

        if slot in self._models:
            self._last_used[slot] = time.time()
            return self._models[slot]

        with self._locks[slot]:
            if slot in self._models:
                return self._models[slot]

            model = self._load_model(slot, config)
            if model:
                self._models[slot] = model
                self._last_used[slot] = time.time()
                logger.info(f"[ModelCoordinator] {slot.value} 已加载")
            return model

    def _load_model(self, slot: ModelSlot, config: dict) -> Any | None:
        """根据配置加载模型"""
        provider = config.get("provider")

        loaders = {
            "sentence-transformers": self._load_sentence_transformer,
            "bigvgan": self._load_bigvgan,
            "maskgct": self._load_maskgct,
            "w2v-bert": self._load_w2v_bert,
            "pytorch": self._load_pytorch_model,
            "transformers": self._load_transformers_model,
        }

        loader = loaders.get(provider)
        if not loader:
            logger.error(f"[ModelCoordinator] 未知 provider: {provider}")
            return None

        try:
            return loader(config)
        except Exception as e:
            logger.error(f"[ModelCoordinator] 加载 {slot.value} 失败: {e}")
            return None

    def _load_sentence_transformer(self, config: dict):
        """加载向量模型 - 强制使用本地快照路径，禁用网络下载"""
        from sentence_transformers import SentenceTransformer

        model_name = config.get("model_name", "sentence-transformers/all-MiniLM-L6-v2")
        # 使用项目根目录下的绝对路径
        project_root = Path(__file__).parent.parent.parent
        cache_dir = project_root / "checkpoints" / "hf_cache"
        device = config.get("device", "cpu")

        # 解析本地 HF 缓存快照路径
        local_root = cache_dir / f"models--{model_name.replace('/', '--')}"
        snapshot_dir = None
        if local_root.exists():
            snapshots = local_root / "snapshots"
            if snapshots.exists():
                for child in snapshots.iterdir():
                    if child.is_dir():
                        snapshot_dir = child
                        break

        if snapshot_dir is None or not snapshot_dir.exists():
            raise FileNotFoundError(f"本地向量模型未找到: {local_root}，请确认模型已下载到本地缓存")

        model_path = str(snapshot_dir).replace('\\', '/')
        return SentenceTransformer(model_path, device=device, local_files_only=True)

    def _load_bigvgan(self, config: dict):
        """加载BigVGAN - 占位，实际由advanced_model_manager实现"""
        logger.info("[ModelCoordinator] BigVGAN加载请求已转发")
        return {"type": "bigvgan", "config": config}

    def _load_maskgct(self, config: dict):
        """加载MaskGCT - 占位"""
        logger.info("[ModelCoordinator] MaskGCT加载请求已转发")
        return {"type": "maskgct", "config": config}

    def _load_w2v_bert(self, config: dict):
        """加载W2V-BERT - 占位"""
        logger.info("[ModelCoordinator] W2V-BERT加载请求已转发")
        return {"type": "w2v-bert", "config": config}

    def _load_pytorch_model(self, config: dict):
        """加载通用PyTorch模型"""
        import torch

        model_path = config.get("model_path")
        device = config.get("device", "cpu")

        if not model_path or not Path(model_path).exists():
            logger.warning(f"[ModelCoordinator] 模型文件不存在: {model_path}")
            return None

        return torch.load(model_path, map_location=device)

    def _load_transformers_model(self, config: dict):
        """加载Transformers模型"""
        import torch
        from transformers import AutoModel, AutoTokenizer

        model_name = config.get("model_name")
        cache_dir = config.get("cache_dir", "checkpoints/hf_cache")
        device = config.get("device", "cpu")

        model = AutoModel.from_pretrained(model_name, cache_dir=cache_dir)
        tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)

        if device == "cuda" and torch.cuda.is_available():
            model = model.cuda()

        return {"model": model, "tokenizer": tokenizer}

    def release_model(self, slot: ModelSlot):
        """释放模型"""
        with self._locks[slot]:
            if slot in self._models:
                model = self._models.pop(slot)
                del model
                gc.collect()

                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception as e:
                    logger.debug(f"CUDA缓存清理失败: {e}")

                logger.info(f"[ModelCoordinator] {slot.value} 已释放")

    def _monitor_loop(self):
        """后台监控 - 自动卸载超时模型"""
        while True:
            time.sleep(60)

            current_time = time.time()
            for slot in list(self._models.keys()):
                config = self._get_config(slot)
                if not config:
                    continue

                if config.get("priority") == "resident":
                    continue

                last_used = self._last_used.get(slot, 0)
                if current_time - last_used > 300:
                    logger.info(f"[ModelCoordinator] {slot.value} 超时释放")
                    self.release_model(slot)

    def get_status(self) -> dict[str, Any]:
        """获取所有槽位状态"""
        status = {}
        for slot in ModelSlot:
            config = self._get_config(slot)
            status[slot.value] = {
                "enabled": config.get("enabled", False) if config else False,
                "loaded": slot in self._models,
                "provider": config.get("provider") if config else None,
                "priority": config.get("priority") if config else None,
            }
        return status

    def reload_config(self):
        """热重载配置"""
        self._models.clear()
        self._last_used.clear()
        gc.collect()
        logger.info("[ModelCoordinator] 配置已热重载")


# 全局实例
coordinator = LocalModelCoordinator()


def get_model_coordinator() -> LocalModelCoordinator:
    """获取模型插排实例"""
    return coordinator


def get_model(slot: ModelSlot) -> Any | None:
    """快捷获取模型"""
    return coordinator.get_model(slot)
