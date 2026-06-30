/**
 * 阶段锚点管理API
 *
 * 【API端点】
 * - GET /api/tasks/{taskId}/anchors - 获取任务的阶段锚点列表
 * - POST /api/tasks/{taskId}/anchors - 创建新的阶段锚点
 * - PUT /api/tasks/{taskId}/anchors/{anchorId} - 更新阶段锚点
 * - DELETE /api/tasks/{taskId}/anchors/{anchorId} - 删除阶段锚点
 * - POST /api/tasks/{taskId}/continue - 从指定锚点继续执行
 * - POST /api/tasks/{taskId}/rollback - 回滚到指定锚点
 */

import { fetchAPI, handleError } from "./index";
import { PhaseAnchor, AnchorStatus } from "../../components/PhaseAnchorPanel";

export type { PhaseAnchor, AnchorStatus };

// 创建锚点请求参数（适配后端 PhaseAnchorCreate）
export interface CreateAnchorParams {
  phase: string;
  description: string;
  title?: string;
  status?: AnchorStatus;
  position?: number;
  checkpoint_data?: Record<string, any>;
  tags?: string[];
}

// 更新锚点请求参数（适配后端 PhaseAnchorUpdate）
export interface UpdateAnchorParams {
  phase?: string;
  description?: string;
  title?: string;
  status?: AnchorStatus;
  position?: number;
  checkpoint_data?: Record<string, any>;
  tags?: string[];
}

// 锚点列表响应
export interface AnchorListResponse {
  anchors: PhaseAnchor[];
  total: number;
}

// 继续执行请求参数
export interface ContinueFromAnchorParams {
  anchor_id: string;
  params?: Record<string, any>;
}

// 回滚请求参数
export interface RollbackParams {
  anchor_id: string;
  preserve_state?: boolean;
}

