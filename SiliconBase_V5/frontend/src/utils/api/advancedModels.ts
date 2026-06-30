/**
 * 高级模型管理 API
 * 对应后端 /api/advanced-models/* 端点
 */

import { fetchAPI, handleError } from "./index";

export interface ModelStatus {
  model_id: string;
  name: string;
  enabled: boolean;
  loaded: boolean;
  downloading: boolean;
  progress: number;
  size?: number;
  memory_usage?: number;
}

export interface OperationResponse {
  success: boolean;
  model_id: string;
  message: string;
}

export interface DownloadProgress {
  model_id: string;
  progress: number;
  status: string;
  speed?: number;
  eta?: number;
}

export interface MemoryStatus {
  total: number;
  available: number;
  used: number;
  percent: number;
}

export const advancedModelsAPI = {
  /**
   * 获取单个模型的详细状态
   */
  async getModelStatus(modelId: string): Promise<ModelStatus> {
    try {
      const response = await fetchAPI<{ success: boolean; data: ModelStatus }>(
        `/api/advanced-models/${encodeURIComponent(modelId)}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取模型状态失败");
    }
  },

  /**
   * 启用模型
   */
  async enableModel(modelId: string): Promise<OperationResponse> {
    try {
      return await fetchAPI<OperationResponse>(
        `/api/advanced-models/${encodeURIComponent(modelId)}/enable`,
        { method: "POST" },
      );
    } catch (error) {
      return handleError(error, "启用模型失败");
    }
  },

  /**
   * 禁用模型
   */
  async disableModel(modelId: string): Promise<OperationResponse> {
    try {
      return await fetchAPI<OperationResponse>(
        `/api/advanced-models/${encodeURIComponent(modelId)}/disable`,
        { method: "POST" },
      );
    } catch (error) {
      return handleError(error, "禁用模型失败");
    }
  },

  /**
   * 部署模型（启用并加载）
   */
  async deployModel(modelId: string): Promise<OperationResponse> {
    try {
      return await fetchAPI<OperationResponse>(
        `/api/advanced-models/${encodeURIComponent(modelId)}/deploy`,
        { method: "POST" },
      );
    } catch (error) {
      return handleError(error, "部署模型失败");
    }
  },

  /**
   * 卸载模型（禁用并释放内存）
   */
  async undeployModel(modelId: string): Promise<OperationResponse> {
    try {
      return await fetchAPI<OperationResponse>(
        `/api/advanced-models/${encodeURIComponent(modelId)}/undeploy`,
        { method: "POST" },
      );
    } catch (error) {
      return handleError(error, "卸载模型失败");
    }
  },

  /**
   * 开始下载模型（后台任务）
   */
  async downloadModel(modelId: string): Promise<{ success: boolean; task_id: string }> {
    try {
      return await fetchAPI<{ success: boolean; task_id: string }>(
        `/api/advanced-models/${encodeURIComponent(modelId)}/download`,
        { method: "POST" },
      );
    } catch (error) {
      return handleError(error, "下载模型失败");
    }
  },

  /**
   * 获取下载进度（SSE）
   * 注意：SSE 连接请使用 EventSource，此函数仅作为端点说明保留
   */
  getDownloadProgressUrl(modelId: string): string {
    return `/api/advanced-models/${encodeURIComponent(modelId)}/download-progress`;
  },

  /**
   * 手动加载模型到内存
   */
  async loadModel(modelId: string): Promise<OperationResponse> {
    try {
      return await fetchAPI<OperationResponse>(
        `/api/advanced-models/${encodeURIComponent(modelId)}/load`,
        { method: "POST" },
      );
    } catch (error) {
      return handleError(error, "加载模型失败");
    }
  },

  /**
   * 卸载模型释放内存
   */
  async unloadModel(modelId: string): Promise<OperationResponse> {
    try {
      return await fetchAPI<OperationResponse>(
        `/api/advanced-models/${encodeURIComponent(modelId)}/unload`,
        { method: "POST" },
      );
    } catch (error) {
      return handleError(error, "卸载模型失败");
    }
  },

  /**
   * 获取系统内存使用情况
   */
  async getSystemMemory(): Promise<MemoryStatus> {
    try {
      const response = await fetchAPI<{ success: boolean; data: MemoryStatus }>(
        "/api/advanced-models/system/memory",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取系统内存失败");
    }
  },
};

export default advancedModelsAPI;
