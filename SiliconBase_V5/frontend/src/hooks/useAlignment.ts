/**
 * useAlignment Hook - 目标对齐状态管理
 * 
 * 功能：
 * 1. 监听WebSocket `clarification_needed` / `confirmation_needed` 事件
 * 2. 管理AlignmentDialog的显示/隐藏状态
 * 3. 处理用户选择并发送回复到后端
 * 
 * 使用示例：
 * ```tsx
 * const { dialogProps, isOpen, sendClarification, sendConfirmation } = useAlignment();
 * 
 * return (
 *   <AlignmentDialog {...dialogProps} />
 * );
 * ```
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useWebSocket } from './useWebSocket';
import type { AlignmentType, AlignmentQueueItem } from '../components/AlignmentDialog';

/** 对齐请求类型 */
export type AlignmentRequestType = 'clarification' | 'confirmation';

/** 澄清请求消息 */
interface ClarificationNeededMessage {
  type: 'clarification_needed';
  request_id: string;
  question: string;
  options?: string[];
  timeout?: number;
  timestamp: number;
}

/** 确认请求消息 */
interface ConfirmationNeededMessage {
  type: 'confirmation_needed';
  request_id: string;
  question: string;
  message: string;
  timeout?: number;
  timestamp: number;
}

/** 对齐响应消息 */
interface AlignmentResponseMessage {
  type: 'clarification_response' | 'confirmation_response';
  request_id: string;
  response: string | boolean;
  timestamp: number;
}

type AlignmentWebSocketMessage = 
  | ClarificationNeededMessage 
  | ConfirmationNeededMessage 
  | AlignmentResponseMessage;

/** 待处理的对齐请求 */
interface PendingAlignment {
  id: string;
  type: AlignmentType;
  question: string;
  options?: string[];
  confirmMessage?: string;
  timeout: number;
  timestamp: number;
}

/** useAlignment 返回类型 */
export interface UseAlignmentReturn {
  /** 当前对话框属性 */
  dialogProps: {
    type: AlignmentType;
    question: string;
    options?: string[];
    confirmMessage?: string;
    isOpen: boolean;
    timeout?: number;
  };
  /** 是否显示对话框 */
  isOpen: boolean;
  /** 是否有待处理的请求 */
  hasPending: boolean;
  /** 待处理请求数量 */
  pendingCount: number;
  /** 发送澄清回复 */
  sendClarification: (response: string) => void;
  /** 发送确认回复 */
  sendConfirmation: (confirmed: boolean) => void;
  /** 取消当前请求 */
  cancelAlignment: () => void;
  /** 清除所有待处理请求 */
  clearAll: () => void;
  /** 处理下一个待处理请求（内部使用） */
  processNext: () => void;
}

/** 默认超时时间（秒） */
const DEFAULT_TIMEOUT = 60;

/**
 * 目标对齐状态管理 Hook
 * 
 * @returns UseAlignmentReturn
 */
