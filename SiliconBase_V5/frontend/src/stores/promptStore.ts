/**
 * Prompt Store - SiliconBase V5
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 功能：
 *   ✓ 管理所有提示词模块的状态
 *   ✓ 与后端API通信（变体切换、失败统计）
 *   ✓ Token预算跟踪
 *
 * 注意：后端API返回camelCase格式数据
 */

import { create } from "zustand";
import { fetchAPI } from "../utils/api";

// ═══════════════════════════════════════════════════
// 类型定义
// ═══════════════════════════════════════════════════

export interface BudgetCategory {
  name: string;
  budget: number;
  used: number;
  percentage: number;
  color: string;
  truncated?: boolean;
}

export interface PromptModule {
  id: string;
  name: string;
  description: string;
  content: string;
  estimatedTokens: number;
  variants?: PromptVariant[];
  currentVariant?: string;
}

export interface PromptVariant {
  id: string;
  name: string;
  description: string;
  tokenCount: number;
  failureRate: number;
  isDefault: boolean;
  content?: string;
}

export interface FailureStats {
  total: number;
  byCategory: Record<string, number>;
  recent7Days: number;
  trend: "up" | "down" | "stable";
  topIssues: Array<{
    cause: string;
    count: number;
    suggestion: string;
  }>;
}

// ═══════════════════════════════════════════════════
// 默认状态
// ═══════════════════════════════════════════════════

const DEFAULT_BUDGET_CATEGORIES: BudgetCategory[] = [
  {
    name: "基础设定",
    budget: 1500,
    used: 0,
    percentage: 0,
    color: "#3b82f6",
    truncated: false,
  },
  {
    name: "感知输入",
    budget: 600,
    used: 0,
    percentage: 0,
    color: "#10b981",
    truncated: false,
  },
  {
    name: "记忆经验",
    budget: 1200,
    used: 0,
    percentage: 0,
    color: "#8b5cf6",
    truncated: false,
  },
  {
    name: "认知辅助",
    budget: 1000,
    used: 0,
    percentage: 0,
    color: "#f59e0b",
    truncated: false,
  },
  {
    name: "任务管理",
    budget: 200,
    used: 0,
    percentage: 0,
    color: "#ef4444",
    truncated: false,
  },
  {
    name: "个性化",
    budget: 100,
    used: 0,
    percentage: 0,
    color: "#ec4899",
    truncated: false,
  },
  {
    name: "弱连接",
    budget: 100,
    used: 0,
    percentage: 0,
    color: "#06b6d4",
    truncated: false,
  },
  {
    name: "预留",
    budget: 400,
    used: 0,
    percentage: 0,
    color: "#6366f1",
    truncated: false,
  },
];

// ═══════════════════════════════════════════════════
// API 调用函数
// ═══════════════════════════════════════════════════

async function fetchWithError<T>(
  endpoint: string,
  options?: Parameters<typeof fetchAPI>[1],
): Promise<T> {
  const data = await fetchAPI<any>(endpoint, options);

  // 检查统一响应格式
  if (
    data &&
    typeof data.success === "boolean" &&
    !data.success &&
    data.error
  ) {
    throw new Error(data.error);
  }

  return data as T;
}

async function fetchModuleVariants(moduleId: string): Promise<PromptVariant[]> {
  // 注意：使用 /api/prompt-variants 避免与 /api/prompt 冲突
  const response = await fetchWithError<{ variants?: PromptVariant[] }>(
    `/api/prompt-variants/${encodeURIComponent(moduleId)}`,
  );
  // 后端返回CamelCase格式: { success, moduleId, variants: [{ id, name, tokenCount, ... }] }
  return response.variants || [];
}

async function fetchPromptModules(): Promise<
  Array<{ id: string; name: string; description: string; content?: string }>
> {
  // 从真实的提示词API加载模块列表和内容
  try {
    const response = await fetchWithError<{
      data?: Array<{
        id: string;
        name: string;
        description: string;
        content?: string;
      }>;
    }>(`/api/prompt/modules?role=assistant`);
    // 后端返回: { success, data: [{ id, name, description, content, ... }] }
    return response.data || [];
  } catch (error) {
    console.warn("[PromptStore] 加载提示词模块失败:", error);
    return [];
  }
}

