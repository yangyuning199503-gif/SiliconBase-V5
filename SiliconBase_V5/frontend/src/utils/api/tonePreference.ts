/**
 * 语气偏好设置API
 *
 * 【API端点】
 * - GET /api/users/{userId}/tone-preference - 获取用户语气偏好
 * - PUT /api/users/{userId}/tone-preference - 更新用户语气偏好
 * - GET /api/tone-presets - 获取语气预设列表
 * - POST /api/tone-preview - 生成语气预览
 */

import type {
  ToneConfig,
  TonePreset,
  ToneType,
} from "../../components/TonePreferencePanel";
import { fetchAPI, handleError } from "./index";

export type { ToneConfig, TonePreset, ToneType };

// 语气偏好API响应
export interface TonePreferenceResponse {
  success: boolean;
  data: ToneConfig;
  message?: string;
}

// 更新语气偏好请求参数
export interface UpdateTonePreferenceParams {
  type?: ToneType;
  formality?: number;
  enthusiasm?: number;
  empathy?: number;
  technicality?: number;
  custom_prompt?: string;
  enabled?: boolean;
}

// 预设列表响应
export interface TonePresetsResponse {
  success: boolean;
  data: TonePreset[];
}

// 创建预设请求参数
export interface CreateTonePresetParams {
  name: string;
  description?: string;
  config: ToneConfig;
}

// 更新预设请求参数
export interface UpdateTonePresetParams {
  name?: string;
  description?: string;
  config?: ToneConfig;
}

// 预览请求参数
export interface TonePreviewParams {
  type: ToneType;
  formality: number;
  enthusiasm: number;
  empathy: number;
  technicality: number;
  custom_prompt?: string;
}

// 预览响应
export interface TonePreviewResponse {
  success: boolean;
  data: {
    preview: string;
    config: ToneConfig;
  };
}

// 语气分析响应
export interface ToneAnalysisResponse {
  success: boolean;
  data: {
    detected_tone: ToneType;
    confidence: number;
    suggestions: string[];
  };
}

// 语气偏好API
export const tonePreferenceAPI = {
  /**
   * 获取用户语气偏好
   */
  async getTonePreference(userId: string = "default"): Promise<ToneConfig> {
    try {
      const response = await fetchAPI<TonePreferenceResponse>(
        `/api/users/${encodeURIComponent(userId)}/tone-preference`,
      );
      return response.data;
    } catch (error) {
      // 如果获取失败，返回默认配置
      console.warn("[TonePreferenceAPI] 获取语气偏好失败，使用默认配置");
      return {
        type: "casual",
        formality: 50,
        enthusiasm: 70,
        empathy: 80,
        technicality: 50,
        enabled: true,
      };
    }
  },

  /**
   * 更新用户语气偏好
   */
  async updateTonePreference(
    userId: string = "default",
    params: UpdateTonePreferenceParams,
  ): Promise<TonePreferenceResponse> {
    try {
      const response = await fetchAPI<TonePreferenceResponse>(
        `/api/users/${encodeURIComponent(userId)}/tone-preference`,
        {
          method: "PUT",
          body: params,
        },
      );
      return response;
    } catch (error) {
      return handleError(error, "更新语气偏好失败");
    }
  },

  /**
   * 重置为默认语气偏好
   */
  async resetTonePreference(userId: string = "default"): Promise<ToneConfig> {
    try {
      const response = await fetchAPI<{ success: boolean; data: ToneConfig }>(
        `/api/users/${encodeURIComponent(userId)}/tone-preference/reset`,
        {
          method: "POST",
        },
      );
      return response.data;
    } catch (error) {
      return handleError(error, "重置语气偏好失败");
    }
  },

  /**
   * 获取语气预设列表
   */
  async getTonePresets(): Promise<TonePreset[]> {
    try {
      const response = await fetchAPI<TonePresetsResponse>("/api/tone-presets");
      return response.data || [];
    } catch (error) {
      console.warn("[TonePreferenceAPI] 获取预设失败，返回空列表");
      return [];
    }
  },

  /**
   * 获取单个语气预设
   */
  async getTonePreset(presetId: string): Promise<TonePreset> {
    try {
      const response = await fetchAPI<{ success: boolean; data: TonePreset }>(
        `/api/tone-presets/${encodeURIComponent(presetId)}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取预设失败");
    }
  },

  /**
   * 创建自定义语气预设
   */
  async createTonePreset(params: CreateTonePresetParams): Promise<TonePreset> {
    try {
      const response = await fetchAPI<{ success: boolean; data: TonePreset }>(
        "/api/tone-presets",
        {
          method: "POST",
          body: params,
        },
      );
      return response.data;
    } catch (error) {
      return handleError(error, "创建预设失败");
    }
  },

  /**
   * 更新语气预设
   */
  async updateTonePreset(
    presetId: string,
    params: UpdateTonePresetParams,
  ): Promise<TonePreset> {
    try {
      const response = await fetchAPI<{ success: boolean; data: TonePreset }>(
        `/api/tone-presets/${encodeURIComponent(presetId)}`,
        {
          method: "PUT",
          body: params,
        },
      );
      return response.data;
    } catch (error) {
      return handleError(error, "更新预设失败");
    }
  },

  /**
   * 删除语气预设
   */
  async deleteTonePreset(
    presetId: string,
  ): Promise<{ success: boolean; message: string }> {
    try {
      const response = await fetchAPI<{ success: boolean; message: string }>(
        `/api/tone-presets/${encodeURIComponent(presetId)}`,
        {
          method: "DELETE",
        },
      );
      return response;
    } catch (error) {
      return handleError(error, "删除预设失败");
    }
  },

  /**
   * 生成语气预览
   */
  async generatePreview(
    params: TonePreviewParams,
  ): Promise<TonePreviewResponse> {
    try {
      const response = await fetchAPI<TonePreviewResponse>(
        "/api/tone-preview",
        {
          method: "POST",
          body: params,
        },
      );
      return response;
    } catch (error) {
      return handleError(error, "生成预览失败");
    }
  },

  /**
   * 分析文本的语气
   */
  async analyzeTone(text: string): Promise<ToneAnalysisResponse> {
    try {
      const response = await fetchAPI<ToneAnalysisResponse>(
        "/api/tone-analyze",
        {
          method: "POST",
          body: { text },
        },
      );
      return response;
    } catch (error) {
      return handleError(error, "语气分析失败");
    }
  },

  /**
   * 应用预设到用户偏好
   */
  async applyPresetToUser(
    userId: string = "default",
    presetId: string,
  ): Promise<ToneConfig> {
    try {
      const response = await fetchAPI<{ success: boolean; data: ToneConfig }>(
        `/api/users/${encodeURIComponent(userId)}/tone-preference/apply-preset`,
        {
          method: "POST",
          body: { preset_id: presetId },
        },
      );
      return response.data;
    } catch (error) {
      return handleError(error, "应用预设失败");
    }
  },

  /**
   * 获取语气历史记录
   */
  async getToneHistory(
    userId: string = "default",
    limit: number = 10,
  ): Promise<{
    history: Array<{
      timestamp: string;
      config: ToneConfig;
      reason?: string;
    }>;
    total: number;
  }> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: {
          history: Array<{
            timestamp: string;
            config: ToneConfig;
            reason?: string;
          }>;
          total: number;
        };
      }>(
        `/api/users/${encodeURIComponent(userId)}/tone-history?limit=${limit}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取语气历史失败");
    }
  },
};

export default tonePreferenceAPI;
