/**
 * 记忆管理API
 */
import { fetchAPI, handleError } from "./index";

export interface ValueAssessmentV2 {
  dimension_scores: Record<string, number>;
  weighted_total: number;
  overall_grade: string;
  will_affect_behavior: boolean;
  emotional_impact?: Record<string, number>;
  suggested_reflection?: string;
  growth_insights?: string[];
  ethical_notes?: string[];
}

export interface Memory {
  id: string;
  layer: string;
  mem_type: string;
  content: string | { text: string; tags?: string[] };
  scene: string;
  rating: number;
  created_at: string;
  source?: string; // 来源: user/ai/system/reflection/evolution/auto_save
  value_assessment?: ValueAssessmentV2;
  context?: {
    value_assessment_v2?: ValueAssessmentV2;
    [key: string]: any;
  };
}

// 创建记忆请求参数
export interface CreateMemoryParams {
  layer: string;
  mem_type?: string;
  content: string;
  scene?: string;
  source?: string;
  tags?: string[];
  value_assessment?: ValueAssessmentV2;
}

export interface MemoryListResponse {
  memories: Memory[];
  total: number;
  offset: number;
  limit: number;
}

export interface SearchResult {
  content: string;
  metadata: Record<string, any>;
  distance: number;
}

export interface SearchResponse {
  results: SearchResult[];
  query: string;
  error?: string;
}

export interface EvolutionRecord {
  id: string;
  timestamp: string;
  compressed_count: number;
  evolved_count: number;
  status: "pending" | "completed" | "failed";
}

export interface EvolutionResponse {
  success: boolean;
  message: string;
  compressed_count?: number;
  evolved_count?: number;
}

export interface EvolutionHistoryResponse {
  evolutions: EvolutionRecord[];
  total: number;
}

// L5 执行记忆接口定义
export interface ExecutionMemory {
  user_id: string;
  tool_name: string;
  input_params: Record<string, any>;
  output_result: Record<string, any>;
  success: boolean;
  execution_time_ms: number;
  timestamp: string;
  task_id?: string;
  session_id?: string;
  error_code?: string;
  error_message?: string;
}

export interface ExecutionStats {
  user_id: string;
  period_days: number;
  total: number;
  success: number;
  failed: number;
  success_rate: number;
  avg_time_ms: number;
  common_tools: Array<{
    tool_name: string;
    count: number;
    success_rate: number;
    avg_time_ms: number;
  }>;
  common_errors: Array<{
    error_code: string;
    count: number;
  }>;
}

export interface ExecutionListResponse {
  executions: ExecutionMemory[];
  total: number;
  limit: number;
  offset: number;
  layer: string;
}

export interface ExecutionStatsResponse {
  stats: ExecutionStats;
  period_days: number;
  layer: string;
}

export interface GetExecutionsParams {
  tool_name?: string;
  success_only?: boolean;
  limit?: number;
  offset?: number;
}

// 维度筛选参数
export interface DimensionFilterParams {
  dimension_weights?: Record<string, number>;
  /** @deprecated 后端 advanced-search 暂不支持，仅保留在 GET query 中供其他接口使用 */
  min_dimension_scores?: Record<string, number>;
  /** @deprecated 后端 advanced-search 暂不支持，仅保留在 GET query 中供其他接口使用 */
  grades?: string[];
}

// 更新记忆请求参数（与后端 MemoryUpdate 对齐，只发 content/rating）
export interface UpdateMemoryParams {
  content?: string;
  rating?: number;
}

// 获取记忆列表参数
export interface GetMemoriesParams {
  limit?: number;
  offset?: number;
  type?: string;
  layer?: string;
  source?: string; // 来源筛选: user/ai/system/reflection/evolution/auto_save
  dimension_weights?: Record<string, number>;
  min_dimension_scores?: Record<string, number>;
  grades?: string[];
}

// 搜索记忆参数
export interface SearchMemoriesParams extends DimensionFilterParams {
  layer?: string;
  limit?: number;
}

