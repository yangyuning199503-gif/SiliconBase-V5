/**
 * 游戏化系统 Hook
 * 提供用户等级、经验值、工具解锁进度等功能
 */
import {
  useState,
  useEffect,
  useCallback,
  useContext,
  createContext,
} from 'react';
import { isAuthenticated } from '../utils/auth';
import { fetchAPI, APIError } from '../utils/api';

// 等级进度信息
export interface LevelProgress {
  current_level: number;
  current_xp: number;
  min_xp: number;
  max_xp: number;
  progress_percent: number;
  xp_to_next: number;
  level_name: string;
  level_color: string;
}

// 分类解锁信息
export interface CategoryProgress {
  name: string;
  icon: string;
  color: string;
  unlock_level: number;
  is_unlocked: boolean;
  progress: number;
}

// 游戏化状态
export interface GamificationStatus {
  user_id: string;
  level: LevelProgress;
  categories: CategoryProgress[];
  stats: {
    total_tools_used: number;
    unique_tools_used: number;
    categories_unlocked: number;
    total_categories: number;
    achievements_count: number;
  };
  recent_activity: {
    last_active: number;
    account_created: number;
  };
}

// 简化版等级信息（用于顶部栏）
export interface SimpleLevelInfo {
  level: number;
  level_name: string;
  xp: number;
  xp_to_next: number;
  progress_percent: number;
  color: string;
}

// 游戏化上下文
interface GamificationContextType {
  status: GamificationStatus | null;
  simpleLevel: SimpleLevelInfo | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  addXp: (amount: number, source?: string) => Promise<void>;
  recordToolUsage: (toolId: string, xpEarned?: number) => Promise<void>;
  isLoggedIn: boolean;
}

const GamificationContext = createContext<GamificationContextType | null>(null);

// 后端允许的经验来源
const VALID_XP_SOURCES = new Set([
  'tool_usage',
  'task_complete',
  'achievement',
  'daily_login',
  'streak_bonus',
]);

// API 函数（统一走 fetchAPI，自动携带 token 并处理 401）
const gamificationAPI = {
  async getStatus(): Promise<GamificationStatus> {
    const res = await fetchAPI<{ data: GamificationStatus }>(
      '/api/gamification/status',
    );
    return res.data;
  },

  async getLevelInfo(): Promise<SimpleLevelInfo> {
    const res = await fetchAPI<{ data: SimpleLevelInfo }>(
      '/api/gamification/level',
    );
    return res.data;
  },

  async addXp(amount: number, source: string = 'tool_usage'): Promise<void> {
    // 对齐后端校验：非法来源会被 400 拒绝
    const safeSource = VALID_XP_SOURCES.has(source) ? source : 'tool_usage';
    const params = new URLSearchParams({
      xp_amount: String(amount),
      source: safeSource,
    });
    await fetchAPI(`/api/gamification/add-xp?${params.toString()}`, {
      method: 'POST',
    });
  },

  async recordToolUsage(
    toolId: string,
    xpEarned: number = 10,
  ): Promise<void> {
    const params = new URLSearchParams({
      tool_id: toolId,
      xp_earned: String(xpEarned),
    });
    await fetchAPI(`/api/gamification/record-tool-usage?${params.toString()}`, {
      method: 'POST',
    });
  },
};

// 判断错误是否为未登录/401
function isAuthError(err: unknown): boolean {
  if (err instanceof APIError && err.status === 401) return true;
  if (err instanceof Error) {
    return err.message.includes('401') || err.message.includes('未登录');
  }
  return false;
}

