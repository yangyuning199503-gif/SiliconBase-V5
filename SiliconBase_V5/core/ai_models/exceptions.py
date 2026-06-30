"""
ModelBus异常定义模块

定义所有与模型基础设施相关的异常类
"""

from typing import Any


class ModelBusException(Exception):
    """ModelBus基础异常类"""

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or "MODEL_BUS_ERROR"
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"[{self.error_code}] {self.message} | Details: {self.details}"
        return f"[{self.error_code}] {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details
        }


class ProviderNotFoundException(ModelBusException):
    """Provider未找到异常"""

    def __init__(
        self,
        provider_type: str,
        model_type: str | None = None,
        message: str | None = None
    ):
        details = {"provider_type": provider_type}
        if model_type:
            details["model_type"] = model_type

        super().__init__(
            message=message or f"Provider类型 '{provider_type}' 未注册",
            error_code="PROVIDER_NOT_FOUND",
            details=details
        )
        self.provider_type = provider_type
        self.model_type = model_type


class SlotNotFoundException(ModelBusException):
    """槽位未找到异常"""

    def __init__(
        self,
        slot_id: str,
        message: str | None = None
    ):
        super().__init__(
            message=message or f"槽位 '{slot_id}' 不存在",
            error_code="SLOT_NOT_FOUND",
            details={"slot_id": slot_id}
        )
        self.slot_id = slot_id


class ConfigurationException(ModelBusException):
    """配置异常"""

    def __init__(
        self,
        message: str,
        config_field: str | None = None,
        config_value: Any | None = None
    ):
        details = {}
        if config_field:
            details["field"] = config_field
        if config_value is not None:
            details["value"] = str(config_value)

        super().__init__(
            message=message,
            error_code="CONFIGURATION_ERROR",
            details=details
        )
        self.config_field = config_field
        self.config_value = config_value


class ProviderUnavailableException(ModelBusException):
    """Provider不可用异常"""

    def __init__(
        self,
        provider: str,
        reason: str | None = None,
        slot_id: str | None = None
    ):
        details = {"provider": provider}
        if reason:
            details["reason"] = reason
        if slot_id:
            details["slot_id"] = slot_id

        super().__init__(
            message=reason or f"Provider '{provider}' 当前不可用",
            error_code="PROVIDER_UNAVAILABLE",
            details=details
        )
        self.provider = provider
        self.reason = reason


class InvokeException(ModelBusException):
    """调用异常"""

    def __init__(
        self,
        message: str,
        slot_id: str | None = None,
        provider: str | None = None,
        original_error: Exception | None = None
    ):
        details = {}
        if slot_id:
            details["slot_id"] = slot_id
        if provider:
            details["provider"] = provider
        if original_error:
            details["original_error"] = f"{type(original_error).__name__}: {str(original_error)}"

        super().__init__(
            message=message,
            error_code="INVOKE_ERROR",
            details=details
        )
        self.slot_id = slot_id
        self.provider = provider
        self.original_error = original_error


class ValidationException(ModelBusException):
    """验证异常"""

    def __init__(
        self,
        message: str,
        field: str | None = None,
        value: Any | None = None
    ):
        details = {}
        if field:
            details["field"] = field
        if value is not None:
            details["value"] = str(value)

        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            details=details
        )
        self.field = field
        self.value = value


class RegistryException(ModelBusException):
    """注册表异常"""

    def __init__(
        self,
        message: str,
        provider_type: str | None = None
    ):
        details = {}
        if provider_type:
            details["provider_type"] = provider_type

        super().__init__(
            message=message,
            error_code="REGISTRY_ERROR",
            details=details
        )
        self.provider_type = provider_type


class TimeoutException(ModelBusException):
    """超时异常"""

    def __init__(
        self,
        operation: str,
        timeout_seconds: float,
        slot_id: str | None = None
    ):
        details = {
            "operation": operation,
            "timeout_seconds": timeout_seconds
        }
        if slot_id:
            details["slot_id"] = slot_id

        super().__init__(
            message=f"操作 '{operation}' 超时 ({timeout_seconds}s)",
            error_code="TIMEOUT_ERROR",
            details=details
        )
        self.operation = operation
        self.timeout_seconds = timeout_seconds


