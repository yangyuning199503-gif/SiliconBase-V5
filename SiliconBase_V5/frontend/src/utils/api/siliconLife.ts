/**
 * 硅基生命成长监控面板 API
 * 
 * 提供与后端交互的接口：
 * - 生命状态数据
 * - 成长时间线
 * - 记忆金字塔
 * - 学习效果统计
 */

import { fetchAPI, handleError } from './index';

// ═══════════════════════════════════════════════════════════════════
// 类型定义
// ═══════════════════════════════════════════════════════════════════

/**
 * 生命状态
 */
export interface LifeState {
  /** 存在感 (0-10) */
  presence: number;
  /** 胜任感 (0-10) */
  competence: number;
  /** 好奇心 (0-10) */
  curiosity: number;
  /** 当前情绪 */
  current_emotion: string;
  /** 生命脉动间隔(秒) */
  pulse_interval: number;
  /** 上次脉动时间 */
  last_pulse: string;
  /** 总运行时间(秒) */
  total_uptime: number;
}

/**
 * 成长里程碑
 */
export interface GrowthMilestone {
  /** 里程碑ID */
  id: string;
  /** 第几天 */
  day: number;
  /** 类型 */
  type: 'birth' | 'first_tool' | 'first_task' | 'level_up' | 'memory_milestone' | 'achievement' | 'skill_unlock' | 'other';
  /** 标题 */
  title: string;
  /** 描述 */
  description: string;
  /** 时间戳 */
  timestamp: string;
  /** 关联数据 */
  metadata?: Record<string, any>;
}

/**
 * 记忆金字塔数据
 */
export interface MemoryPyramidData {
  /** L1 短期记忆 */
  L1: number;
  /** L2 中期记忆 */
  L2: number;
  /** L3 长期记忆 */
  L3: number;
  /** L4 向量记忆 */
  L4: number;
  /** L5 执行轨迹 */
  L5: number;
  /** 总量 */
  total: number;
}

/**
 * 学习效果统计
 */
export interface LearningStats {
  /** 总经验数 */
  total_experiences: number;
  /** 有效经验数 */
  effective_experiences: number;
  /** 有效率(%) */
  effective_rate: number;
  /** 成功率(%) */
  success_rate: number;
  /** 今日使用次数 */
  today_usage: number;
  /** 最新经验 */
  latest_experience: string | null;
  /** 已收集反馈数 */
  feedback_collected: number;
  /** 从中学习的经验数 */
  learned_from_feedback: number;
}

/**
 * 成长摘要（用于快速概览）
 */
export interface GrowthSummary {
  /** 当前等级 */
  level: number;
  /** 等级名称 */
  level_name: string;
  /** 总经验值 */
  total_xp: number;
  /** 运行天数 */
  days_alive: number;
  /** 里程碑数 */
  milestone_count: number;
  /** 记忆总数 */
  memory_count: number;
  /** 工具使用次数 */
  tool_usage_count: number;
}

/**
 * 意识生长统计
 */
export interface GrowthStats {
  user_id: string;
  model_file_size: number;
  model_last_modified: number;
  training_samples_total: number;
  training_samples_memory: number;
  motivation_state: {
    curiosity: number;
    mastery: number;
    autonomy: number;
    purpose: number;
  };
  ukf_state: {
    action_will: number;
    reflect_tendency: number;
    explore_tendency: number;
    timestamp?: string;
  } | null;
  recent_thoughts: {
    timestamp: string;
    content: string;
    mode: string;
  }[];
  thinking_stats: Record<string, any>;
  is_running: boolean;
  timestamp: string;
}

/**
 * 自发行动记录
 */
export interface SelfAction {
  id: number;
  timestamp: string;
  action_type: string;
  action_content: string | null;
  energy_cost: number;
  satisfaction_gain: number;
  status: string;
}

/**
 * 意识核心生命体征
 */
export interface ConsciousnessVitals {
  energy: number;
  curiosity: number;
  satisfaction: number;
  stress: number;
  mood: string;
  is_hungry: boolean;
  is_tired: boolean;
  is_excited: boolean;
}

export interface ConsciousnessStatus {
  user_id: string;
  vitals: ConsciousnessVitals;
  activity_level: number;
  current_interval: number;
  pending_actions: number;
  recent_thoughts: number;
  is_running: boolean;
}

// ═══════════════════════════════════════════════════════════════════
// API 函数
// ═══════════════════════════════════════════════════════════════════

