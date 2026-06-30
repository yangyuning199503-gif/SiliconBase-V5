/**
 * 语音控制 API
 * 对应后端 /api/voice/* 端点
 */

import { fetchAPI, handleError } from "./index";

export interface VoiceStatus {
  enabled: boolean;
  tts_engine?: string;
  asr_engine?: string;
  is_speaking?: boolean;
}

export interface STTResponse {
  success: boolean;
  text: string;
  confidence?: number;
  error?: string;
}

export const voiceAPI = {
  /**
   * 播报语音消息
   */
  async announce(message: string, priority: string = "normal"): Promise<{ success: boolean; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; message: string }>("/api/voice/announce", {
        method: "POST",
        body: { message, priority },
      });
    } catch (error) {
      return handleError(error, "语音播报失败");
    }
  },

  /**
   * 播报层级切换提示
   */
  async announceLayerSwitch(layer: string, message?: string): Promise<{ success: boolean; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; message: string }>("/api/voice/layer-switch", {
        method: "POST",
        body: { layer, message },
      });
    } catch (error) {
      return handleError(error, "层级切换播报失败");
    }
  },

  /**
   * 语音测试
   */
  async testVoice(text: string = "语音测试"): Promise<{ success: boolean; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; message: string }>("/api/voice/test", {
        method: "POST",
        body: { text },
      });
    } catch (error) {
      return handleError(error, "语音测试失败");
    }
  },

  /**
   * 获取语音系统状态
   */
  async getStatus(): Promise<VoiceStatus> {
    try {
      return await fetchAPI<VoiceStatus>("/api/voice/status");
    } catch (error) {
      return handleError(error, "获取语音状态失败");
    }
  },

  /**
   * 启用语音播报
   */
  async enable(): Promise<{ success: boolean; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; message: string }>("/api/voice/enable", {
        method: "POST",
      });
    } catch (error) {
      return handleError(error, "启用语音失败");
    }
  },

  /**
   * 禁用语音播报
   */
  async disable(): Promise<{ success: boolean; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; message: string }>("/api/voice/disable", {
        method: "POST",
      });
    } catch (error) {
      return handleError(error, "禁用语音失败");
    }
  },

  /**
   * 音频语音识别（Speech-to-Text）
   */
  async speechToText(audioBase64: string, format: string = "wav"): Promise<STTResponse> {
    try {
      return await fetchAPI<STTResponse>("/api/voice/stt", {
        method: "POST",
        body: { audio: audioBase64, format },
      });
    } catch (error) {
      return handleError(error, "语音识别失败");
    }
  },

  /**
   * 快捷语音播报（GET 方式）
   */
  async quickAnnounce(message: string): Promise<{ success: boolean; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; message: string }>(
        `/api/voice/quick-announce?message=${encodeURIComponent(message)}`,
      );
    } catch (error) {
      return handleError(error, "快捷语音播报失败");
    }
  },
};

export default voiceAPI;
