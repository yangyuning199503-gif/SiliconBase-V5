/**
 * AIStatusIndicator - AI状态指示器组件
 * 
 * 功能：
 * - 显示AI当前状态（思考中/执行中/等待中/已完成）
 * - 显示当前执行动作
 * - 显示进度条（如果有）
 * - 通过WebSocket实时更新
 */

import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { 
  Brain, 
  CheckCircle2, 
  AlertCircle, 
  Clock,
  Activity,
  Zap,
  PauseCircle
} from 'lucide-react';

// AI状态类型
export type AIState = 'idle' | 'thinking' | 'executing' | 'waiting' | 'error' | 'completed';

// 状态配置
const STATE_CONFIG: Record<AIState, {
  label: string;
  color: string;
  bgColor: string;
  icon: React.ReactNode;
  animation?: string;
}> = {
  idle: {
    label: '空闲',
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/10',
    icon: <Activity className="w-4 h-4" />
  },
  thinking: {
    label: '思考中',
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/10',
    icon: <Brain className="w-4 h-4" />,
    animation: 'pulse'
  },
  executing: {
    label: '执行中',
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10',
    icon: <Zap className="w-4 h-4" />,
    animation: 'spin-slow'
  },
  waiting: {
    label: '等待中',
    color: 'text-orange-400',
    bgColor: 'bg-orange-500/10',
    icon: <PauseCircle className="w-4 h-4" />
  },
  error: {
    label: '出错',
    color: 'text-red-400',
    bgColor: 'bg-red-500/10',
    icon: <AlertCircle className="w-4 h-4" />
  },
  completed: {
    label: '已完成',
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10',
    icon: <CheckCircle2 className="w-4 h-4" />
  }
};

// 状态接口
interface AIStatus {
  state: AIState;
  current_action: string;
  progress?: number;
  estimated_remaining?: number;
  details?: Record<string, any>;
}

interface AIStatusIndicatorProps {
  className?: string;
  showProgress?: boolean;
  showDetails?: boolean;
  compact?: boolean;
}