async function switchVariantApi(
  moduleId: string,
  variantId: string,
): Promise<{ content: string; tokenCount: number }> {
  const response = await fetchWithError<{
    content?: string;
    tokenCount?: number;
  }>(`/api/prompt-variants/${encodeURIComponent(moduleId)}/switch`, {
    method: "POST",
    body: { variantId }, // CamelCase请求体
  });
  // 后端返回CamelCase: { success, moduleId, variantId, content, tokenCount }
  return {
    content: response.content || "",
    tokenCount: response.tokenCount || 0,
  };
}

async function fetchFailureStats(): Promise<FailureStats> {
  const response = await fetchWithError<any>(`/api/stats/failures?days=7`);
  // 后端返回CamelCase格式: { success, data: { periodDays, totalFailures, byCause, topFailingTasks, ... } }
  const stats = response.data || {};

  // 转换后端字段名到前端格式
  // byCause -> byCategory (根因映射到类别)
  const byCategory: Record<string, number> = {};
  if (stats.byCause) {
    Object.entries(stats.byCause).forEach(([cause, data]: [string, any]) => {
      byCategory[cause] = data.count || 0;
    });
  }

  // topFailingTasks -> topIssues
  const topIssues = (stats.topFailingTasks || []).map(
    (task: [string, number]) => ({
      cause: task[0],
      count: task[1],
      suggestion: `检查${task[0]}相关提示词配置`,
    }),
  );

  return {
    total: stats.totalFailures || 0,
    byCategory,
    recent7Days: stats.totalFailures || 0, // 使用totalFailures作为最近7天统计
    trend: "stable", // 后端暂无趋势计算，默认稳定
    topIssues,
  };
}

async function fetchDailyReport(): Promise<string> {
  const response = await fetchWithError<{ data?: { report?: string } }>(
    `/api/stats/daily-report`,
  );
  // 后端返回: { success, data: { report: string } }
  return response.data?.report || "";
}

async function saveCustomContentApi(
  moduleId: string,
  content: string,
  userId: string = "default",
): Promise<boolean> {
  const response = await fetchWithError<{ success: boolean }>(
    `/api/prompt-variants/${encodeURIComponent(moduleId)}/save`,
    {
      method: "POST",
      body: { content, userId }, // CamelCase
    },
  );
  // 后端返回: { success, moduleId, message }
  return response.success;
}

async function resetToDefaultApi(
  moduleId: string,
  userId: string = "default",
): Promise<{ content: string; tokenCount: number }> {
  const response = await fetchWithError<{ content?: string }>(
    `/api/prompt-variants/${encodeURIComponent(moduleId)}/reset?userId=${encodeURIComponent(userId)}`,
    {
      method: "POST",
    },
  );
  // 后端返回: { success, moduleId, content, message }
  return {
    content: response.content || "",
    tokenCount: response.content ? estimateTokens(response.content) : 0,
  };
}

// ═══════════════════════════════════════════════════
// 本地Token估算（客户端备份方案）
// ═══════════════════════════════════════════════════

function estimateTokens(text: string): number {
  // 与后端保持一致：中文字符约1.5 tokens，英文约0.25 tokens
  let count = 0;
  for (const char of text) {
    if (/[\u4e00-\u9fff]/.test(char)) {
      count += 1.5;
    } else {
      count += 0.25;
    }
  }
  return Math.ceil(count);
}

// ═══════════════════════════════════════════════════
// Zustand Store
// ═══════════════════════════════════════════════════

interface PromptState {
  modules: Record<string, PromptModule>;
  budgetCategories: BudgetCategory[];
  failureStats: FailureStats | null;
  dailyReport: string | null;
  isLoading: boolean;
  error: string | null;
  editingContent: Record<string, string>;
  hasUnsavedChanges: Record<string, boolean>;

