/**
 * 三视图配置 API
 * 对应后端 /api/three-views/* 端点
 */

import { fetchAPI, handleError } from "./index";

export interface ThreeViewsTemplate {
  id: string;
  name: string;
  description?: string;
  content: string;
}

export interface ThreeViewsConfigData {
  template_id?: string;
  worldview?: string;
  values?: string;
  ethics?: string;
  custom?: Record<string, any>;
}

export const threeViewsAPI = {
  /**
   * 获取所有可用三观模板
   */
  async getTemplates(): Promise<ThreeViewsTemplate[]> {
    try {
      const response = await fetchAPI<{ success: boolean; data: { templates: ThreeViewsTemplate[] } }>(
        "/api/three-views/templates",
      );
      return response.data.templates || [];
    } catch (error) {
      return handleError(error, "获取三观模板失败");
    }
  },

  /**
   * 获取当前用户三观配置
   */
  async getConfig(): Promise<ThreeViewsConfigData> {
    try {
      const response = await fetchAPI<{ success: boolean; data: ThreeViewsConfigData }>(
        "/api/three-views/config",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取三观配置失败");
    }
  },

  /**
   * 保存用户三观配置
   */
  async saveConfig(config: ThreeViewsConfigData): Promise<{ success: boolean; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; message: string }>("/api/three-views/config", {
        method: "POST",
        body: config,
      });
    } catch (error) {
      return handleError(error, "保存三观配置失败");
    }
  },

  /**
   * 预览指定模板的三观提示词
   */
  async previewTemplate(templateId: string): Promise<{ prompt: string }> {
    try {
      const response = await fetchAPI<{ success: boolean; data: { prompt: string } }>(
        `/api/three-views/preview?template_id=${encodeURIComponent(templateId)}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "预览模板失败");
    }
  },
};

export default threeViewsAPI;
