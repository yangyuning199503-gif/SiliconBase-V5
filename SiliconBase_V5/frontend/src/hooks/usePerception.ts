import { useState, useEffect, useCallback, useRef } from 'react';
import { useWebSocket } from './useWebSocket';

/**
 * 感知系统状态（避免与 types/index.ts 的 SystemStatus 冲突）
 */
export interface PerceptionSystemStatus {
  cpu: number;
  memory: number;
}

/**
 * 感知数据 —— 与后端 perception_manager.py 推送结构对齐
 */
export interface PerceptionData {
  /** 感知类型 */
  type: string;
  /** 触发原因 */
  trigger_reason: string;
  /** 时间戳 */
  timestamp: number;
  /** 置信度 */
  confidence: number;
  /** 内容预览 */
  content_preview: string;
  /** 元数据（可能包含 objects/bbox 等视觉元素） */
  metadata?: Record<string, any>;
}

/**
 * usePerception Hook 返回类型
 */
export interface UsePerceptionReturn {
  /** 是否正在显示感知指示器 */
  isActive: boolean;
  /** 感知数据 */
  perceptionData: PerceptionData | null;
  /** 触发原因 */
  triggerReason: string;
  /** 是否展开显示详情 */
  isExpanded: boolean;
  /** 设置展开状态 */
  setIsExpanded: (expanded: boolean) => void;
  /** 手动触发显示（调试用） */
  trigger: (data: PerceptionData, reason: string) => void;
  /** 手动关闭 */
  close: () => void;
}

/**
 * 自动隐藏延迟（毫秒）
 */
const AUTO_HIDE_DELAY = 3000;

/**
 * 感知状态管理 Hook
 * 
 * 功能：
 * 1. 通过WebSocket实时接收感知触发事件
 * 2. 管理感知指示器的显示/隐藏状态
 * 3. 3秒后自动隐藏指示器
 * 4. 支持手动触发和关闭（调试用）
 * 
 * @returns UsePerceptionReturn
 */
export function usePerception(): UsePerceptionReturn {
  const { lastMessage, isConnected } = useWebSocket();
  
  // 是否激活
  const [isActive, setIsActive] = useState(false);
  
  // 感知数据
  const [perceptionData, setPerceptionData] = useState<PerceptionData | null>(null);
  
  // 触发原因
  const [triggerReason, setTriggerReason] = useState('');
  
  // 是否展开
  const [isExpanded, setIsExpanded] = useState(false);
  
  // 隐藏定时器引用
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /**
   * 清除隐藏定时器
   */
  const clearHideTimer = useCallback(() => {
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }, []);

  /**
   * 启动隐藏定时器
   */
  const startHideTimer = useCallback(() => {
    clearHideTimer();
    hideTimerRef.current = setTimeout(() => {
      setIsActive(false);
      // 延迟重置展开状态，等待淡出动画完成
      setTimeout(() => setIsExpanded(false), 300);
    }, AUTO_HIDE_DELAY);
  }, [clearHideTimer]);

  /**
   * 处理WebSocket消息
   */
  useEffect(() => {
    if (!lastMessage) return;

    if (lastMessage.type === 'perception_triggered') {
      const data = lastMessage.data;
      if (!data) {
        console.error('[SILENT_FAILURE_BLOCKED] perception_triggered消息缺少data')
        return
      }
      
      console.log('[usePerception] 感知触发:', data.trigger_reason, data);
      
      // 清除之前的定时器
      clearHideTimer();
      
      // 更新状态
      setIsActive(true);
      setPerceptionData(data as PerceptionData);
      setTriggerReason((data.trigger_reason as string) || 'unknown');
      
      // 启动自动隐藏定时器
      startHideTimer();
    }
  }, [lastMessage, clearHideTimer, startHideTimer]);

  /**
   * WebSocket断开时清理状态
   */
  useEffect(() => {
    if (!isConnected && isActive) {
      setIsActive(false);
      clearHideTimer();
    }
  }, [isConnected, isActive, clearHideTimer]);

  /**
   * 手动触发（调试用）
   */
  const trigger = useCallback((data: PerceptionData, reason: string) => {
    clearHideTimer();
    setIsActive(true);
    setPerceptionData(data);
    setTriggerReason(reason);
    startHideTimer();
  }, [clearHideTimer, startHideTimer]);

  /**
   * 手动关闭
   */
  const close = useCallback(() => {
    clearHideTimer();
    setIsActive(false);
    setTimeout(() => setIsExpanded(false), 300);
  }, [clearHideTimer]);

  /**
   * 组件卸载时清理
   */
  useEffect(() => {
    return () => {
      clearHideTimer();
    };
  }, [clearHideTimer]);

  return {
    isActive,
    perceptionData,
    triggerReason,
    isExpanded,
    setIsExpanded,
    trigger,
    close,
  };
}

export default usePerception;
