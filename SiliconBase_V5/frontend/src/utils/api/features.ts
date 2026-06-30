/**
 * 功能开关与系统模式 API
 * 对应后端 /api/features/* 与 /api/mode 端点
 */

import { fetchAPI, handleError } from "./index";
import { configAPI } from "./config";

export interface FeatureStatus {
  id: string;
  name: string;
  description: string;
  category: string;
  enabled: boolean;
  state: string;
  available: boolean;
  configurable: boolean;
  requires_restart: boolean;
  error_message?: string;
  sub_features: Array<Record<string, any>>;
  dependencies: Array<Record<string, any>>;
}

export interface FeatureSummary {
  total: number;
  enabled: number;
  available: number;
  running: number;
  degraded: boolean;
}

export interface FeaturesResponse {
  features: FeatureStatus[];
  summary: FeatureSummary;
}

export interface FeatureDetailResponse {
  feature: FeatureStatus;
  config: Record<string, any>;
  dependencies: DependencyInfo[];
  missing_deps: DependencyInfo[];
  install_guide?: string;
}

export interface DependencyInfo {
  name: string;
  type: string;
  required: boolean;
  feature?: string;
  description?: string;
  status: string;
  version?: string;
  message?: string;
  install_cmd?: string;
  download_url?: string;
  size?: string;
}

export interface DependencyCheckResponse {
  available: DependencyInfo[];
  missing: DependencyInfo[];
  optional: DependencyInfo[];
  errors: DependencyInfo[];
  all_ok: boolean;
}

export interface CategoryInfo {
  id: string;
  name: string;
  description: string;
}

export interface FeatureActionResponse {
  success: boolean;
  feature_id: string;
  message: string;
  requires_restart: boolean;
  new_state: string;
}

export interface InstallResponse {
  success: boolean;
  message: string;
  dependency?: string;
}

export interface ModeResponse {
  success: boolean;
  mode: string;
  message?: string;
}