export function useAlignment(): UseAlignmentReturn {
  const { lastMessage, sendMessage, isConnected } = useWebSocket();
  
  // 待处理请求队列
  const [pendingQueue, setPendingQueue] = useState<PendingAlignment[]>([]);
  
  // 当前显示的对齐请求
  const [currentAlignment, setCurrentAlignment] = useState<PendingAlignment | null>(null);
  
  // 处理状态
  const [isProcessing, setIsProcessing] = useState(false);
  
  // 超时定时器引用
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /**
   * 清除超时定时器
   */
  const clearTimeoutTimer = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  /**
   * 处理下一个待处理请求
   */
  const processNext = useCallback(() => {
    setPendingQueue(prev => {
      if (prev.length === 0) {
        setCurrentAlignment(null);
        return prev;
      }
      
      const next = prev[0];
      setCurrentAlignment(next);
      setIsProcessing(false);
      
      // 设置超时处理
      if (next.timeout > 0) {
        clearTimeoutTimer();
        timeoutRef.current = setTimeout(() => {
          // 超时自动取消
          handleTimeout(next.id);
        }, next.timeout * 1000);
      }
      
      return prev;
    });
  }, [clearTimeoutTimer]);

  /**
   * 处理超时
   */
  const handleTimeout = useCallback((requestId: string) => {
    console.log(`[useAlignment] 请求超时: ${requestId}`);
    
    // 发送超时响应
    sendMessage({
      type: 'clarification_timeout',
      request_id: requestId,
      timestamp: Date.now()
    });
    
    // 从队列中移除
    setPendingQueue(prev => {
      const filtered = prev.filter(p => p.id !== requestId);
      
      // 如果当前显示的是超时的请求，处理下一个
      if (currentAlignment?.id === requestId) {
        if (filtered.length > 0) {
          const next = filtered[0];
          setCurrentAlignment(next);
          setIsProcessing(false);
          
          if (next.timeout > 0) {
            clearTimeoutTimer();
            timeoutRef.current = setTimeout(() => {
              handleTimeout(next.id);
            }, next.timeout * 1000);
          }
        } else {
          setCurrentAlignment(null);
        }
      }
      
      return filtered;
    });
  }, [sendMessage, currentAlignment, clearTimeoutTimer]);

  /**
   * 监听WebSocket消息
   */
  useEffect(() => {
    if (!lastMessage) return;

    const msg = lastMessage as AlignmentWebSocketMessage;

    switch (msg.type) {
      case 'clarification_needed': {
        const clarificationMsg = msg as ClarificationNeededMessage;
        const newAlignment: PendingAlignment = {
          id: clarificationMsg.request_id,
          type: 'clarification',
          question: clarificationMsg.question,
          options: clarificationMsg.options || [],
          timeout: clarificationMsg.timeout || DEFAULT_TIMEOUT,
          timestamp: clarificationMsg.timestamp
        };
        
        console.log('[useAlignment] 收到澄清请求:', newAlignment);
        
        setPendingQueue(prev => {
          // 检查是否已存在相同的请求
          if (prev.some(p => p.id === newAlignment.id)) {
            return prev;
          }
          
          const newQueue = [...prev, newAlignment];
          
          // 如果是第一个请求，立即显示
          if (newQueue.length === 1) {
            setCurrentAlignment(newAlignment);
            setIsProcessing(false);
            
            // 设置超时
            if (newAlignment.timeout > 0) {
              clearTimeoutTimer();
              timeoutRef.current = setTimeout(() => {
                handleTimeout(newAlignment.id);
              }, newAlignment.timeout * 1000);
            }
          }
          
          return newQueue;
        });
        break;
      }

      case 'confirmation_needed': {
        const confirmationMsg = msg as ConfirmationNeededMessage;
        const newAlignment: PendingAlignment = {
          id: confirmationMsg.request_id,
          type: 'confirmation',
          question: confirmationMsg.question,
          confirmMessage: confirmationMsg.message,
          timeout: confirmationMsg.timeout || DEFAULT_TIMEOUT,
          timestamp: confirmationMsg.timestamp
        };
        
        console.log('[useAlignment] 收到确认请求:', newAlignment);
        
        setPendingQueue(prev => {
          if (prev.some(p => p.id === newAlignment.id)) {
            return prev;
          }
          
          const newQueue = [...prev, newAlignment];
          
          if (newQueue.length === 1) {
            setCurrentAlignment(newAlignment);
            setIsProcessing(false);
            
            if (newAlignment.timeout > 0) {
              clearTimeoutTimer();
              timeoutRef.current = setTimeout(() => {
                handleTimeout(newAlignment.id);
              }, newAlignment.timeout * 1000);
            }
          }
          
          return newQueue;
        });
        break;
      }
    }
  }, [lastMessage, handleTimeout, clearTimeoutTimer]);

  /**
   * 发送澄清回复
   */
  const sendClarification = useCallback((response: string) => {
    if (!currentAlignment) return;
    
    setIsProcessing(true);
    clearTimeoutTimer();
    
    // 发送回复到后端
    sendMessage({
      type: 'clarification_response',
      request_id: currentAlignment.id,
      response,
      timestamp: Date.now()
    });
    
    console.log('[useAlignment] 发送澄清回复:', { requestId: currentAlignment.id, response });
    
    // 延迟后处理下一个
    setTimeout(() => {
      setPendingQueue(prev => {
        const filtered = prev.filter(p => p.id !== currentAlignment.id);
        
        if (filtered.length > 0) {
          const next = filtered[0];
          setCurrentAlignment(next);
          setIsProcessing(false);
          
          if (next.timeout > 0) {
            timeoutRef.current = setTimeout(() => {
              handleTimeout(next.id);
            }, next.timeout * 1000);
          }
        } else {
          setCurrentAlignment(null);
          setIsProcessing(false);
        }
        
        return filtered;
      });
    }, 300);
  }, [currentAlignment, sendMessage, clearTimeoutTimer, handleTimeout]);

  /**
   * 发送确认回复
   */
  const sendConfirmation = useCallback((confirmed: boolean) => {
    if (!currentAlignment) return;
    
    setIsProcessing(true);
    clearTimeoutTimer();
    
    // 发送回复到后端
    sendMessage({
      type: 'confirmation_response',
      request_id: currentAlignment.id,
      response: confirmed,
      timestamp: Date.now()
    });
    
    console.log('[useAlignment] 发送确认回复:', { requestId: currentAlignment.id, confirmed });
    
    // 延迟后处理下一个
    setTimeout(() => {
      setPendingQueue(prev => {
        const filtered = prev.filter(p => p.id !== currentAlignment.id);
        
        if (filtered.length > 0) {
          const next = filtered[0];
          setCurrentAlignment(next);
          setIsProcessing(false);
          
          if (next.timeout > 0) {
            timeoutRef.current = setTimeout(() => {
              handleTimeout(next.id);
            }, next.timeout * 1000);
          }
        } else {
          setCurrentAlignment(null);
          setIsProcessing(false);
        }
        
        return filtered;
      });
    }, 300);
  }, [currentAlignment, sendMessage, clearTimeoutTimer, handleTimeout]);

  /**
   * 取消当前请求
   */
  const cancelAlignment = useCallback(() => {
    if (!currentAlignment) return;
    
    clearTimeoutTimer();
    
    // 发送取消消息
    sendMessage({
      type: currentAlignment.type === 'clarification' 
        ? 'clarification_cancelled' 
        : 'confirmation_cancelled',
      request_id: currentAlignment.id,
      timestamp: Date.now()
    });
    
    console.log('[useAlignment] 取消对齐请求:', currentAlignment.id);
    
    setPendingQueue(prev => {
      const filtered = prev.filter(p => p.id !== currentAlignment.id);
      
      if (filtered.length > 0) {
        const next = filtered[0];
        setCurrentAlignment(next);
        setIsProcessing(false);
        
        if (next.timeout > 0) {
          timeoutRef.current = setTimeout(() => {
            handleTimeout(next.id);
          }, next.timeout * 1000);
        }
      } else {
        setCurrentAlignment(null);
        setIsProcessing(false);
      }
      
      return filtered;
    });
  }, [currentAlignment, sendMessage, clearTimeoutTimer, handleTimeout]);

  /**
   * 清除所有待处理请求
   */
  const clearAll = useCallback(() => {
    clearTimeoutTimer();
    
    // 取消所有待处理请求
    pendingQueue.forEach(alignment => {
      sendMessage({
        type: alignment.type === 'clarification' 
          ? 'clarification_cancelled' 
          : 'confirmation_cancelled',
        request_id: alignment.id,
        timestamp: Date.now()
      });
    });
    
    setPendingQueue([]);
    setCurrentAlignment(null);
    setIsProcessing(false);
    
    console.log('[useAlignment] 清除所有对齐请求');
  }, [pendingQueue, sendMessage, clearTimeoutTimer]);

  /**
   * 清理
   */
  useEffect(() => {
    return () => {
      clearTimeoutTimer();
    };
  }, [clearTimeoutTimer]);

  /**
   * 连接断开时清除所有请求
   */
  useEffect(() => {
    if (!isConnected) {
      clearAll();
    }
  }, [isConnected, clearAll]);

  return {
    dialogProps: {
      type: currentAlignment?.type || 'clarification',
      question: currentAlignment?.question || '',
      options: currentAlignment?.options,
      confirmMessage: currentAlignment?.confirmMessage,
      isOpen: !!currentAlignment && !isProcessing,
      timeout: currentAlignment?.timeout
    },
    isOpen: !!currentAlignment && !isProcessing,
    hasPending: pendingQueue.length > 0,
    pendingCount: pendingQueue.length,
    sendClarification,
    sendConfirmation,
    cancelAlignment,
    clearAll,
    processNext
  };
}

