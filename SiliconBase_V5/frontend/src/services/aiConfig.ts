/**
 * AI配置API服务 - 支持多后端切换和热加载
 */

import { fetchAPI } from '@/utils/api';

const API_BASE = '/api/ai';

export interface AIProviderInfo {
  type: string;
  name: string;
  category?: 'cloud' | 'local' | 'other';
  description?: string;
  default_model?: string;
  models?: string[];
  required_config: string[];
  optional_config: string[];
}

export interface AIProviderConfig {
  base_url?: string;
  model?: string;
  timeout?: number;
  retry_times?: number;
  api_key?: string;
  api_url?: string;
  headers?: Record<string, string>;
  request_template?: Record<string, any>;
  response_path?: string;
  preset?: string;
  temperature?: number;
  max_tokens?: number;
}

export interface VisionConfig {
  // 新格式: 多后端管理
  default_backend?: string;
  backends?: Record<string, AIProviderConfig & { 
    name: string; 
    provider: string;
    capabilities?: string[];
    supports_vision?: boolean;
  }>;
  // 旧格式: 单后端 (兼容)
  provider?: string;
  config?: AIProviderConfig;
  // 状态标识
  configured?: boolean;
  legacy_model?: string;
}

export interface AICurrentConfig {
  provider: string;
  config: AIProviderConfig;
  info: {
    type: string;
    config: Record<string, any>;
    available: boolean;
  };
}

export const aiConfigService = {
  async getProviders(): Promise<AIProviderInfo[]> {
    try {
      const result = await fetchAPI<any>(`${API_BASE}/providers`);
      if (!result.success) throw new Error(result.error || '获取提供商列表失败');
      if (!result.data || !Array.isArray(result.data)) {
        throw new Error('提供商数据格式错误');
      }
      return result.data;
    } catch (error) {
      console.error('[AIConfigService] 获取提供商列表失败:', error);
      throw error;
    }
  },

  async getCurrentConfig(): Promise<AICurrentConfig> {
    try {
      const result = await fetchAPI<any>(`${API_BASE}/config`);
      if (!result.success) throw new Error(result.error || '获取配置失败');
      // 确保返回的数据包含必要的字段
      const data = result.data || {};
      if (!data.config) {
        data.config = {};
      }
      if (!data.provider) {
        data.provider = 'ollama';
      }
      return data;
    } catch (error) {
      console.error('[AIConfigService] 获取当前配置失败:', error);
      throw error;
    }
  },

  async updateConfig(
    provider: string,
    config: AIProviderConfig,
    options?: { persist?: boolean; saveApiKey?: boolean; vision?: VisionConfig }
  ): Promise<{ success: boolean; message: string }> {
    try {
      const body: Record<string, any> = {
        provider,
        config,
        persist: options?.persist ?? true,
        save_api_key: options?.saveApiKey ?? false
      };
      
      // 如果提供了视觉配置，添加到请求体
      if (options?.vision) {
        body.vision = options.vision;
      }
      
      const result = await fetchAPI<any>(`${API_BASE}/config`, {
        method: 'POST',
        body,
      });
      return result;
    } catch (error) {
      console.error('[AIConfigService] 更新配置失败:', error);
      throw error;
    }
  },

  async testConfig(provider: string, config: AIProviderConfig): Promise<{ success: boolean; message: string; available_models?: string[] }> {
    try {
      return await fetchAPI<any>(`${API_BASE}/test`, {
        method: 'POST',
        body: { provider, config },
        timeout: 30000,  // 增加到30秒，因为AI配置测试可能需要较长时间
      });
    } catch (error) {
      console.error('[AIConfigService] 测试配置失败:', error);
      throw error;
    }
  },

  async getModels(provider?: string): Promise<string[]> {
    try {
      const url = provider ? `${API_BASE}/models?provider=${provider}` : `${API_BASE}/models`;
      const result = await fetchAPI<any>(url);
      if (!result.success) throw new Error(result.error || '获取模型列表失败');
      return result.data || [];
    } catch (error) {
      console.error('[AIConfigService] 获取模型列表失败:', error);
      throw error;
    }
  },

  async getVisionConfig(): Promise<VisionConfig | null> {
    try {
      const result = await fetchAPI<any>(`${API_BASE}/config/vision`);
      if (!result.success) {
        console.warn('[AIConfigService] 获取视觉配置失败:', result.error);
        return null;
      }
      return result.data || null;
    } catch (error) {
      console.error('[AIConfigService] 获取视觉配置失败:', error);
      return null;
    }
  },

  async getProviderModels(provider: string): Promise<string[]> {
    try {
      const result = await fetchAPI<any>(`${API_BASE}/models/${encodeURIComponent(provider)}`);
      if (!result.success) throw new Error(result.error || '获取提供商模型列表失败');
      return result.data || [];
    } catch (error) {
      console.error('[AIConfigService] 获取提供商模型列表失败:', error);
      throw error;
    }
  },

  async updateVisionConfig(vision: VisionConfig): Promise<{ success: boolean; message: string }> {
    try {
      return await fetchAPI<any>(`${API_BASE}/config/vision`, {
        method: 'POST',
        body: vision,
      });
    } catch (error) {
      console.error('[AIConfigService] 更新视觉配置失败:', error);
      throw error;
    }
  },

  async testVision(
    image: string,
    prompt: string = '描述这张图片',
    config?: AIProviderConfig
  ): Promise<{ success: boolean; message: string; result?: string }> {
    try {
      return await fetchAPI<any>(`${API_BASE}/test/vision`, {
        method: 'POST',
        body: { image, prompt, config },
        timeout: 60000,
      });
    } catch (error) {
      console.error('[AIConfigService] 视觉测试失败:', error);
      throw error;
    }
  }
};
