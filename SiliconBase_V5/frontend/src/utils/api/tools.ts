/**
 * 工具管理API
 */
import { fetchAPI, handleError } from "./index";

export interface ToolCategory {
  name: string;
  count: number;
  description?: string;
  icon?: string;
  unlock_level?: number;
}

export interface Tool {
  id: string;
  name: string;
  description: string;
  category: string;
  enabled: boolean;
  parameters?: Record<string, any>;
  // 扩展字段 - 用于游戏化和工具状态管理
  deprecated?: boolean;
  duplicate_of?: string;
  executable?: boolean;
  owner?: "system" | "user" | "custom";
  description_full?: string;
  is_duplicate?: boolean;
  xp_value?: number;
  unlock_level?: number;
  rarity?: "common" | "rare" | "epic" | "legendary";
  cooldown?: number;
  daily_limit?: number;
  tags?: string[];
}

export interface ToolWithStatus extends Tool {
  is_loading?: boolean;
  is_error?: boolean;
  error_message?: string;
  last_used?: number;
  use_count?: number;
}

export interface ToolTestResult {
  success: boolean;
  tool_id: string;
  result: any;
  error?: string;
  timestamp: number;
}

export interface RegisterToolResult {
  success: boolean;
  tool_id?: string;
  error?: string;
  warnings?: string[];
}

