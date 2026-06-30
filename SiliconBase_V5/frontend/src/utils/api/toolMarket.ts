/**
 * 云端工具市场 API 客户端
 *
 * 【P1 修复】统一使用 fetchAPI，自动携带 token、刷新和 401 处理
 */

import { getAuthToken } from "../auth";
import { fetchAPI } from "./index";

export interface CloudTool {
  tool_id: string;
  name: string;
  description: string;
  version: string;
  author: string;
  category: string;
  tags: string[];
  icon?: string;
  status: string;
  download_count: number;
  rating: number;
  rating_count: number;
  release_date: string;
  last_update: string;
  size_bytes: number;
}

export interface InstalledTool {
  tool_id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  category: string;
  install_date: string;
  source: string;
  auto_update: boolean;
}

export interface UpdateInfo {
  tool_id: string;
  current: string;
  latest: string;
  changelog?: string;
}

export interface InstallTask {
  task_id: string;
  tool_id: string;
  version: string;
  status:
    | "pending"
    | "downloading"
    | "verifying"
    | "installing"
    | "completed"
    | "failed"
    | "rolling_back";
  progress: number;
  message: string;
  error?: string;
}

class ToolMarketAPI {
  // 获取云端工具列表
  async getTools(
    category?: string,
    page: number = 1,
    pageSize: number = 20,
  ): Promise<{ tools: CloudTool[]; total: number }> {
    const params = new URLSearchParams();
    if (category) params.append("category", category);
    params.append("page", page.toString());
    params.append("page_size", pageSize.toString());

    return fetchAPI<{ tools: CloudTool[]; total: number }>(
      `/api/cloud-tools/list?${params.toString()}`,
    );
  }

  // 获取工具详情
  async getToolDetail(
    toolId: string,
    version?: string,
  ): Promise<CloudTool | null> {
    const endpoint = version
      ? `/api/cloud-tools/${encodeURIComponent(toolId)}/${encodeURIComponent(version)}/detail`
      : `/api/cloud-tools/${encodeURIComponent(toolId)}/latest/detail`;

    const data = await fetchAPI<{ data?: CloudTool }>(endpoint);
    return data.data || null;
  }

  // 获取工具版本列表
  async getToolVersions(toolId: string): Promise<string[]> {
    const data = await fetchAPI<{ versions?: Array<{ version: string }> }>(
      `/api/cloud-tools/${encodeURIComponent(toolId)}/versions`,
    );
    return data.versions?.map((v) => v.version) || [];
  }

  // 安装工具
  async installTool(
    toolId: string,
    version: string = "latest",
  ): Promise<{ task_id: string }> {
    return fetchAPI<{ task_id: string }>("/api/tool-market/install", {
      method: "POST",
      body: { tool_id: toolId, version },
    });
  }

  // 获取已安装工具列表
  async getInstalledTools(): Promise<InstalledTool[]> {
    const data = await fetchAPI<{ tools?: InstalledTool[] }>(
      "/api/tool-market/installed",
    );
    return data.tools || [];
  }

  // 卸载工具
  async uninstallTool(toolId: string): Promise<boolean> {
    try {
      await fetchAPI(
        `/api/tool-market/uninstall/${encodeURIComponent(toolId)}`,
        { method: "POST" },
      );
      return true;
    } catch {
      return false;
    }
  }

  // 检查更新
  async checkUpdates(): Promise<UpdateInfo[]> {
    const data = await fetchAPI<{ updates?: UpdateInfo[] }>(
      "/api/tool-market/check-updates",
      {
        method: "POST",
        body: {},
      },
    );
    return data.updates || [];
  }

  // 获取安装任务状态
  async getInstallTask(taskId: string): Promise<InstallTask | null> {
    try {
      return await fetchAPI<InstallTask>(
        `/api/tool-market/task/${encodeURIComponent(taskId)}`,
      );
    } catch {
      return null;
    }
  }

  // 下载工具包（Blob 类型不走 fetchAPI，保留原生 fetch）
  async downloadTool(toolId: string, version: string): Promise<Blob> {
    const token = getAuthToken();
    const response = await fetch(
      `/api/cloud-tools/${encodeURIComponent(toolId)}/${encodeURIComponent(version)}/download`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      },
    );

    if (!response.ok) {
      throw new Error("下载失败");
    }

    return response.blob();
  }

  // 发布工具到云端市场
  async publishTool(tool: {
    tool_id: string;
    name: string;
    description: string;
    version: string;
    code: string;
    author?: string;
    category?: string;
    tags?: string[];
  }): Promise<{ success: boolean; tool_id: string; version: string }> {
    return fetchAPI<{ success: boolean; tool_id: string; version: string }>("/api/cloud-tools/publish", {
      method: "POST",
      body: tool,
    });
  }

  // 检查云端工具更新
  async checkCloudUpdates(): Promise<UpdateInfo[]> {
    const data = await fetchAPI<{ updates?: UpdateInfo[] }>("/api/cloud-tools/check-updates", {
      method: "POST",
      body: {},
    });
    return data.updates || [];
  }

  // 审核通过工具（管理员权限）
  async approveTool(
    toolId: string,
    version: string,
  ): Promise<{ success: boolean; message: string }> {
    return fetchAPI<{ success: boolean; message: string }>(
      `/api/cloud-tools/${encodeURIComponent(toolId)}/${encodeURIComponent(version)}/approve`,
      { method: "POST" },
    );
  }

  // 更新工具到最新版本（复用已有 update 接口）
  async updateTool(toolId: string): Promise<{ success: boolean; message?: string }> {
    return fetchAPI<{ success: boolean; message?: string }>(
      `/api/tool-market/update/${encodeURIComponent(toolId)}`,
      { method: "POST" },
    );
  }

  // 自动更新所有可更新工具
  async autoUpdate(): Promise<{ success: boolean; updated: number; failed: number }> {
    return fetchAPI<{ success: boolean; updated: number; failed: number }>(
      "/api/tool-market/auto-update",
      { method: "POST", body: {} },
    );
  }

  // 检查工具是否已安装
  async isInstalled(toolId: string): Promise<boolean> {
    try {
      const data = await fetchAPI<{ installed?: boolean }>(
        `/api/tool-market/is-installed/${encodeURIComponent(toolId)}`,
      );
      return data.installed || false;
    } catch {
      return false;
    }
  }
}

export const toolMarketAPI = new ToolMarketAPI();
export default toolMarketAPI;
