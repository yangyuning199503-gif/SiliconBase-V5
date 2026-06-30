/**
 * 游戏化 API
 * 对应后端 /api/gamification/* 端点
 */

import { fetchAPI, handleError } from "./index";

export interface GamificationStatus {
  user_id: string;
  level: number;
  xp: number;
  next_level_xp: number;
  progress: number;
  achievements_count: number;
  total_tool_usage: number;
}

export interface LevelInfo {
  level: number;
  title: string;
  min_xp: number;
  max_xp: number;
  progress: number;
}

export interface CategoryStatus {
  category: string;
  unlocked: boolean;
  required_level: number;
  current_level: number;
}

export interface Achievement {
  id: string;
  name: string;
  description: string;
  icon?: string;
  unlocked: boolean;
  unlocked_at?: string;
  xp_reward: number;
}

export interface LeaderboardEntry {
  rank: number;
  user_id: string;
  level: number;
  xp: number;
  achievements: number;
}

export const gamificationAPI = {
  /**
   * 获取用户游戏化状态
   */
  async getStatus(): Promise<GamificationStatus> {
    try {
      const response = await fetchAPI<{ success: boolean; data: GamificationStatus }>(
        "/api/gamification/status",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取游戏化状态失败");
    }
  },

  /**
   * 获取等级信息（简化版）
   */
  async getLevel(): Promise<LevelInfo> {
    try {
      const response = await fetchAPI<{ success: boolean; data: LevelInfo }>(
        "/api/gamification/level",
      );
      return response.data;
    } catch (error) {
      return handleError(error, "获取等级信息失败");
    }
  },

  /**
   * 增加用户经验值
   */
  async addXP(amount: number, reason?: string): Promise<{ success: boolean; xp: number; level: number }> {
    try {
      const response = await fetchAPI<{ success: boolean; data: { xp: number; level: number } }>(
        "/api/gamification/add-xp",
        {
          method: "POST",
          body: { amount, reason },
        },
      );
      return { success: response.success, ...response.data };
    } catch (error) {
      return handleError(error, "增加经验值失败");
    }
  },

  /**
   * 记录工具使用并获得经验值
   */
  async recordToolUsage(toolName: string, success: boolean = true): Promise<{ success: boolean; xp: number }> {
    try {
      const response = await fetchAPI<{ success: boolean; data: { xp: number } }>(
        "/api/gamification/record-tool-usage",
        {
          method: "POST",
          body: { tool_name: toolName, success },
        },
      );
      return { success: response.success, ...response.data };
    } catch (error) {
      return handleError(error, "记录工具使用失败");
    }
  },

  /**
   * 获取工具分类解锁状态
   */
  async getCategories(): Promise<CategoryStatus[]> {
    try {
      const response = await fetchAPI<{ success: boolean; data: { categories: CategoryStatus[] } }>(
        "/api/gamification/categories",
      );
      return response.data.categories || [];
    } catch (error) {
      return handleError(error, "获取分类解锁状态失败");
    }
  },

  /**
   * 获取用户成就列表
   */
  async getAchievements(): Promise<Achievement[]> {
    try {
      const response = await fetchAPI<{ success: boolean; data: { achievements: Achievement[] } }>(
        "/api/gamification/achievements",
      );
      return response.data.achievements || [];
    } catch (error) {
      return handleError(error, "获取成就列表失败");
    }
  },

  /**
   * 获取排行榜
   */
  async getLeaderboard(limit: number = 50): Promise<LeaderboardEntry[]> {
    try {
      const response = await fetchAPI<{ success: boolean; data: { leaderboard: LeaderboardEntry[] } }>(
        `/api/gamification/leaderboard?limit=${limit}`,
      );
      return response.data.leaderboard || [];
    } catch (error) {
      return handleError(error, "获取排行榜失败");
    }
  },
};

export default gamificationAPI;
