/**
 * 配置管理API - 支持global.yaml热加载
 *
 * 2026-02-27 更新：
 * - 新增YAML操作接口
 * - 支持直接读取/写入global.yaml
 * - 支持手动触发热重载
 */
import { fetchAPI, handleError } from "./index";

export interface ConfigData {
  work_mode: string;
  voice_wake_word: string;
  model_name: string;
  vision_model: string;
  temperature: number;
  max_tokens: number;
  tool_whitelist: string[];
  enable_voice: boolean;
  think_interval: number;
  voice_tts_engine: string;
  voice_tts_speed: number;
  voice_tts_volume: number;
  voice_wake_mode: string;
  voice_input_device: string;
  voice_output_device: string;
  voice_asr_engine: string;
}

// Select选项可以是字符串数组或对象数组
export interface SelectOption {
  value: string;
  label: string;
}

export interface ConfigSchemaItem {
  type:
    | "select"
    | "string"
    | "number"
    | "integer"
    | "boolean"
    | "array"
    | "password";
  label: string;
  description?: string;
  options?: string[] | SelectOption[];
  placeholder?: string;
  min?: number;
  max?: number;
  step?: number;
}

export interface ConfigSchema {
  [key: string]: ConfigSchemaItem;
}

// YAML配置响应
export interface YamlConfigResponse {
  content: string;
  parsed: Record<string, any>;
}

// 配置映射（表单字段到YAML路径）
// P0-005 Fix: voice_wake_word 映射到 voice.wake_words（列表格式）
export const CONFIG_MAPPING: Record<string, string> = {
  work_mode: "work_mode",
  voice_wake_word: "voice.wake_words", // 已更新：复数形式，列表格式
  model_name: "ai.default_model",
  vision_model: "ai.vision_model", // 视觉模型配置
  temperature: "ai.temperature",
  max_tokens: "ai.max_tokens",
  tool_whitelist: "tools.whitelist",
  enable_voice: "voice.enabled",
  think_interval: "mode.daily.interval",
};

// 反向映射
export const REVERSE_CONFIG_MAPPING: Record<string, string> = Object.entries(
  CONFIG_MAPPING,
).reduce((acc, [key, value]) => ({ ...acc, [value]: key }), {});

// 备份信息接口
export interface BackupInfo {
  filename: string;
  path: string;
  size: number;
  created: string;
}

// 备份列表响应
export interface BackupListResponse {
  backups: BackupInfo[];
  count: number;
  max_backups: number;
}

export const configAPI = {
  /**
   * 获取当前配置（表单格式）
   */
  async getConfig(): Promise<ConfigData> {
    try {
      const response = await fetchAPI<{ success: boolean; data: ConfigData }>(
        "/api/config",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取配置失败");
    }
  },

  /**
   * 获取配置Schema（用于表单生成）
   */
  async getConfigSchema(): Promise<ConfigSchema> {
    try {
      const response = await fetchAPI<{ success: boolean; data: ConfigSchema }>(
        "/api/config/schema",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取配置Schema失败");
    }
  },

  /**
   * 更新配置（表单格式）
   * S-2 Fix: 使用 CONFIG_MAPPING 将表单键转换为 YAML 路径，
   * 并对 voice_wake_word 自动包装为列表格式。
   */
  async updateConfig(
    updates: Partial<ConfigData>,
  ): Promise<{ success: boolean; message: string }> {
    try {
      // 将表单键转换为 YAML 路径
      const mappedUpdates: Record<string, any> = {};
      for (const [formKey, value] of Object.entries(updates)) {
        const yamlPath = CONFIG_MAPPING[formKey] || formKey;
        // voice_wake_word 需要包装为列表
        if (formKey === "voice_wake_word" && typeof value === "string") {
          mappedUpdates[yamlPath] = [value];
        } else {
          mappedUpdates[yamlPath] = value;
        }
      }
      const response = await fetchAPI<{ success: boolean; message: string }>(
        "/api/config",
        {
          method: "POST",
          body: mappedUpdates,
        },
      );
      return response;
    } catch (error) {
      return handleError(error, "更新配置失败");
    }
  },

  /**
   * 获取global.yaml原始内容
   */
  async getYamlConfig(): Promise<YamlConfigResponse> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: YamlConfigResponse;
      }>("/api/config/yaml");
      return response.data;
    } catch (error) {
      return handleError(error, "获取YAML配置失败");
    }
  },

  /**
   * 保存global.yaml内容
   */
  async saveYamlConfig(content: string): Promise<{
    success: boolean;
    message: string;
    data?: { parsed: Record<string, any> };
  }> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        message: string;
        data?: { parsed: Record<string, any> };
      }>("/api/config/yaml", {
        method: "POST",
        body: { content },
      });
      return response;
    } catch (error) {
      return handleError(error, "保存YAML配置失败");
    }
  },

  /**
   * 直接按 YAML 路径更新配置（用于功能开关子特性等灵活场景）
   * @param updates - 键为 YAML 路径（如 features.advanced_models.bigvgan_v2.enabled），值为新值
   */
  async updateRawConfig(
    updates: Record<string, any>,
  ): Promise<{ success: boolean; message: string }> {
    try {
      const response = await fetchAPI<{ success: boolean; message: string }>(
        "/api/config",
        {
          method: "POST",
          body: updates,
        },
      );
      return response;
    } catch (error) {
      return handleError(error, "更新配置失败");
    }
  },

  /**
   * 手动触发配置热重载
   */
  async reloadConfig(): Promise<{ success: boolean; message: string }> {
    try {
      const response = await fetchAPI<{ success: boolean; message: string }>(
        "/api/config/reload",
        {
          method: "POST",
        },
      );
      return response;
    } catch (error) {
      return handleError(error, "热重载配置失败");
    }
  },

  /**
   * 获取备份列表
   */
  async getBackupList(): Promise<BackupListResponse> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: BackupListResponse;
      }>("/api/config/backups");
      return response.data;
    } catch (error) {
      return handleError(error, "获取备份列表失败");
    }
  },

  /**
   * 从备份恢复配置
   */
  async restoreBackup(
    backupFilename: string,
  ): Promise<{ success: boolean; message: string; warning?: string }> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        message: string;
        warning?: string;
      }>("/api/config/restore", {
        method: "POST",
        body: { backup_filename: backupFilename },
      });
      return response;
    } catch (error) {
      return handleError(error, "恢复备份失败");
    }
  },
};

// 工具函数：获取嵌套值
export function getNestedValue(obj: any, path: string): any {
  return path.split(".").reduce((acc, key) => acc?.[key], obj);
}

// 工具函数：设置嵌套值
export function setNestedValue(obj: any, path: string, value: any): void {
  const keys = path.split(".");
  const lastKey = keys.pop()!;
  const target = keys.reduce((acc, key) => {
    if (!acc[key]) acc[key] = {};
    return acc[key];
  }, obj);
  target[lastKey] = value;
}