export const toolsAPI = {
  /**
   * 获取所有工具列表
   */
  async getTools(): Promise<Tool[]> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: { tools: Tool[] };
      }>("/api/tools/");
      return response.data?.tools || [];
    } catch (error) {
      return handleError(error, "获取工具列表失败");
    }
  },

  /**
   * 获取工具分类列表
   */
  async getCategories(): Promise<{ categories: ToolCategory[] }> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: { categories: ToolCategory[] };
      }>("/api/tools/categories");
      return response.data || { categories: [] };
    } catch (error) {
      return handleError(error, "获取工具分类失败");
    }
  },

  /**
   * 获取分类下的工具
   */
  async getToolsByCategory(
    category: string,
  ): Promise<{ category: string; tools: Tool[] }> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: { category: string; tools: Tool[] };
      }>(`/api/tools/category/${encodeURIComponent(category)}`);
      return response.data || { category, tools: [] };
    } catch (error) {
      return handleError(error, "获取工具列表失败");
    }
  },

  /**
   * 获取工具详情
   */
  async getToolDetail(toolId: string): Promise<Tool> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Tool }>(
        `/api/tools/detail/${encodeURIComponent(toolId)}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取工具详情失败");
    }
  },

  /**
   * 搜索工具
   */
  async searchTools(query: string): Promise<{ results: Tool[] }> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: { results: Tool[] };
      }>(`/api/tools/search?q=${encodeURIComponent(query)}`);
      return response.data || { results: [] };
    } catch (error) {
      return handleError(error, "搜索工具失败");
    }
  },

  /**
   * 测试工具
   */
  async testTool(
    toolId: string,
    params: Record<string, any>,
  ): Promise<ToolTestResult> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: ToolTestResult;
      }>(`/api/tools/test/${encodeURIComponent(toolId)}`, {
        method: "POST",
        body: params,
      });
      return response.data;
    } catch (error) {
      return handleError(error, "测试工具失败");
    }
  },

  /**
   * 启用/禁用工具
   */
  async toggleTool(
    toolId: string,
  ): Promise<{ success: boolean; tool_id: string; enabled: boolean }> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: { success: boolean; tool_id: string; enabled: boolean };
      }>(`/api/tools/toggle/${encodeURIComponent(toolId)}`, {
        method: "POST",
      });
      return response.data;
    } catch (error) {
      return handleError(error, "切换工具状态失败");
    }
  },

  /**
   * 删除工具
   */
  async deleteTool(
    toolId: string,
  ): Promise<{ success: boolean; message: string }> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: { success: boolean; message: string };
      }>(`/api/tools/delete/${encodeURIComponent(toolId)}`, {
        method: "POST",
      });
      return response.data;
    } catch (error) {
      return handleError(error, "删除工具失败");
    }
  },

  /**
   * 注册新工具（从代码）
   */
  async registerTool(
    name: string,
    description: string,
    code: string,
    skipSandbox: boolean = false,
  ): Promise<RegisterToolResult> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: RegisterToolResult;
      }>("/api/tools/register", {
        method: "POST",
        body: { name, description, code, skip_sandbox: skipSandbox },
      });
      return response.data;
    } catch (error) {
      return handleError(error, "注册工具失败");
    }
  },

  /**
   * 获取工具详情（标准路径）
   */
  async getTool(toolId: string): Promise<Tool> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Tool }>(
        `/api/tools/${encodeURIComponent(toolId)}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取工具详情失败");
    }
  },

  /**
   * 执行指定工具
   */
  async executeTool(toolId: string, params: Record<string, any>): Promise<any> {
    try {
      const response = await fetchAPI<{ success: boolean; data: any }>(
        `/api/tools/${encodeURIComponent(toolId)}/execute`,
        {
          method: "POST",
          body: params,
        },
      );
      return response.data;
    } catch (error) {
      return handleError(error, "执行工具失败");
    }
  },

  /**
   * 通用执行工具（不指定 tool_id）
   */
  async execute(request: { tool_id: string; params: Record<string, any> }): Promise<any> {
    try {
      const response = await fetchAPI<{ success: boolean; data: any }>("/api/tools/execute", {
        method: "POST",
        body: request,
      });
      return response.data;
    } catch (error) {
      return handleError(error, "执行工具失败");
    }
  },

  /**
   * 验证工具参数
   */
  async validateParams(toolId: string, params: Record<string, any>): Promise<{ valid: boolean; errors?: string[] }> {
    try {
      const response = await fetchAPI<{ success: boolean; data: { valid: boolean; errors?: string[] } }>(
        "/api/tools/validate",
        {
          method: "POST",
          body: { tool_id: toolId, params },
        },
      );
      return response.data;
    } catch (error) {
      return handleError(error, "验证工具参数失败");
    }
  },

  /**
   * 获取工具参数 schema
   */
  async getToolSchema(toolId: string): Promise<Record<string, any>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        `/api/tools/schema/${encodeURIComponent(toolId)}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取工具 schema 失败");
    }
  },

  /**
   * 工具手册 L1 层概览
   */
  async getToolManualL1(): Promise<{ categories: ToolCategory[] }> {
    try {
      const response = await fetchAPI<{ success: boolean; data: { categories: ToolCategory[] } }>(
        "/api/tools/tool-manual/l1",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取工具手册 L1 失败");
    }
  },

  /**
   * 工具手册 L2 层分类内容
   */
  async getToolManualL2(category: string): Promise<Record<string, any>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        `/api/tools/tool-manual/l2/${encodeURIComponent(category)}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取工具手册 L2 失败");
    }
  },

  /**
   * 工具手册 L3 层工具详情
   */
  async getToolManualL3(toolId: string): Promise<Record<string, any>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        `/api/tools/tool-manual/l3/${encodeURIComponent(toolId)}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取工具手册 L3 失败");
    }
  },

  /**
   * 切换工具手册层级
   */
  async switchToolManualLevel(level: string, category?: string, toolId?: string): Promise<{ success: boolean }> {
    try {
      return await fetchAPI<{ success: boolean }>("/api/tools/tool-manual/switch", {
        method: "POST",
        body: { level, category, tool_id: toolId },
      });
    } catch (error) {
      return handleError(error, "切换工具手册层级失败");
    }
  },

  /**
   * 清除工具手册缓存
   */
  async clearToolManualCache(): Promise<{ success: boolean; message: string }> {
    try {
      return await fetchAPI<{ success: boolean; message: string }>("/api/tools/tool-manual/clear-cache", {
        method: "POST",
      });
    } catch (error) {
      return handleError(error, "清除工具手册缓存失败");
    }
  },

  /**
   * 获取工具手册缓存状态
   */
  async getToolManualCacheStatus(): Promise<Record<string, any>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        "/api/tools/tool-manual/cache-status",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取工具手册缓存状态失败");
    }
  },
};
