import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { fetchAPI, APIError } from '../utils/api';

// 模式类型定义
type ModeType = 'daily' | 'focus';

// State 接口定义
interface ModeState {
  // 状态
  mode: ModeType;
  isLoading: boolean;
  error: string | null;

  // Actions
  switchMode: (mode: ModeType) => Promise<boolean>;
  fetchCurrentMode: () => Promise<void>;
  clearError: () => void;
}

// 创建 Store
export const useModeStore = create<ModeState>()(
  persist(
    (set, get) => ({
      // 初始状态
      mode: 'daily', // 默认日常模式，与后端保持一致（用户需求自动触发专注模式）
      isLoading: false,
      error: null,

      /**
       * 切换模式
       * @param newMode - 目标模式: 'daily' | 'focus'
       * @returns Promise<boolean> - 切换是否成功
       */
      switchMode: async (newMode: ModeType): Promise<boolean> => {
        const currentMode = get().mode;

        // 如果模式相同，直接返回成功
        if (currentMode === newMode) {
          return true;
        }

        // 设置加载状态
        set({ isLoading: true, error: null });

        try {
          console.log('[ModeStore] 正在发送模式切换请求:', {
            mode: newMode,
            currentMode,
          });

          // 调用后端 API 切换模式（fetchAPI 自动携带 token 并处理 401）
          await fetchAPI('/api/mode', {
            method: 'POST',
            body: {
              mode: newMode,
              reason: `用户手动切换到${newMode === 'daily' ? '日常' : '专注'}模式`,
            },
          });

          // 更新本地状态
          set({
            mode: newMode,
            isLoading: false,
            error: null,
          });

          console.log(`[ModeStore] 模式切换成功: ${currentMode} -> ${newMode}`);
          return true;
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : '切换模式时发生未知错误';

          console.error('[ModeStore] 切换模式异常:', {
            error: errorMessage,
            mode: newMode,
          });

          set({
            isLoading: false,
            error: errorMessage,
          });

          return false;
        }
      },

      /**
       * 从后端获取当前模式
       */
      fetchCurrentMode: async (): Promise<void> => {
        set({ isLoading: true, error: null });

        try {
          console.log('[ModeStore] 正在获取当前模式');

          // fetchAPI 自动携带 token 并处理 401
          const data = await fetchAPI<{
            mode?: string;
            mode_info?: { mode?: string };
          }>('/api/mode');

          // 验证返回的模式值
          const serverMode = (data.mode_info?.mode || data.mode) as ModeType;
          if (serverMode === 'daily' || serverMode === 'focus') {
            set({
              mode: serverMode,
              isLoading: false,
              error: null,
            });
            console.log(`[ModeStore] 从服务器获取模式: ${serverMode}`);
          } else {
            console.warn('[ModeStore] 服务器返回无效模式值:', serverMode);
            set({ isLoading: false });
          }
        } catch (error) {
          // 如果后端未实现该 API（404），使用本地存储的值
          if (error instanceof APIError && error.status === 404) {
            console.warn('[ModeStore] 后端模式 API 未实现，使用本地存储值');
            set({ isLoading: false });
            return;
          }

          const errorMessage =
            error instanceof Error ? error.message : '获取模式时发生未知错误';

          console.error('[ModeStore] 获取模式异常:', { error: errorMessage });

          // 获取失败时保持当前值，只记录错误
          set({
            isLoading: false,
            error: errorMessage,
          });
        }
      },

      /**
       * 清除错误状态
       */
      clearError: (): void => {
        set({ error: null });
      },
    }),
    {
      // 持久化配置
      name: 'siliconbase-mode-storage', // localStorage 键名
      partialize: (state) => ({
        mode: state.mode, // 只持久化 mode 字段
      }),
    },
  ),
);

// 导出类型
export type { ModeType };