export const featuresAPI = {
  /**
   * 获取所有功能状态
   */
  async getFeatures(): Promise<FeaturesResponse> {
    try {
      const response = await fetchAPI<{ success: boolean; data: FeaturesResponse }>("/api/features");
      return response.data;
    } catch (error) {
      return handleError(error, "获取功能列表失败");
    }
  },

  /**
   * 获取功能分类
   */
  async getCategories(): Promise<CategoryInfo[]> {
    try {
      const response = await fetchAPI<{ success: boolean; data: { categories: CategoryInfo[] } }>(
        "/api/features/categories",
      );
      return response.data.categories || [];
    } catch (error) {
      return handleError(error, "获取功能分类失败");
    }
  },

  /**
   * 获取特定功能详情
   */
  async getFeature(featureId: string): Promise<FeatureDetailResponse> {
    try {
      const response = await fetchAPI<{ success: boolean; data: FeatureDetailResponse }>(
        `/api/features/${encodeURIComponent(featureId)}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取功能详情失败");
    }
  },

  /**
   * 启用功能
   */
  async enableFeature(featureId: string, confirmRestart: boolean = false): Promise<FeatureActionResponse> {
    try {
      const response = await fetchAPI<{ success: boolean; data: FeatureActionResponse }>(
        `/api/features/${encodeURIComponent(featureId)}/enable`,
        {
          method: "POST",
          body: { confirm_restart: confirmRestart },
        },
      );
      return response.data;
    } catch (error) {
      return handleError(error, "启用功能失败");
    }
  },

  /**
   * 禁用功能
   */
  async disableFeature(featureId: string, confirmRestart: boolean = false): Promise<FeatureActionResponse> {
    try {
      const response = await fetchAPI<{ success: boolean; data: FeatureActionResponse }>(
        `/api/features/${encodeURIComponent(featureId)}/disable`,
        {
          method: "POST",
          body: { confirm_restart: confirmRestart },
        },
      );
      return response.data;
    } catch (error) {
      return handleError(error, "禁用功能失败");
    }
  },

  /**
   * 切换子功能开关（通过 /api/config 直接修改配置）
   * @param featureId - 父功能ID
   * @param subFeatureId - 子功能ID
   * @param configPath - 配置YAML路径
   * @param enabled - 是否启用
   * @returns 操作结果
   */
  async toggleSubFeature(
    featureId: string,
    subFeatureId: string,
    configPath: string,
    enabled: boolean,
  ): Promise<{ success: boolean; message: string }> {
    try {
      const result = await configAPI.updateRawConfig({ [configPath]: enabled });
      return {
        success: result.success,
        message: result.message || `${enabled ? "启用" : "禁用"} ${featureId}.${subFeatureId} 成功`,
      };
    } catch (error) {
      return handleError(error, "切换子功能失败");
    }
  },

  /**
   * 检查功能状态
   */
  async checkFeature(featureId: string): Promise<FeatureActionResponse> {
    try {
      const response = await fetchAPI<{ success: boolean; data: FeatureActionResponse }>(
        `/api/features/${encodeURIComponent(featureId)}/check`,
        {
          method: "POST",
        },
      );
      return response.data;
    } catch (error) {
      return handleError(error, "检查功能状态失败");
    }
  },

  /**
   * 检查所有依赖
   */
  async checkDependencies(): Promise<DependencyCheckResponse> {
    try {
      const response = await fetchAPI<{ success: boolean; data: DependencyCheckResponse }>(
        "/api/features/dependencies/check",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "检查依赖失败");
    }
  },

  /**
   * 获取功能依赖
   */
  async getFeatureDependencies(featureId: string): Promise<DependencyCheckResponse> {
    try {
      const response = await fetchAPI<{ success: boolean; data: DependencyCheckResponse }>(
        `/api/features/${encodeURIComponent(featureId)}/dependencies`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取功能依赖失败");
    }
  },

  /**
   * 安装依赖
   */
  async installDependency(dependencyName: string): Promise<InstallResponse> {
    try {
      const response = await fetchAPI<{ success: boolean; data: InstallResponse }>(
        "/api/features/dependencies/install",
        {
          method: "POST",
          body: { dependency_name: dependencyName },
        },
      );
      return response.data;
    } catch (error) {
      return handleError(error, "安装依赖失败");
    }
  },

  /**
   * 获取依赖安装指南
   */
  async getDependencyGuide(dependencyName: string): Promise<{ guide: string }> {
    try {
      const response = await fetchAPI<{ success: boolean; data: { guide: string } }>(
        `/api/features/dependencies/guide/${encodeURIComponent(dependencyName)}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取安装指南失败");
    }
  },

  /**
   * 刷新功能状态
   */
  async refreshFeatures(): Promise<FeaturesResponse> {
    try {
      const response = await fetchAPI<{ success: boolean; data: FeaturesResponse }>(
        "/api/features/refresh",
        {
          method: "POST",
        },
      );
      return response.data;
    } catch (error) {
      return handleError(error, "刷新功能状态失败");
    }
  },

  /**
   * 获取系统状态（兼容旧版）
   */
  async getSystemStatus(): Promise<Record<string, any>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        "/api/features/system/status",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取系统状态失败");
    }
  },

  /**
   * 配置功能
   */
  async configureFeature(
    featureId: string,
    config: Record<string, any>,
  ): Promise<FeatureActionResponse> {
    try {
      const response = await fetchAPI<{ success: boolean; data: FeatureActionResponse }>(
        `/api/features/${encodeURIComponent(featureId)}/configure`,
        {
          method: "POST",
          body: config,
        },
      );
      return response.data;
    } catch (error) {
      return handleError(error, "配置功能失败");
    }
  },

  /**
   * 获取当前用户工作模式
   */
  async getMode(): Promise<string> {
    try {
      const response = await fetchAPI<{ mode: string }>("/api/mode");
      return response.mode;
    } catch (error) {
      return handleError(error, "获取工作模式失败");
    }
  },

  /**
   * 设置当前用户工作模式
   */
  async setMode(mode: string, reason: string = ""): Promise<ModeResponse> {
    try {
      return await fetchAPI<ModeResponse>("/api/mode", {
        method: "POST",
        body: { mode, reason },
      });
    } catch (error) {
      return handleError(error, "切换工作模式失败");
    }
  },
};

export default featuresAPI;