# =============================================================================
# 音频相关异常 (Phase 3新增)
# =============================================================================

class AudioException(ModelBusException):
    """音频相关异常基类"""

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        details: dict[str, Any] | None = None
    ):
        super().__init__(
            message=message,
            error_code=error_code or "AUDIO_ERROR",
            details=details
        )


class ModelLoadException(AudioException):
    """模型加载失败异常"""

    def __init__(
        self,
        message: str,
        model_path: str | None = None,
        provider: str | None = None
    ):
        details = {}
        if model_path:
            details["model_path"] = model_path
        if provider:
            details["provider"] = provider

        super().__init__(
            message=message,
            error_code="MODEL_LOAD_ERROR",
            details=details
        )
        self.model_path = model_path
        self.provider = provider


class RecognitionException(AudioException):
    """语音识别失败异常"""

    def __init__(
        self,
        message: str,
        audio_length: int | None = None,
        sample_rate: int | None = None,
        details: dict[str, Any] | None = None
    ):
        error_details = details or {}
        if audio_length is not None:
            error_details["audio_length"] = audio_length
        if sample_rate is not None:
            error_details["sample_rate"] = sample_rate

        super().__init__(
            message=message,
            error_code="RECOGNITION_ERROR",
            details=error_details
        )
        self.audio_length = audio_length
        self.sample_rate = sample_rate


class SynthesisException(AudioException):
    """语音合成失败异常"""

    def __init__(
        self,
        message: str,
        text: str | None = None,
        speaker_id: int | None = None,
        details: dict[str, Any] | None = None
    ):
        error_details = details or {}
        if text is not None:
            error_details["text_length"] = len(text) if text else 0
        if speaker_id is not None:
            error_details["speaker_id"] = speaker_id

        super().__init__(
            message=message,
            error_code="SYNTHESIS_ERROR",
            details=error_details
        )
        self.text = text
        self.speaker_id = speaker_id


class AudioFormatException(AudioException):
    """音频格式错误异常"""

    def __init__(
        self,
        message: str,
        expected_format: str | None = None,
        actual_format: str | None = None,
        sample_rate: int | None = None
    ):
        details = {}
        if expected_format:
            details["expected_format"] = expected_format
        if actual_format:
            details["actual_format"] = actual_format
        if sample_rate is not None:
            details["sample_rate"] = sample_rate

        super().__init__(
            message=message,
            error_code="AUDIO_FORMAT_ERROR",
            details=details
        )
        self.expected_format = expected_format
        self.actual_format = actual_format
        self.sample_rate = sample_rate


class AudioEnhancementException(AudioException):
    """语音增强失败异常"""

    def __init__(
        self,
        message: str,
        operation: str | None = None,
        audio_length: int | None = None
    ):
        details = {}
        if operation:
            details["operation"] = operation
        if audio_length is not None:
            details["audio_length"] = audio_length

        super().__init__(
            message=message,
            error_code="ENHANCEMENT_ERROR",
            details=details
        )
        self.operation = operation
        self.audio_length = audio_length


# =============================================================================
# 向量嵌入相关异常 (Phase 4新增)
# =============================================================================

class EmbeddingException(ModelBusException):
    """
    向量嵌入失败异常

    当文本向量化过程失败时抛出。
    """

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        details: dict[str, Any] | None = None
    ):
        super().__init__(
            message=message,
            error_code=error_code or "EMBEDDING_ERROR",
            details=details
        )


class MultimodalException(ModelBusException):
    """
    多模态处理失败异常

    当多模态模型（视觉+动作+推理）处理失败时抛出。
    """

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        details: dict[str, Any] | None = None
    ):
        super().__init__(
            message=message,
            error_code=error_code or "MULTIMODAL_ERROR",
            details=details
        )