export const AIStatusIndicator: React.FC<AIStatusIndicatorProps> = ({
  className = '',
  showProgress = true,
  showDetails = true,
  compact = false
}) => {
  const [status, setStatus] = useState<AIStatus>({
    state: 'idle',
    current_action: '准备就绪'
  });
  const [isConnected, setIsConnected] = useState(false);

  // 建立WebSocket连接
  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('silicon_user') || '{}');
    const userId = user.user_id || 'default';
    const token = localStorage.getItem('silicon_token');
    const wsUrl = `ws://${window.location.host}/ws/ai-status/${userId}${token ? `?token=${token}` : ''}`;
    const websocket = new WebSocket(wsUrl);

    websocket.onopen = () => {
      setIsConnected(true);
      console.log('[AIStatus] WebSocket连接成功');
    };

    websocket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);

        switch (message.type) {
          case 'status':
          case 'heartbeat':
            if (message.data) setStatus(message.data);
            break;
          case 'state_change':
            if (message.data?.new_state) {
              setStatus(prev => ({
                ...prev,
                state: message.data.new_state,
                current_action: message.data.action || prev?.current_action
              }));
            }
            break;
          case 'error':
            console.error('[AIStatus] 收到错误:', message.message || '未知错误');
            break;
        }
      } catch (e) {
        console.error('[AIStatus] 解析消息失败:', e);
      }
    };

    websocket.onclose = () => {
      setIsConnected(false);
      console.log('[AIStatus] WebSocket连接关闭');
    };

    websocket.onerror = (event) => {
      console.error('[AIStatus] WebSocket错误事件:', event.type);
    };
    
    // 心跳
    const heartbeat = setInterval(() => {
      if (websocket.readyState === WebSocket.OPEN) {
        websocket.send('ping');
      }
    }, 30000);
    
    return () => {
      clearInterval(heartbeat);
      websocket.close();
    };
  }, []);

  // 格式化剩余时间
  const formatRemaining = (seconds?: number): string => {
    if (!seconds) return '';
    if (seconds < 60) return `${seconds}秒`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟`;
    return `${Math.floor(seconds / 3600)}小时${Math.floor((seconds % 3600) / 60)}分钟`;
  };

  const config = STATE_CONFIG[status.state];
  const progress = status.progress || 0;

  // 紧凑模式
  if (compact) {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <motion.div
          className={`flex items-center gap-1.5 px-2 py-1 rounded-full ${config.bgColor}`}
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
        >
          <motion.div
            animate={config.animation === 'pulse' ? {
              scale: [1, 1.2, 1],
              opacity: [1, 0.7, 1]
            } : config.animation === 'spin-slow' ? {
              rotate: 360
            } : {}}
            transition={{
              duration: config.animation === 'spin-slow' ? 2 : 1.5,
              repeat: Infinity,
              ease: "easeInOut"
            }}
          >
            {config.icon}
          </motion.div>
          <span className={`text-xs font-medium ${config.color}`}>
            {config.label}
          </span>
        </motion.div>
        
        {/* 连接状态指示 */}
        <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
      </div>
    );
  }

  return (
    <div className={`bg-slate-900/80 border border-slate-700 rounded-xl p-4 ${className}`}>
      {/* 头部：状态和连接 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <motion.div
            className={`flex items-center justify-center w-10 h-10 rounded-xl ${config.bgColor}`}
            animate={config.animation === 'pulse' ? {
              scale: [1, 1.1, 1]
            } : {}}
            transition={{ duration: 1.5, repeat: Infinity }}
          >
            <motion.div
              animate={config.animation === 'spin-slow' ? {
                rotate: 360
              } : {}}
              transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
              className={config.color}
            >
              {config.icon}
            </motion.div>
          </motion.div>
          
          <div>
            <h3 className={`font-semibold ${config.color}`}>
              {config.label}
            </h3>
            <p className="text-sm text-slate-400">
              {status.current_action}
            </p>
          </div>
        </div>
        
        {/* 连接状态 */}
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'} ${isConnected ? 'animate-pulse' : ''}`} />
          <span className="text-xs text-slate-500">
            {isConnected ? '已连接' : '断开'}
          </span>
        </div>
      </div>

      {/* 进度条 */}
      {showProgress && status.progress !== undefined && (
        <div className="mb-3">
          <div className="flex justify-between text-xs text-slate-400 mb-1">
            <span>进度</span>
            <span>{Math.round(progress)}%</span>
          </div>
          <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
            <motion.div
              className={`h-full rounded-full ${
                status.state === 'error' ? 'bg-red-500' :
                status.state === 'completed' ? 'bg-emerald-500' :
                'bg-blue-500'
              }`}
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.5, ease: "easeOut" }}
            />
          </div>
        </div>
      )}

      {/* 详情 */}
      {showDetails && (
        <div className="flex items-center justify-between text-xs text-slate-500">
          <div className="flex items-center gap-4">
            {status.estimated_remaining && (
              <div className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                <span>预计剩余: {formatRemaining(status.estimated_remaining)}</span>
              </div>
            )}
            
            {status.details?.announcements !== undefined && (
              <div className="flex items-center gap-1">
                <Activity className="w-3 h-3" />
                <span>播报: {status.details.announcements}次</span>
              </div>
            )}
          </div>
          
          {/* 通知级别 */}
          {status.details?.level && (
            <span className="px-2 py-0.5 bg-slate-700 rounded text-slate-400">
              {status.details.level}
            </span>
          )}
        </div>
      )}
    </div>
  );
};

// 独立的状态徽章组件
export const AIStatusBadge: React.FC<{ state: AIState; className?: string }> = ({ 
  state, 
  className = '' 
}) => {
  const config = STATE_CONFIG[state];
  
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${config.bgColor} ${config.color} ${className}`}>
      {config.icon}
      {config.label}
    </span>
  );
};

export default AIStatusIndicator;
