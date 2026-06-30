/**
 * 提示词模块类型定义
 * SiliconBase V5 - Type Definitions
 */

// ========== 基础类型 ==========

export interface PromptModule {
  id: string;
  name: string;
  description: string;
  content?: string;
  category: 'system' | 'optional';
  optional: boolean;
  default: boolean;
  order: number;
  is_user_override?: boolean;
  variables?: string[];
}

export interface PromptVariant {
  id: string;
  name: string;
  description: string;
  content?: string;
  tokenCount: number;
  failureRate: number;
  isDefault: boolean;
  // 统计信息
  stats?: {
    usageCount: number;
    successCount: number;
    avgResponseTime: number;
  };
}

// ========== Token预算 ==========

export interface BudgetCategory {
  name: string;
  budget: number;
  used: number;
  percentage?: number;  // 使用率百分比
  color?: string;       // 显示颜色
  truncated?: boolean;
  originalTokens?: number;
  warning?: boolean;    // 接近预算上限
}

export interface TokenBudgetReport {
  totalOriginalTokens: number;
  totalTruncatedTokens: number;
  totalBudget: number;
  categories: BudgetCategory[];
  allocations: {
    category: string;
    originalLength: number;
    budget: number;
    truncatedLength: number;
    wasTruncated: boolean;
  }[];
}

// ========== 失败分析 ==========

export interface FailurePattern {
  id: string;
  taskType: string;
  taskName: string;
  rootCause: '1' | '2' | '3' | '4' | '5';  // 1=提示词, 2=工具, 3=参数, 4=技能, 5=其他
  confidence: number;
  explanation: string;
  promptVersion: string;
  timestamp: string;
  suggestedFix?: string;
  promptPatch?: string;
}

export interface FailureStats {
  periodDays: number;
  totalFailures: number;
  byCause: Record<string, {
    count: number;
    examples: { task: string; explanation: string; patch?: string; suggestedFix?: string }[];
  }>;
  byVersion: Record<string, {
    failures: number;
    total?: number;
    failureRate?: number;
  }>;
  topFailingTasks: [string, number][];
  generatedAt: string;
}

export interface RootCauseInfo {
  code: string;
  name: string;
  description: string;
  color: string;  // 用于UI显示的颜色
}

export const ROOT_CAUSES: Record<string, RootCauseInfo> = {
  '1': { code: '1', name: '提示词描述不清', description: 'AI理解错意图', color: '#EF4444' },
  '2': { code: '2', name: '工具选择错误', description: '选错工具', color: '#F59E0B' },
  '3': { code: '3', name: '参数配置错误', description: '工具参数有误', color: '#3B82F6' },
  '4': { code: '4', name: '缺少必要技能', description: '无合适工具', color: '#8B5CF6' },
  '5': { code: '5', name: '环境/外部因素', description: '系统问题', color: '#6B7280' },
};

// ========== 优化建议 ==========

export interface OptimizationSuggestion {
  id: string;
  type: 'shorten' | 'clarify' | 'add_examples' | 'restructure' | 'switch_variant';
  moduleId: string;
  moduleName: string;
  reason: string;
  severity: 'high' | 'medium' | 'low';
  autoFixAvailable: boolean;
  autoFixResult?: string;
  metrics: {
    currentTokens: number;
    recommendedTokens: number;
    currentFailureRate: number;
  };
}

// ========== A/B测试 ==========

export interface ABTestVariant {
  id: string;
  name: string;
  successRate: number;
  samples: number;
  avgTokens: number;
}

export interface ABTestConfig {
  moduleId: string;
  variantA: string;
  variantB: string;
  trafficSplit: number;
  successMetric: 'task_completion' | 'user_rating';
  startDate?: string;
  endDate?: string;
}

// ========== API响应 ==========

export interface PromptBuildResult {
  prompt: string;
  modules_used: string[];
  estimated_tokens: number;
  variables_used: Record<string, string>;
  budget_report?: TokenBudgetReport;
}

export interface EnhancedPreviewResult {
  prompt: string;
  totalTokens: number;
  modules: {
    id: string;
    name: string;
    content: string;
    tokens: number;
    truncated: boolean;
    originalContent?: string;
  }[];
  budgetReport: TokenBudgetReport;
}
