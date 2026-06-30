/**
 * 提示词管理API
 * 用于前端获取模块列表、保存模块选择、预览提示词等
 */

import { fetchAPI } from "./index";

// 模块信息接口
export interface PromptModule {
  id: string;
  name: string;
  description: string;
  optional: boolean;
  default: boolean;
  order: number;
  category: "system" | "modules";
  content?: string;
  is_user_override?: boolean;
}

// 角色信息接口
export interface RoleInfo {
  id: string;
  name: string;
  description: string;
}

// 提示词构建结果
export interface PromptBuildResult {
  prompt: string;
  modules_used: string[];
  estimated_tokens: number;
  variables_used: Record<string, string>;
}

// 前端完整配置
export interface PromptFrontendConfig {
  modules: PromptModule[];
  roles: RoleInfo[];
  user_selection: string[];
  role_default: Record<string, string[]>;
}

// 保存模块响应
export interface SaveModuleResponse {
  success: boolean;
  message: string;
  module_id: string;
  mode: "user" | "global";
  is_admin: boolean;
}

// 管理员状态响应
export interface AdminStatusResponse {
  success: boolean;
  is_admin: boolean;
  user_id: string;
}

// 用户配置信息
export interface UserInfo {
  user_id: string;
  is_admin: boolean;
}

// 完整配置响应（带用户信息）
export interface ConfigWithUserInfo {
  modules: {
    system: PromptModule[];
    optional: PromptModule[];
  };
  roles: string[];
  user_selection: {
    enabled_modules: string[];
    role: string;
  };
  role_default: Record<string, string[]>;
  user_info: UserInfo;
}

/**
 * 获取所有可用模块
 * @param role 角色ID
 */
export const getModules = async (
  role: string = "assistant",
): Promise<PromptModule[]> => {
  try {
    return fetchAPI<PromptModule[]>(`/api/prompt/modules?role=${role}`);
  } catch (error) {
    console.error("[PromptAPI] 获取模块列表失败:", error);
    throw error;
  }
};

/**
 * 获取所有可用角色
 */
export const getRoles = async (): Promise<RoleInfo[]> => {
  try {
    return fetchAPI<RoleInfo[]>("/api/prompt/roles");
  } catch (error) {
    console.error("[PromptAPI] 获取角色列表失败:", error);
    throw error;
  }
};

/**
 * 获取角色的默认模块
 * @param role 角色ID
 */
export const getDefaultModules = async (role: string): Promise<string[]> => {
  try {
    const response = await fetchAPI<{ default_modules: string[] }>(
      `/api/prompt/default-modules/${role}`,
    );
    return response.default_modules;
  } catch (error) {
    console.error("[PromptAPI] 获取默认模块失败:", error);
    throw error;
  }
};

/**
 * 获取用户的模块选择
 * @param userId 用户ID
 * @param role 角色ID
 */
export const getUserSelection = async (
  userId: string,
  role: string = "assistant",
): Promise<string[]> => {
  try {
    const response = await fetchAPI<{ selected_modules: string[] }>(
      `/api/prompt/user-selection/${userId}?role=${role}`,
    );
    return response.selected_modules;
  } catch (error) {
    console.error("[PromptAPI] 获取用户选择失败:", error);
    throw error;
  }
};

/**
 * 保存用户的模块选择
 * @param userId 用户ID
 * @param selectedModules 选中的模块ID列表
 */
export const saveUserSelection = async (
  userId: string,
  selectedModules: string[],
): Promise<{ success: boolean; message: string }> => {
  try {
    return fetchAPI<{ success: boolean; message: string }>(
      "/api/prompt/save-selection",
      {
        method: "POST",
        body: {
          user_id: userId,
          selected_modules: selectedModules,
        },
      },
    );
  } catch (error) {
    console.error("[PromptAPI] 保存用户选择失败:", error);
    throw error;
  }
};

/**
 * 构建提示词（预览）
 * @param role 角色
 * @param selectedModules 选中的模块
 * @param userId 用户ID
 * @param variables 变量
 */
export const buildPrompt = async (
  role: string = "assistant",
  selectedModules?: string[],
  userId?: string,
  variables?: Record<string, string>,
): Promise<PromptBuildResult> => {
  try {
    return fetchAPI<PromptBuildResult>("/api/prompt/build", {
      method: "POST",
      body: {
        role,
        selected_modules: selectedModules,
        user_id: userId,
        variables,
      },
    });
  } catch (error) {
    console.error("[PromptAPI] 构建提示词失败:", error);
    throw error;
  }
};

/**
 * 预览单个模块内容
 * @param moduleId 模块ID
 */
export const previewModule = async (
  moduleId: string,
): Promise<{
  module_id: string;
  content: string;
  is_user_override?: boolean;
}> => {
  try {
    return fetchAPI<{
      module_id: string;
      content: string;
      is_user_override?: boolean;
    }>("/api/prompt/preview-module", {
      method: "POST",
      body: { module_id: moduleId },
    });
  } catch (error) {
    console.error("[PromptAPI] 预览模块失败:", error);
    throw error;
  }
};

/**
 * 获取前端完整配置
 * @param userId 用户ID
 * @param role 角色
 */