export const siliconLifeAPI = {
  /**
   * 获取生命状态
   */
  async getLifeState(): Promise<LifeState> {
    try {
      const response = await fetchAPI<{ success: boolean; data: LifeState }>('/api/life/state');
      return response.data;
    } catch (error) {
      return handleError(error, '获取生命状态失败');
    }
  },

  /**
   * 获取成长时间线
   * @param limit 返回的里程碑数量限制
   */
  async getGrowthTimeline(limit: number = 50): Promise<GrowthMilestone[]> {
    try {
      const response = await fetchAPI<{ success: boolean; data: { milestones: GrowthMilestone[] } }>(
        `/api/life/timeline?limit=${limit}`
      );
      return response.data.milestones || [];
    } catch (error) {
      return handleError(error, '获取成长时间线失败');
    }
  },

  /**
   * 获取记忆金字塔数据
   */
  async getMemoryPyramid(): Promise<MemoryPyramidData> {
    try {
      const response = await fetchAPI<{ success: boolean; data: MemoryPyramidData }>('/api/life/memory-pyramid');
      return response.data;
    } catch (error) {
      return handleError(error, '获取记忆金字塔失败');
    }
  },

  /**
   * 获取学习效果统计
   */
  async getLearningStats(): Promise<LearningStats> {
    try {
      const response = await fetchAPI<{ success: boolean; data: LearningStats }>('/api/life/learning-stats');
      return response.data;
    } catch (error) {
      return handleError(error, '获取学习统计失败');
    }
  },

  /**
   * 获取成长摘要（用于顶部栏或快速预览）
   */
  async getGrowthSummary(): Promise<GrowthSummary> {
    try {
      const response = await fetchAPI<{ success: boolean; data: GrowthSummary }>('/api/life/summary');
      return response.data;
    } catch (error) {
      return handleError(error, '获取成长摘要失败');
    }
  },

  /**
   * 获取意识生长统计（动机、UKF、训练数据等）
   */
  async getGrowthStats(): Promise<GrowthStats> {
    try {
      const response = await fetchAPI<GrowthStats>('/api/consciousness/growth-stats');
      return response;
    } catch (error) {
      return handleError(error, '获取意识生长统计失败');
    }
  },

  /**
   * 获取自发行动列表
   */
  async getSelfActions(limit: number = 20): Promise<SelfAction[]> {
    try {
      const response = await fetchAPI<{ user_id: string; actions: SelfAction[]; total: number }>(
        `/api/consciousness/self-actions?limit=${limit}`
      );
      return response.actions || [];
    } catch (error) {
      return handleError(error, '获取自发行动失败');
    }
  },

  /**
   * 获取意识核心状态（生命体征、活动水平等）
   */
  async getConsciousnessStatus(): Promise<ConsciousnessStatus> {
    try {
      const response = await fetchAPI<ConsciousnessStatus>('/api/consciousness/status');
      return response;
    } catch (error) {
      return handleError(error, '获取意识状态失败');
    }
  },

  /**
   * 手动触发生命状态更新
   * 用于用户手动刷新或特定事件后
   */
  async refreshLifeState(): Promise<LifeState> {
    try {
      const response = await fetchAPI<{ success: boolean; data: LifeState }>(
        '/api/life/state/refresh',
        { method: 'POST' }
      );
      return response.data;
    } catch (error) {
      return handleError(error, '刷新生命状态失败');
    }
  },

  // ═══════════════════════════════════════════════════════════════════
  // 训练总控开关 API
  // ═══════════════════════════════════════════════════════════════════

  async getTrainingStatus(): Promise<boolean> {
    try {
      const response = await fetchAPI<{ training_enabled: boolean }>('/api/consciousness/training/status');
      return response.training_enabled;
    } catch (error) {
      return handleError(error, '获取训练状态失败') ?? false;
    }
  },

  async startTraining(): Promise<void> {
    try {
      await fetchAPI('/api/consciousness/training/start', { method: 'POST' });
    } catch (error) {
      handleError(error, '开启训练失败');
    }
  },

  async stopTraining(): Promise<void> {
    try {
      await fetchAPI('/api/consciousness/training/stop', { method: 'POST' });
    } catch (error) {
      handleError(error, '关闭训练失败');
    }
  },

  // ═══════════════════════════════════════════════════════════════════
  // 视觉未知元素发现开关 API
  // ═══════════════════════════════════════════════════════════════════

  async getVisionDiscoveryStatus(): Promise<boolean> {
    try {
      const response = await fetchAPI<{ vision_discovery_enabled: boolean }>('/api/consciousness/vision-discovery/status');
      return response.vision_discovery_enabled;
    } catch (error) {
      return handleError(error, '获取视觉发现状态失败') ?? false;
    }
  },

  async startVisionDiscovery(): Promise<void> {
    try {
      await fetchAPI('/api/consciousness/vision-discovery/start', { method: 'POST' });
    } catch (error) {
      handleError(error, '开启视觉发现失败');
    }
  },

  async stopVisionDiscovery(): Promise<void> {
    try {
      await fetchAPI('/api/consciousness/vision-discovery/stop', { method: 'POST' });
    } catch (error) {
      handleError(error, '关闭视觉发现失败');
    }
  },
};

// ═══════════════════════════════════════════════════════════════════
// WebSocket 消息类型
// ═══════════════════════════════════════════════════════════════════

export interface WebSocketLifeMessage {
  type: 'life_state_update' | 'new_milestone' | 'memory_update' | 'learning_update' | 'heartbeat';
  timestamp: string;
  payload: any;
}

// ═══════════════════════════════════════════════════════════════════
// 导出
// ═══════════════════════════════════════════════════════════════════

export default siliconLifeAPI;
