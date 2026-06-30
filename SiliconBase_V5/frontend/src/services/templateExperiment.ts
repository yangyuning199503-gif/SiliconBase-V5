import { fetchAPI } from '@/utils/api';

/**
 * 模板实验API服务
 * 
 * 提供与后端template_experiment模块的交互接口
 */

export interface TaskFeedback {
  taskId: string;
  templateName: string;
  rating: number;
  feedback: string;
  quickTags: string[];
  timestamp: number;
}

export interface TemplateReport {
  template_name: string;
  total_tasks: number;
  successful_tasks: number;
  success_rate: number;
  avg_rating: number;
  rating_count: number;
  avg_execution_time_ms: number;
  avg_steps: number;
  avg_tool_calls: number;
  avg_memory_hits: number;
}

export interface ExperimentComparison {
  templates: string[];
  success_rates: number[];
  avg_ratings: number[];
  avg_execution_times: number[];
  total_tasks: number[];
  last_updated: number;
}

export interface UserRecommendation {
  recommended_template: string;
  confidence: number;
  reason: string;
  alternatives: string[];
  interaction_count?: number;
}

export interface WeeklyReport {
  week_start: string;
  week_end: string;
  generated_at: number;
  template_comparison: Record<string, TemplateReport>;
  winner_template: string | null;
  recommendations: string[];
}

/**
 * 提交任务反馈
 */
export async function submitTaskFeedback(feedback: TaskFeedback): Promise<boolean> {
  try {
    const result = await fetchAPI<any>('/api/template-experiment/feedback', {
      method: 'POST',
      body: feedback,
    });
    return result.success === true;
  } catch (error) {
    console.error('[TemplateExperimentAPI] 提交反馈失败:', error);
    // 失败时存储到本地，稍后重试
    storePendingFeedback(feedback);
    return false;
  }
}

/**
 * 获取模板效果报告
 */
export async function getTemplateReport(): Promise<Record<string, TemplateReport>> {
  try {
    const result = await fetchAPI<any>('/api/template-experiment/report');
    return result.data || {};
  } catch (error) {
    console.error('[TemplateExperimentAPI] 获取报告失败:', error);
    return {};
  }
}

/**
 * 获取实验对比数据（用于Dashboard）
 */
export async function getExperimentComparison(): Promise<ExperimentComparison | null> {
  try {
    const result = await fetchAPI<any>('/api/template-experiment/comparison');
    return result.data || null;
  } catch (error) {
    console.error('[TemplateExperimentAPI] 获取对比数据失败:', error);
    return null;
  }
}

/**
 * 获取用户模板推荐
 */
export async function getUserRecommendation(): Promise<UserRecommendation | null> {
  try {
    const result = await fetchAPI<any>('/api/template-experiment/recommendation');
    return result.data || null;
  } catch (error) {
    console.error('[TemplateExperimentAPI] 获取推荐失败:', error);
    return null;
  }
}

/**
 * 获取最新周报告
 */
export async function getLatestWeeklyReport(): Promise<WeeklyReport | null> {
  try {
    const result = await fetchAPI<any>('/api/template-experiment/weekly-report');
    return result.data || null;
  } catch (error) {
    console.error('[TemplateExperimentAPI] 获取周报告失败:', error);
    return null;
  }
}

/**
 * 获取所有周报告
 */
export async function getAllWeeklyReports(): Promise<WeeklyReport[]> {
  try {
    const result = await fetchAPI<any>('/api/template-experiment/weekly-reports');
    return result.data || [];
  } catch (error) {
    console.error('[TemplateExperimentAPI] 获取所有周报告失败:', error);
    return [];
  }
}

/**
 * 手动生成周报告（管理员功能）
 */
export async function generateWeeklyReport(): Promise<WeeklyReport | null> {
  try {
    const result = await fetchAPI<any>('/api/template-experiment/generate-report', {
      method: 'POST',
    });
    return result.data || null;
  } catch (error) {
    console.error('[TemplateExperimentAPI] 生成周报告失败:', error);
    return null;
  }
}

// =============================================================================
// 本地存储辅助函数（用于离线支持）
// =============================================================================

const PENDING_FEEDBACK_KEY = 'template_experiment_pending_feedback';

function storePendingFeedback(feedback: TaskFeedback): void {
  try {
    const pending = JSON.parse(localStorage.getItem(PENDING_FEEDBACK_KEY) || '[]');
    pending.push(feedback);
    localStorage.setItem(PENDING_FEEDBACK_KEY, JSON.stringify(pending));
  } catch (error) {
    console.error('[TemplateExperimentAPI] 存储待发送反馈失败:', error);
  }
}

/**
 * 重试发送待处理的反馈
 */
export async function retryPendingFeedback(): Promise<number> {
  try {
    const pending = JSON.parse(localStorage.getItem(PENDING_FEEDBACK_KEY) || '[]');
    if (pending.length === 0) return 0;

    let successCount = 0;
    const failed: TaskFeedback[] = [];

    for (const feedback of pending) {
      const success = await submitTaskFeedback(feedback);
      if (success) {
        successCount++;
      } else {
        failed.push(feedback);
      }
    }

    localStorage.setItem(PENDING_FEEDBACK_KEY, JSON.stringify(failed));
    return successCount;
  } catch (error) {
    console.error('[TemplateExperimentAPI] 重试发送失败:', error);
    return 0;
  }
}