/**
 * 使用队列的高级Hook - 支持Promise风格的请求
 */
export function useAlignmentQueue() {
  const [queue, setQueue] = useState<AlignmentQueueItem[]>([]);
  const resolversRef = useRef<Map<string, (value: string | boolean) => void>>(new Map());

  /**
   * 添加对齐请求到队列
   */
  const requestAlignment = useCallback((
    type: AlignmentType,
    question: string,
    options?: { options?: string[]; confirmMessage?: string; timeout?: number }
  ): Promise<string | boolean> => {
    return new Promise((resolve) => {
      const id = `align_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      
      resolversRef.current.set(id, resolve);
      
      const newItem: AlignmentQueueItem = {
        id,
        type,
        question,
        options: options?.options,
        confirmMessage: options?.confirmMessage,
        timeout: options?.timeout || 60,
        resolve
      };
      
      setQueue(prev => [...prev, newItem]);
    });
  }, []);

  /**
   * 处理确认
   */
  const handleConfirm = useCallback((id: string) => {
    const resolve = resolversRef.current.get(id);
    if (resolve) {
      resolve(true);
      resolversRef.current.delete(id);
    }
    setQueue(prev => prev.filter(item => item.id !== id));
  }, []);

  /**
   * 处理澄清/拒绝
   */
  const handleClarify = useCallback((id: string, response: string) => {
    const resolve = resolversRef.current.get(id);
    if (resolve) {
      resolve(response);
      resolversRef.current.delete(id);
    }
    setQueue(prev => prev.filter(item => item.id !== id));
  }, []);

  /**
   * 处理取消
   */
  const handleCancel = useCallback((id: string) => {
    const resolve = resolversRef.current.get(id);
    if (resolve) {
      resolve('cancelled');
      resolversRef.current.delete(id);
    }
    setQueue(prev => prev.filter(item => item.id !== id));
  }, []);

  /**
   * 请求澄清（Promise风格）
   */
  const requestClarification = useCallback((
    question: string,
    options: string[],
    timeout?: number
  ): Promise<string> => {
    return requestAlignment('clarification', question, { options, timeout }) as Promise<string>;
  }, [requestAlignment]);

  /**
   * 请求确认（Promise风格）
   */
  const requestConfirmation = useCallback((
    question: string,
    confirmMessage: string,
    timeout?: number
  ): Promise<boolean> => {
    return requestAlignment('confirmation', question, { confirmMessage, timeout }) as Promise<boolean>;
  }, [requestAlignment]);

  return {
    queue,
    requestAlignment,
    requestClarification,
    requestConfirmation,
    handleConfirm,
    handleClarify,
    handleCancel,
    hasPending: queue.length > 0,
    count: queue.length
  };
}

export default useAlignment;