// 会话记忆响应
export interface SessionMemory {
  id: string;
  session_id: string;
  memory_id: string;
  memory_type: "context" | "reference" | "experience" | "preference";
  relevance_score: number;
  used_in_response: boolean;
  created_at: string;
  memory?: Memory;
}

export interface SessionMemoriesResponse {
  session_id: string;
  memories: SessionMemory[];
  total: number;
  total_relevance_score: number;
}

export const memoryAPI = {
  /**
   * 创建单条记忆
   */
  async createMemory(
    params: CreateMemoryParams,
  ): Promise<{ success: boolean; data: Memory }> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Memory }>(
        "/api/memories",
        {
          method: "POST",
          body: {
            content: params.content,
            type: params.mem_type || "chat",
            layer: params.layer,
            scene: params.scene || "",
            source: params.source || "user",
            tags: params.tags,
            value_assessment: params.value_assessment,
          },
        },
      );
      return response;
    } catch (error) {
      return handleError(error, "创建记忆失败");
    }
  },

  /**
   * 批量创建记忆
   */
  async createMemoriesBatch(
    items: CreateMemoryParams[],
  ): Promise<{ success: boolean; created: number; total: number }> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        created: number;
        total: number;
        memory_ids: string[];
      }>("/api/memories/batch", {
        method: "POST",
        body: {
          items: items.map((item) => ({
            content: item.content,
            type: item.mem_type || "chat",
            layer: item.layer,
            scene: item.scene || "",
            source: item.source || "user",
            tags: item.tags,
            value_assessment: item.value_assessment,
          })),
        },
      });
      return response;
    } catch (error) {
      return handleError(error, "批量创建记忆失败");
    }
  },

  /**
   * 获取记忆列表
   */
  async getMemories(params?: GetMemoriesParams): Promise<MemoryListResponse> {
    try {
      const queryParams = new URLSearchParams();
      if (params?.limit) queryParams.set("limit", params.limit.toString());
      if (params?.offset !== undefined)
        queryParams.set("offset", params.offset.toString());
      if (params?.type) queryParams.set("type", params.type);
      if (params?.layer) queryParams.set("layer", params.layer);
      if (params?.source) queryParams.set("source", params.source);

      // 添加维度筛选参数
      if (
        params?.dimension_weights &&
        Object.keys(params.dimension_weights).length > 0
      ) {
        queryParams.set(
          "dimension_weights",
          JSON.stringify(params.dimension_weights),
        );
      }

      if (
        params?.min_dimension_scores &&
        Object.keys(params.min_dimension_scores).length > 0
      ) {
        queryParams.set(
          "min_dimension_scores",
          JSON.stringify(params.min_dimension_scores),
        );
      }

      // 添加等级筛选参数
      if (params?.grades && params.grades.length > 0) {
        queryParams.set("grades", params.grades.join(","));
      }

      const query = queryParams.toString();
      const response = await fetchAPI<{
        success: boolean;
        data: MemoryListResponse;
      }>(`/api/memories${query ? "?" + query : ""}`);
      return response.data;
    } catch (error) {
      return handleError(error, "获取记忆列表失败");
    }
  },

  /**
   * 搜索记忆
   */
  async searchMemories(
    query: string,
    params?: SearchMemoriesParams,
  ): Promise<SearchResponse> {
    try {
      const queryParams = new URLSearchParams();
      queryParams.set("q", encodeURIComponent(query));
      queryParams.set("limit", (params?.limit || 10).toString());

      // 添加维度筛选参数
      if (
        params?.dimension_weights &&
        Object.keys(params.dimension_weights).length > 0
      ) {
        queryParams.set(
          "dimension_weights",
          JSON.stringify(params.dimension_weights),
        );
      }

      if (
        params?.min_dimension_scores &&
        Object.keys(params.min_dimension_scores).length > 0
      ) {
        queryParams.set(
          "min_dimension_scores",
          JSON.stringify(params.min_dimension_scores),
        );
      }

      // 添加等级筛选参数
      if (params?.grades && params.grades.length > 0) {
        queryParams.set("grades", params.grades.join(","));
      }

      const response = await fetchAPI<{
        success: boolean;
        data: SearchResponse;
      }>(`/api/memories/search?${queryParams.toString()}`);
      return response.data;
    } catch (error) {
      return handleError(error, "搜索记忆失败");
    }
  },

  /**
   * 高级搜索记忆（带维度筛选）
   */
  async advancedSearch(
    query: string,
    params: SearchMemoriesParams = {},
  ): Promise<SearchResponse> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: SearchResponse;
      }>("/api/memories/advanced-search", {
        method: "POST",
        body: {
          query,
          layer: params.layer,
          limit: params.limit || 10,
        },
      });
      return response.data;
    } catch (error) {
      return handleError(error, "高级搜索失败");
    }
  },

  /**
   * 删除记忆
   */
  async deleteMemory(
    memoryId: string,
  ): Promise<{ success: boolean; id: string }> {
    try {
      return await fetchAPI(`/api/memories/${encodeURIComponent(memoryId)}`, {
        method: "DELETE",
      });
    } catch (error) {
      return handleError(error, "删除记忆失败");
    }
  },

  /**
   * 更新记忆
   */
  async updateMemory(
    memoryId: string,
    updates: UpdateMemoryParams,
  ): Promise<{ success: boolean; id: string }> {
    try {
      const body = {
        content: updates.content,
        rating: updates.rating,
      };
      return await fetchAPI(`/api/memories/${encodeURIComponent(memoryId)}`, {
        method: "PUT",
        body: body,
      });
    } catch (error) {
      return handleError(error, "更新记忆失败");
    }
  },

  /**
   * 批量删除记忆
   */
  async deleteBatch(
    memoryIds: string[],
  ): Promise<{ success: boolean; deleted: number }> {
    try {
      return await fetchAPI("/api/memories/batch", {
        method: "DELETE",
        body: { ids: memoryIds },
      });
    } catch (error) {
      return handleError(error, "批量删除记忆失败");
    }
  },

  /**
   * 触发记忆进化
   */
  async triggerEvolution(): Promise<EvolutionResponse> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: EvolutionResponse;
      }>("/api/memories/evolve", {
        method: "POST",
      });
      return response.data;
    } catch (error) {
      return handleError(error, "记忆进化失败");
    }
  },

  /**
   * 获取进化历史
   */
  async getEvolutionHistory(
    limit: number = 10,
  ): Promise<EvolutionHistoryResponse> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: EvolutionHistoryResponse;
      }>(`/api/memories/evolution-history?limit=${limit}`);
      return response.data;
    } catch (error) {
      return handleError(error, "获取进化历史失败");
    }
  },

  /**
   * 按维度筛选记忆
   */
  async filterByDimensions(
    dimensions: string[],
    minScores?: Record<string, number>,
    options?: { limit?: number; offset?: number },
  ): Promise<MemoryListResponse> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: MemoryListResponse;
      }>("/api/memories/filter-by-dimensions", {
        method: "POST",
        body: {
          dimensions,
          min_scores: minScores,
          limit: options?.limit || 20,
          offset: options?.offset || 0,
        },
      });
      return response.data;
    } catch (error) {
      return handleError(error, "维度筛选失败");
    }
  },

  /**
   * 按等级筛选记忆
   */
  async filterByGrades(
    grades: string[],
    options?: { limit?: number; offset?: number; layer?: string },
  ): Promise<MemoryListResponse> {
    try {
      const queryParams = new URLSearchParams();
      queryParams.set("grades", grades.join(","));
      if (options?.limit) queryParams.set("limit", options.limit.toString());
      if (options?.offset !== undefined)
        queryParams.set("offset", options.offset.toString());
      if (options?.layer) queryParams.set("layer", options.layer);

      const response = await fetchAPI<{
        success: boolean;
        data: MemoryListResponse;
      }>(`/api/memories/filter-by-grades?${queryParams.toString()}`);
      return response.data;
    } catch (error) {
      return handleError(error, "等级筛选失败");
    }
  },

  // ═══════════════════════════════════════════════════════════════════
  // L5 执行记忆 API
  // ═══════════════════════════════════════════════════════════════════

  /**
   * 获取L5执行轨迹列表
   */
  async getExecutions(
    params?: GetExecutionsParams,
  ): Promise<ExecutionListResponse> {
    try {
      const queryParams = new URLSearchParams();
      if (params?.limit) queryParams.set("limit", params.limit.toString());
      if (params?.offset !== undefined)
        queryParams.set("offset", params.offset.toString());
      if (params?.tool_name) queryParams.set("tool_name", params.tool_name);
      if (params?.success_only !== undefined)
        queryParams.set("success_only", params.success_only.toString());

      const query = queryParams.toString();
      const response = await fetchAPI<{
        success: boolean;
        data: ExecutionListResponse;
      }>(`/api/memories/executions${query ? "?" + query : ""}`);
      return response.data;
    } catch (error) {
      return handleError(error, "获取执行轨迹失败");
    }
  },

  /**
   * 获取L5执行统计
   */
  async getExecutionStats(days: number = 30): Promise<ExecutionStatsResponse> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: ExecutionStatsResponse;
      }>(`/api/memories/executions/stats?days=${days}`);
      return response.data;
    } catch (error) {
      return handleError(error, "获取执行统计失败");
    }
  },

  /**
   * 删除L5执行记录
   */
  async deleteExecution(
    executionId: string,
  ): Promise<{ success: boolean; id: string }> {
    try {
      return await fetchAPI(
        `/api/memories/executions/${encodeURIComponent(executionId)}`,
        {
          method: "DELETE",
        },
      );
    } catch (error) {
      return handleError(error, "删除执行记录失败");
    }
  },

  /**
   * 批量删除L5执行记录
   */
  async deleteExecutionsBatch(
    executionIds: string[],
  ): Promise<{ success: boolean; deleted: number }> {
    try {
      return await fetchAPI("/api/memories/executions/batch-delete", {
        method: "POST",
        body: { ids: executionIds },
      });
    } catch (error) {
      return handleError(error, "批量删除执行记录失败");
    }
  },

  /**
   * 获取会话相关记忆
   * GET /api/memories/by-session/{sessionId}
   */
  async getSessionMemories(
    sessionId: string,
  ): Promise<SessionMemoriesResponse> {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: SessionMemoriesResponse;
      }>(`/api/memories/by-session/${encodeURIComponent(sessionId)}`);
      return response.data;
    } catch (error) {
      return handleError(error, "获取会话记忆失败");
    }
  },

  /**
   * 标记记忆重要性
   */
  async markMemoryImportant(
    memoryId: string,
    important: boolean,
  ): Promise<{ success: boolean; id: string }> {
    try {
      return await fetchAPI(
        `/api/memories/${encodeURIComponent(memoryId)}/important`,
        {
          method: "PUT",
          body: { important },
        },
      );
    } catch (error) {
      return handleError(error, "标记记忆重要性失败");
    }
  },

  // ═══════════════════════════════════════════════════════════════════
  // 记忆可视化 API
  // ═══════════════════════════════════════════════════════════════════

  /**
   * 获取记忆流动数据
   */
  async getVizFlow(limit: number = 100): Promise<Record<string, any>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        `/api/memories/viz/flow?limit=${limit}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取记忆流动数据失败");
    }
  },

  /**
   * 获取记忆关联图谱数据
   */
  async getVizGraph(limit: number = 100): Promise<Record<string, any>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        `/api/memories/viz/graph?limit=${limit}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取记忆关联图谱失败");
    }
  },

  /**
   * 获取记忆统计数据
   */
  async getVizStats(): Promise<Record<string, any>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        "/api/memories/viz/stats",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取记忆统计数据失败");
    }
  },

  /**
   * 获取记忆时间线
   */
  async getVizTimeline(limit: number = 50): Promise<Array<Record<string, any>>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Array<Record<string, any>> }>(
        `/api/memories/viz/timeline?limit=${limit}`,
      );
      return response.data || [];
    } catch (error) {
      return handleError(error, "获取记忆时间线失败");
    }
  },

  /**
   * 获取记忆来源统计
   */
  async getSourceStats(): Promise<Record<string, any>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        "/api/memories/source-stats",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取记忆来源统计失败");
    }
  },

  /**
   * L4 向量记忆搜索
   */
  async vectorSearch(
    query: string,
    limit: number = 10,
  ): Promise<Array<{ content: string; metadata: Record<string, any>; distance: number }>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Array<{ content: string; metadata: Record<string, any>; distance: number }> }>(
        `/api/memory/vector/search?q=${encodeURIComponent(query)}&limit=${limit}`,
      );
      return response.data || [];
    } catch (error) {
      return handleError(error, "向量记忆搜索失败");
    }
  },

  // ═══════════════════════════════════════════════════════════════════
  // 记忆图谱 API
  // ═══════════════════════════════════════════════════════════════════

  /**
   * 记忆图谱根路径
   */
  async getGraphOverview(): Promise<Record<string, any>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        "/api/memories/graph",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取记忆图谱概览失败");
    }
  },

  /**
   * 添加记忆节点
   */
  async addGraphNode(node: {
    memory_id?: string;
    label?: string;
    type?: string;
    metadata?: Record<string, any>;
  }): Promise<{ success: boolean; node_id: string }> {
    try {
      return await fetchAPI<{ success: boolean; node_id: string }>("/api/memories/graph/node", {
        method: "POST",
        body: node,
      });
    } catch (error) {
      return handleError(error, "添加记忆节点失败");
    }
  },

  /**
   * 添加记忆关系
   */
  async addGraphRelation(relation: {
    source_id: string;
    target_id: string;
    relation_type: string;
    strength?: number;
  }): Promise<{ success: boolean; relation_id: string }> {
    try {
      return await fetchAPI<{ success: boolean; relation_id: string }>(
        "/api/memories/graph/relation",
        {
          method: "POST",
          body: relation,
        },
      );
    } catch (error) {
      return handleError(error, "添加记忆关系失败");
    }
  },

  /**
   * 联想回忆
   */
  async getRelatedMemories(memoryId: string, limit: number = 10): Promise<Record<string, any>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        `/api/memories/graph/related/${encodeURIComponent(memoryId)}?limit=${limit}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取联想回忆失败");
    }
  },

  /**
   * 查找推理路径
   */
  async findGraphPath(sourceId: string, targetId: string): Promise<Record<string, any>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        `/api/memories/graph/path?source_id=${encodeURIComponent(sourceId)}&target_id=${encodeURIComponent(targetId)}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "查找推理路径失败");
    }
  },

  /**
   * 获取可视化数据
   */
  async getGraphVisualization(params?: {
    user_id?: string;
    depth?: number;
    limit?: number;
  }): Promise<Record<string, any>> {
    try {
      const query = new URLSearchParams();
      if (params?.user_id) query.set("user_id", params.user_id);
      if (params?.depth !== undefined) query.set("depth", String(params.depth));
      if (params?.limit !== undefined) query.set("limit", String(params.limit));
      const queryString = query.toString();
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        `/api/memories/graph/visualization${queryString ? "?" + queryString : ""}`,
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取图谱可视化数据失败");
    }
  },

  /**
   * 获取图谱统计信息
   */
  async getGraphStats(): Promise<Record<string, any>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        "/api/memories/graph/stats",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取图谱统计失败");
    }
  },

  /**
   * 自动发现关系
   */
  async discoverGraphRelations(): Promise<{ success: boolean; discovered: number }> {
    try {
      return await fetchAPI<{ success: boolean; discovered: number }>(
        "/api/memories/graph/discover",
        { method: "POST" },
      );
    } catch (error) {
      return handleError(error, "自动发现关系失败");
    }
  },

  /**
   * 导出图谱数据
   */
  async exportGraph(): Promise<Record<string, any>> {
    try {
      const response = await fetchAPI<{ success: boolean; data: Record<string, any> }>(
        "/api/memories/graph/export",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "导出图谱数据失败");
    }
  },
};