// 阶段锚点API
export const phaseAnchorAPI = {
  /**
   * 获取任务的阶段锚点列表
   */
  async getAnchors(taskId: string): Promise<AnchorListResponse> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        anchors: PhaseAnchor[];
        total: number;
      }>(`/api/tasks/${encodeURIComponent(taskId)}/anchors`);
      return { anchors: response.anchors || [], total: response.total || 0 };
    } catch (error) {
      return handleError(error, "获取阶段锚点失败");
    }
  },

  /**
   * 获取单个锚点详情（后端未提供 GET 单条接口，通过列表过滤实现）
   */
  async getAnchor(taskId: string, anchorId: string): Promise<PhaseAnchor> {
    try {
      const list = await this.getAnchors(taskId);
      const anchor = list.anchors.find((a) => a.id === anchorId);
      if (!anchor) {
        throw new Error("锚点不存在");
      }
      return anchor;
    } catch (error) {
      return handleError(error, "获取锚点详情失败");
    }
  },

  /**
   * 创建新的阶段锚点
   */
  async createAnchor(
    taskId: string,
    params: CreateAnchorParams,
  ): Promise<{ success: boolean; data: PhaseAnchor }> {
    try {
      const body = {
        title: params.title || params.phase,
        phase: params.phase,
        description: params.description,
        status: params.status || "active",
        position: params.position ?? 0,
        metadata: {
          checkpoint_data: params.checkpoint_data,
          tags: params.tags || [],
        },
      };
      const response = await fetchAPI<{ success: boolean; anchor: PhaseAnchor }>(
        `/api/tasks/${encodeURIComponent(taskId)}/anchors`,
        {
          method: "POST",
          body,
        },
      );
      return { success: response.success, data: response.anchor };
    } catch (error) {
      return handleError(error, "创建锚点失败");
    }
  },

  /**
   * 更新阶段锚点
   */
  async updateAnchor(
    taskId: string,
    anchorId: string,
    params: UpdateAnchorParams,
  ): Promise<{ success: boolean; data: PhaseAnchor }> {
    try {
      const body: Record<string, any> = {};
      if (params.title !== undefined) body.title = params.title;
      if (params.phase !== undefined) body.phase = params.phase;
      if (params.description !== undefined) body.description = params.description;
      if (params.status !== undefined) body.status = params.status;
      if (params.position !== undefined) body.position = params.position;
      if (params.checkpoint_data !== undefined || params.tags !== undefined) {
        body.metadata = {
          ...(params.checkpoint_data !== undefined && { checkpoint_data: params.checkpoint_data }),
          ...(params.tags !== undefined && { tags: params.tags }),
        };
      }
      const response = await fetchAPI<{ success: boolean; anchor: PhaseAnchor }>(
        `/api/tasks/${encodeURIComponent(taskId)}/anchors/${encodeURIComponent(anchorId)}`,
        {
          method: "PUT",
          body,
        },
      );
      return { success: response.success, data: response.anchor };
    } catch (error) {
      return handleError(error, "更新锚点失败");
    }
  },

  /**
   * 删除阶段锚点
   */
  async deleteAnchor(
    taskId: string,
    anchorId: string,
  ): Promise<{ success: boolean; id: string }> {
    try {
      const response = await fetchAPI<{ success: boolean; deleted_id: string }>(
        `/api/tasks/${encodeURIComponent(taskId)}/anchors/${encodeURIComponent(anchorId)}`,
        {
          method: "DELETE",
        },
      );
      return { success: response.success, id: response.deleted_id };
    } catch (error) {
      return handleError(error, "删除锚点失败");
    }
  },

  /**
   * 批量删除锚点
   */
  async deleteAnchorsBatch(
    taskId: string,
    anchorIds: string[],
  ): Promise<{ success: boolean; deleted: number }> {
    try {
      // 后端 /batch 是“替换整组锚点”，语义不同；这里通过循环单删实现批量删除
      let deleted = 0;
      for (const anchorId of anchorIds) {
        const result = await this.deleteAnchor(taskId, anchorId);
        if (result.success) deleted += 1;
      }
      return { success: true, deleted };
    } catch (error) {
      return handleError(error, "批量删除锚点失败");
    }
  },

  /**
   * 从指定锚点继续执行
   */
  async continueFromAnchor(
    taskId: string,
    params: ContinueFromAnchorParams,
  ): Promise<{ success: boolean; message: string; task_id: string; anchor_id: string }> {
    try {
      return await fetchAPI<{
        success: boolean;
        message: string;
        task_id: string;
        anchor_id: string;
      }>(`/api/tasks/${encodeURIComponent(taskId)}/continue`, {
        method: "POST",
        body: params,
      });
    } catch (error) {
      return handleError(error, "继续执行失败");
    }
  },

  /**
   * 回滚到指定锚点
   */
  async rollbackToAnchor(
    taskId: string,
    params: RollbackParams,
  ): Promise<{ success: boolean; message: string; task_id: string; anchor_id: string }> {
    try {
      return await fetchAPI<{
        success: boolean;
        message: string;
        task_id: string;
        anchor_id: string;
      }>(`/api/tasks/${encodeURIComponent(taskId)}/rollback`, {
        method: "POST",
        body: params,
      });
    } catch (error) {
      return handleError(error, "回滚失败");
    }
  },

  /**
   * 设置锚点状态
   */
  async setAnchorStatus(
    taskId: string,
    anchorId: string,
    status: AnchorStatus,
  ): Promise<{ success: boolean; data: PhaseAnchor }> {
    return this.updateAnchor(taskId, anchorId, { status });
  },

  /**
   * 获取锚点历史记录
   */
  async getAnchorHistory(
    taskId: string,
    anchorId: string,
  ): Promise<{
    success: boolean;
    data: {
      anchor: PhaseAnchor;
      history: Array<{ timestamp: string; action: string; user?: string }>;
    };
  }> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: {
          anchor: PhaseAnchor;
          history: Array<{ timestamp: string; action: string; user?: string }>;
        };
      }>(
        `/api/tasks/${encodeURIComponent(taskId)}/anchors/${encodeURIComponent(anchorId)}/history`,
      );
      return response;
    } catch (error) {
      return handleError(error, "获取锚点历史失败");
    }
  },
};

export default phaseAnchorAPI;