export const getFrontendConfig = async (
  userId?: string,
  role: string = "assistant",
): Promise<ConfigWithUserInfo> => {
  try {
    const params = new URLSearchParams();
    if (userId) params.append("user_id", userId);
    params.append("role", role);

    return fetchAPI<ConfigWithUserInfo>(
      `/api/prompt/config-for-frontend?${params.toString()}`,
    );
  } catch (error) {
    console.error("[PromptAPI] 获取前端配置失败:", error);
    throw error;
  }
};

/**
 * 热重载配置（管理员用）
 */
export const reloadConfig = async (): Promise<{
  success: boolean;
  message: string;
}> => {
  try {
    return fetchAPI<{ success: boolean; message: string }>(
      "/api/prompt/reload",
    );
  } catch (error) {
    console.error("[PromptAPI] 重载配置失败:", error);
    throw error;
  }
};

/**
 * 保存模块内容
 * @param moduleId 模块ID
 * @param content 模块内容
 * @param mode 保存模式：'user'（默认）或 'global'
 */
export const saveModule = async (
  moduleId: string,
  content: string,
  mode: "user" | "global" = "user",
): Promise<SaveModuleResponse> => {
  try {
    return fetchAPI<SaveModuleResponse>("/api/prompt/modules", {
      method: "POST",
      body: {
        module_id: moduleId,
        content: content,
        mode: mode,
      },
    });
  } catch (error) {
    console.error("[PromptAPI] 保存模块失败:", error);
    throw error;
  }
};

/**
 * 检查当前用户是否为管理员
 */
export const checkAdminStatus = async (): Promise<AdminStatusResponse> => {
  try {
    return fetchAPI<AdminStatusResponse>("/api/prompt/check-admin");
  } catch (error) {
    console.error("[PromptAPI] 检查管理员状态失败:", error);
    throw error;
  }
};

/**
 * 获取用户模块配置（用户级覆盖）
 * @param moduleId 模块ID
 */
export const getUserModuleConfig = async (
  moduleId: string,
): Promise<{
  success: boolean;
  module_id: string;
  config: any;
  has_override: boolean;
}> => {
  try {
    return fetchAPI<{
      success: boolean;
      module_id: string;
      config: any;
      has_override: boolean;
    }>(`/api/prompt/user-module-config/${moduleId}`);
  } catch (error) {
    console.error("[PromptAPI] 获取用户模块配置失败:", error);
    throw error;
  }
};

/**
 * 删除用户模块配置（恢复使用全局配置）
 * @param moduleId 模块ID
 */
export const deleteUserModuleConfig = async (
  moduleId: string,
): Promise<{
  success: boolean;
  message: string;
  module_id: string;
}> => {
  try {
    return fetchAPI<{
      success: boolean;
      message: string;
      module_id: string;
    }>(`/api/prompt/user-module-config/${moduleId}`, {
      method: "DELETE",
    });
  } catch (error) {
    console.error("[PromptAPI] 删除用户模块配置失败:", error);
    throw error;
  }
};

// ========== 失败分析API ==========

/**
 * 获取失败统计数据
 * @param days 统计天数
 * @returns CamelCase格式的失败统计数据
 */
export const getFailureStats = async (
  days: number = 7,
): Promise<{
  periodDays: number;
  totalFailures: number;
  byCause: Record<
    string,
    {
      count: number;
      examples: {
        task: string;
        explanation: string;
        patch?: string;
        suggestedFix?: string;
      }[];
    }
  >;
  byVersion: Record<string, { failures: number }>;
  topFailingTasks: [string, number][];
  generatedAt: string;
}> => {
  try {
    // 后端返回 { success, data: FailureStatsResponse }
    const response = await fetchAPI<{
      success: boolean;
      data: {
        periodDays: number;
        totalFailures: number;
        byCause: Record<string, any>;
        byVersion: Record<string, any>;
        topFailingTasks: [string, number][];
        generatedAt: string;
      };
    }>(`/api/stats/failures?days=${days}`);

    if (!response.success) {
      throw new Error("获取失败统计数据失败");
    }

    return response.data;
  } catch (error) {
    console.error("[PromptAPI] 获取失败统计失败:", error);
    throw error;
  }
};

/**
 * 生成每日分析报告
 * @returns Markdown格式的报告
 */
export const generateDailyReport = async (): Promise<string> => {
  try {
    // 后端返回 { success, data: { report: string } }
    const response = await fetchAPI<{
      success: boolean;
      data: { report: string };
    }>("/api/stats/daily-report");

    if (!response.success) {
      throw new Error("生成每日报告失败");
    }

    return response.data.report;
  } catch (error) {
    console.error("[PromptAPI] 生成每日报告失败:", error);
    throw error;
  }
};

// 导出API对象
export const promptAPI = {
  getModules,
  getRoles,
  getDefaultModules,
  getUserSelection,
  saveUserSelection,
  buildPrompt,
  previewModule,
  getFrontendConfig,
  reloadConfig,
  saveModule,
  checkAdminStatus,
  getUserModuleConfig,
  deleteUserModuleConfig,
  getFailureStats,
  generateDailyReport,
};