// 游戏化 Provider
export function GamificationProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [status, setStatus] = useState<GamificationStatus | null>(null);
  const [simpleLevel, setSimpleLevel] = useState<SimpleLevelInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  const fetchData = useCallback(async () => {
    // 检查用户是否已登录，未登录时跳过请求
    if (!isAuthenticated()) {
      console.debug('[Gamification] 用户未登录，跳过数据获取');
      setLoading(false);
      setIsLoggedIn(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setIsLoggedIn(true);

      // 并行获取数据
      const [statusData, levelData] = await Promise.all([
        gamificationAPI.getStatus(),
        gamificationAPI.getLevelInfo(),
      ]);

      setStatus(statusData);
      setSimpleLevel(levelData);
    } catch (err) {
      // 401 错误特殊处理 - 不显示错误，因为未登录/会话过期是正常状态
      if (isAuthError(err)) {
        console.debug('[Gamification] 认证失败，用户可能未登录');
        setIsLoggedIn(false);
        setError(null);
      } else {
        const msg = err instanceof Error ? err.message : '未知错误';
        setError(msg);
        console.error('[Gamification] 获取数据失败:', err);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    await fetchData();
  }, [fetchData]);

  const addXp = useCallback(
    async (amount: number, source: string = 'tool_usage') => {
      // 检查登录状态
      if (!isAuthenticated()) {
        console.warn('[Gamification] 未登录，无法添加经验值');
        throw new Error('请先登录');
      }
      try {
        await gamificationAPI.addXp(amount, source);
        // 刷新数据
        await refresh();
      } catch (err) {
        console.error('[Gamification] 添加经验值失败:', err);
        throw err;
      }
    },
    [refresh],
  );

  const recordToolUsage = useCallback(
    async (toolId: string, xpEarned: number = 10) => {
      // 检查登录状态
      if (!isAuthenticated()) {
        console.warn('[Gamification] 未登录，无法记录工具使用');
        throw new Error('请先登录');
      }
      try {
        await gamificationAPI.recordToolUsage(toolId, xpEarned);
        // 刷新数据
        await refresh();
      } catch (err) {
        console.error('[Gamification] 记录工具使用失败:', err);
        throw err;
      }
    },
    [refresh],
  );

  // 初始数据获取 + 定时刷新
  useEffect(() => {
    fetchData();

    // 定时刷新（每30秒）- 仅在登录状态下刷新
    const interval = setInterval(() => {
      if (isAuthenticated()) {
        fetchData();
      }
    }, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // 监听认证状态变化
  useEffect(() => {
    // 处理登录成功事件
    const handleAuthSuccess = (_event: CustomEvent) => {
      console.log('[Gamification] 检测到登录成功，刷新数据');
      fetchData();
    };

    // 处理登出事件
    const handleAuthLogout = () => {
      console.log('[Gamification] 检测到登出，清空数据');
      setStatus(null);
      setSimpleLevel(null);
      setIsLoggedIn(false);
      setError(null);
    };

    // 监听全局认证事件
    window.addEventListener(
      'auth:login_success',
      handleAuthSuccess as EventListener,
    );
    window.addEventListener('auth:logout', handleAuthLogout as EventListener);

    return () => {
      window.removeEventListener(
        'auth:login_success',
        handleAuthSuccess as EventListener,
      );
      window.removeEventListener(
        'auth:logout',
        handleAuthLogout as EventListener,
      );
    };
  }, [fetchData]);

  return (
    <GamificationContext.Provider
      value={{
        status,
        simpleLevel,
        loading,
        error,
        refresh,
        addXp,
        recordToolUsage,
        isLoggedIn,
      }}
    >
      {children}
    </GamificationContext.Provider>
  );
}

// 使用游戏化 Hook
export function useGamification() {
  const context = useContext(GamificationContext);
  if (!context) {
    throw new Error('useGamification must be used within GamificationProvider');
  }
  return context;
}

// 简化版 Hook（仅获取等级信息）
export function useLevelInfo(): SimpleLevelInfo | null {
  const { simpleLevel, isLoggedIn } = useGamification();
  // 未登录时返回null，不抛出错误
  if (!isLoggedIn) {
    return null;
  }
  return simpleLevel;
}

// 导出 API 供直接使用
export { gamificationAPI };