  loadModules: () => Promise<void>;
  loadVariants: (moduleId: string) => Promise<void>;
  switchVariant: (moduleId: string, variantId: string) => Promise<void>;
  updateContent: (moduleId: string, content: string) => void;
  saveModule: (moduleId: string) => Promise<void>;
  discardChanges: (moduleId: string) => void;
  resetToDefault: (moduleId: string) => Promise<void>; // 恢复默认
  refreshBudget: () => Promise<void>;
  loadFailureStats: () => Promise<void>;
  loadDailyReport: () => Promise<void>;
  reset: () => void;
}

const initialModules: Record<string, PromptModule> = {
  three_views: {
    id: "three_views",
    name: "三观提示词",
    description: "你的价值观和行为准则",
    content: "",
    estimatedTokens: 0,
  },
  identity: {
    id: "identity",
    name: "身份定位",
    description: "你的自我认知",
    content: "",
    estimatedTokens: 0,
  },
  memory_system: {
    id: "memory_system",
    name: "记忆系统",
    description: "记忆管理策略",
    content: "",
    estimatedTokens: 0,
  },
  behavior: {
    id: "behavior",
    name: "行为模式",
    description: "交互行为规范",
    content: "",
    estimatedTokens: 0,
  },
};

export const usePromptStore = create<PromptState>((set, get) => ({
  modules: initialModules,
  budgetCategories: DEFAULT_BUDGET_CATEGORIES,
  failureStats: null,
  dailyReport: null,
  isLoading: false,
  error: null,
  editingContent: {},
  hasUnsavedChanges: {},

  loadModules: async () => {
    set({ isLoading: true, error: null });
    try {
      // 1. 从真实API加载提示词模块列表和内容
      const apiModules = await fetchPromptModules();

      // 2. 构建模块数据
      const modules: Record<string, PromptModule> = {};

      for (const apiMod of apiModules) {
        if (apiMod.id) {
          modules[apiMod.id] = {
            id: apiMod.id,
            name: apiMod.name || apiMod.id,
            description: apiMod.description || "",
            content: apiMod.content || "",
            estimatedTokens: estimateTokens(apiMod.content || ""),
          };

          // 3. 加载变体信息
          try {
            const variants = await fetchModuleVariants(apiMod.id);
            if (variants.length > 0) {
              modules[apiMod.id].variants = variants;
              modules[apiMod.id].currentVariant =
                variants.find((v) => v.isDefault)?.id || variants[0].id;
              // 如果有变体内容且当前内容为空，使用变体内容
              if (!modules[apiMod.id].content) {
                const defaultVariant =
                  variants.find((v) => v.isDefault) || variants[0];
                modules[apiMod.id].content = defaultVariant.content || "";
                modules[apiMod.id].estimatedTokens = estimateTokens(
                  modules[apiMod.id].content,
                );
              }
            }
          } catch (e) {
            console.warn(`[PromptStore] 加载模块 ${apiMod.id} 变体失败`);
          }
        }
      }

      // 4. 如果没有加载到任何模块，使用默认值
      if (Object.keys(modules).length === 0) {
        Object.assign(modules, initialModules);
      }

      set({ modules, isLoading: false });
      get().refreshBudget();
    } catch (error) {
      set({ error: String(error), isLoading: false });
    }
  },

  loadVariants: async (moduleId: string) => {
    try {
      const variants = await fetchModuleVariants(moduleId);
      set((state) => ({
        modules: {
          ...state.modules,
          [moduleId]: {
            ...state.modules[moduleId],
            variants,
          },
        },
      }));
    } catch (error) {
      console.error(`[PromptStore] 加载变体失败: ${moduleId}`, error);
    }
  },

  switchVariant: async (moduleId: string, variantId: string) => {
    set({ isLoading: true });
    try {
      const result = await switchVariantApi(moduleId, variantId);
      set((state) => ({
        modules: {
          ...state.modules,
          [moduleId]: {
            ...state.modules[moduleId],
            content: result.content,
            currentVariant: variantId,
            estimatedTokens:
              result.tokenCount || estimateTokens(result.content),
          },
        },
        isLoading: false,
      }));
      get().refreshBudget();
    } catch (error) {
      set({ error: String(error), isLoading: false });
      throw error;
    }
  },

  updateContent: (moduleId: string, content: string) => {
    set((state) => ({
      editingContent: { ...state.editingContent, [moduleId]: content },
      hasUnsavedChanges: { ...state.hasUnsavedChanges, [moduleId]: true },
    }));
    get().refreshBudget();
  },

  saveModule: async (moduleId: string) => {
    const state = get();
    const newContent = state.editingContent[moduleId];
    if (!newContent) return;

    set({ isLoading: true });
    try {
      // 调用API保存自定义内容
      await saveCustomContentApi(moduleId, newContent);

      set((state) => ({
        modules: {
          ...state.modules,
          [moduleId]: {
            ...state.modules[moduleId],
            content: newContent,
            estimatedTokens: estimateTokens(newContent),
          },
        },
        editingContent: { ...state.editingContent, [moduleId]: "" },
        hasUnsavedChanges: { ...state.hasUnsavedChanges, [moduleId]: false },
        isLoading: false,
      }));
      get().refreshBudget();
    } catch (error) {
      set({ error: String(error), isLoading: false });
      throw error;
    }
  },

  discardChanges: (moduleId: string) => {
    set((state) => ({
      editingContent: { ...state.editingContent, [moduleId]: "" },
      hasUnsavedChanges: { ...state.hasUnsavedChanges, [moduleId]: false },
    }));
    get().refreshBudget();
  },

  resetToDefault: async (moduleId: string) => {
    set({ isLoading: true });
    try {
      // 调用API恢复默认内容
      const result = await resetToDefaultApi(moduleId);

      set((state) => ({
        modules: {
          ...state.modules,
          [moduleId]: {
            ...state.modules[moduleId],
            content: result.content,
            estimatedTokens:
              result.tokenCount || estimateTokens(result.content),
            currentVariant:
              state.modules[moduleId]?.variants?.find((v) => v.isDefault)?.id ||
              state.modules[moduleId]?.variants?.[0]?.id,
          },
        },
        editingContent: { ...state.editingContent, [moduleId]: "" },
        hasUnsavedChanges: { ...state.hasUnsavedChanges, [moduleId]: false },
        isLoading: false,
      }));
      get().refreshBudget();
    } catch (error) {
      set({ error: String(error), isLoading: false });
      throw error;
    }
  },

  refreshBudget: async () => {
    const state = get();
    const categories = [...state.budgetCategories];
    const moduleToCategory: Record<string, number> = {
      three_views: 0,
      identity: 0,
      behavior: 0,
      memory_system: 2,
    };
    categories.forEach((c) => {
      c.used = 0;
    });
    for (const [moduleId, module] of Object.entries(state.modules)) {
      const content = state.editingContent[moduleId] || module.content || "";
      const tokens = estimateTokens(content);
      const categoryIdx = moduleToCategory[moduleId];
      if (categoryIdx !== undefined) {
        categories[categoryIdx].used += tokens;
      }
    }
    categories.forEach((cat) => {
      cat.percentage = Math.round((cat.used / cat.budget) * 100);
    });
    set({ budgetCategories: categories });
  },

  loadFailureStats: async () => {
    try {
      const stats = await fetchFailureStats();
      set({ failureStats: stats });
    } catch (error) {
      console.error("[PromptStore] 加载失败统计失败:", error);
      set({
        failureStats: {
          total: 0,
          byCategory: {},
          recent7Days: 0,
          trend: "stable",
          topIssues: [],
        },
      });
    }
  },

  loadDailyReport: async () => {
    try {
      const report = await fetchDailyReport();
      set({ dailyReport: report });
    } catch (error) {
      console.error("[PromptStore] 加载每日报告失败:", error);
      set({ dailyReport: "暂无数据" });
    }
  },

  reset: () => {
    set({
      modules: initialModules,
      budgetCategories: DEFAULT_BUDGET_CATEGORIES,
      failureStats: null,
      dailyReport: null,
      isLoading: false,
      error: null,
      editingContent: {},
      hasUnsavedChanges: {},
    });
  },
}));
