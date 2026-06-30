import { useEffect, useState, useCallback } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { Mic, Volume2, Loader2, AlertCircle } from 'lucide-react';

/**
 * 语音状态类型
 */
type VoiceState = 'idle' | 'awake' | 'speaking' | 'listening';

/**
 * VoiceStateIndicator 组件
 * 
 * 显示当前语音状态，包括：
 * - 唤醒状态: 显示"正在倾听"动画
 * - 播报状态: 显示进度条
 * - 系统播报保护期: 显示"请稍候"
 * - 识别状态: 显示录音中
 * 
 * 通过 WebSocket 接收后端语音状态变化
 */
export function VoiceStateIndicator() {
  const { lastMessage, isConnected } = useWebSocket();
  
  // 当前语音状态
  const [voiceState, setVoiceState] = useState<VoiceState>('idle');
  
  // 保护期结束时间（毫秒时间戳）
  const [protectedUntil, setProtectedUntil] = useState<number | null>(null);
  
  // 是否处于保护期
  const [isProtected, setIsProtected] = useState(false);
  
  // 保护期倒计时（秒）
  const [protectedCountdown, setProtectedCountdown] = useState(0);
  
  // 错误状态（用于降级到轮询时的错误显示）
  const [hasError, setHasError] = useState(false);

  /**
   * 处理 WebSocket 消息
   */
  useEffect(() => {
    if (!lastMessage) return;

    // 处理语音状态变化消息
    if (lastMessage.type === 'voice_state_change') {
      const data = lastMessage.data;
      if (!data) {
        console.error('[SILENT_FAILURE_BLOCKED] voice_state_change消息缺少data')
        return
      }
      
      const voiceState = (data.state as VoiceState) || 'idle'
      console.log('[VoiceState] 收到状态变化:', voiceState, data);
      
      // 更新状态
      setVoiceState(voiceState);
      setHasError(false);
      
      // 处理保护期
      const protectedUntil = data?.protected_until as number | undefined
      if (protectedUntil && protectedUntil > Date.now()) {
        setProtectedUntil(protectedUntil);
        setIsProtected(protectedUntil > Date.now());
        
        // 计算倒计时
        const remaining = Math.ceil((protectedUntil - Date.now()) / 1000);
        setProtectedCountdown(Math.max(0, remaining));
      } else {
        setProtectedUntil(null);
        setIsProtected(false);
        setProtectedCountdown(0);
      }
    }
  }, [lastMessage]);

  /**
   * 保护期倒计时
   */
  useEffect(() => {
    if (!isProtected || !protectedUntil) return;

    const interval = setInterval(() => {
      const remaining = Math.ceil((protectedUntil - Date.now()) / 1000);
      
      if (remaining <= 0) {
        setIsProtected(false);
        setProtectedCountdown(0);
        clearInterval(interval);
      } else {
        setProtectedCountdown(remaining);
      }
    }, 100);

    return () => clearInterval(interval);
  }, [isProtected, protectedUntil]);

  /**
   * WebSocket 断开时的降级处理
   * 当 WebSocket 断开超过5秒后，显示错误状态
   */
  useEffect(() => {
    if (!isConnected) {
      const timer = setTimeout(() => {
        setHasError(true);
      }, 5000);
      return () => clearTimeout(timer);
    } else {
      setHasError(false);
    }
  }, [isConnected]);

  /**
   * 获取状态显示配置
   */
  const getStateConfig = useCallback(() => {
    switch (voiceState) {
      case 'awake':
        return {
          icon: <Mic className="w-5 h-5 text-blue-500 animate-pulse" />,
          text: '正在倾听',
          bgColor: 'bg-blue-50',
          borderColor: 'border-blue-200',
          textColor: 'text-blue-700',
          showWave: true,
        };
      case 'speaking':
        return {
          icon: <Volume2 className="w-5 h-5 text-green-500" />,
          text: isProtected ? `系统播报中 (${protectedCountdown}s)` : '正在播报',
          bgColor: 'bg-green-50',
          borderColor: 'border-green-200',
          textColor: 'text-green-700',
          showProgress: true,
        };
      case 'listening':
        return {
          icon: <Mic className="w-5 h-5 text-purple-500 animate-bounce" />,
          text: '录音中...',
          bgColor: 'bg-purple-50',
          borderColor: 'border-purple-200',
          textColor: 'text-purple-700',
          showWave: true,
        };
      case 'idle':
      default:
        return {
          icon: null,
          text: hasError ? '状态同步失败' : '',
          bgColor: hasError ? 'bg-red-50' : 'bg-gray-50',
          borderColor: hasError ? 'border-red-200' : 'border-gray-200',
          textColor: hasError ? 'text-red-600' : 'text-gray-500',
          showWave: false,
        };
    }
  }, [voiceState, isProtected, protectedCountdown, hasError]);

  const config = getStateConfig();

  // 如果处于空闲状态且没有错误，不显示指示器
  if (voiceState === 'idle' && !hasError) {
    return null;
  }

  return (
    <div
      className={`
        fixed bottom-20 left-1/2 transform -translate-x-1/2
        flex items-center gap-3 px-4 py-2.5 rounded-full
        border shadow-lg transition-all duration-300
        ${config.bgColor} ${config.borderColor}
        z-50
      `}
    >
      {/* 错误指示 */}
      {hasError && (
        <AlertCircle className="w-4 h-4 text-red-500" />
      )}
      
      {/* 图标 */}
      {config.icon && (
        <div className="flex-shrink-0">
          {config.icon}
        </div>
      )}
      
      {/* 文字 */}
      <span className={`text-sm font-medium ${config.textColor}`}>
        {config.text}
      </span>
      
      {/* 声波动画 - 倾听/识别状态 */}
      {config.showWave && (
        <div className="flex items-center gap-0.5">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className={`
                w-1 rounded-full
                ${voiceState === 'listening' ? 'bg-purple-400' : 'bg-blue-400'}
                animate-pulse
              `}
              style={{
                height: `${12 + i * 4}px`,
                animationDelay: `${i * 0.15}s`,
                animationDuration: '0.8s',
              }}
            />
          ))}
        </div>
      )}
      
      {/* 进度条 - 播报状态 */}
      {config.showProgress && (
        <div className="w-16 h-1 bg-gray-200 rounded-full overflow-hidden">
          <div 
            className={`
              h-full rounded-full
              ${isProtected ? 'bg-orange-400' : 'bg-green-400'}
              transition-all duration-300
            `}
            style={{
              width: isProtected 
                ? `${((5 - protectedCountdown) / 5) * 100}%` 
                : '60%',
              animation: isProtected ? 'none' : 'progress 2s ease-in-out infinite',
            }}
          />
        </div>
      )}
      
      {/* 保护期提示 */}
      {isProtected && (
        <span className="text-xs text-orange-600 font-medium">
          请稍候
        </span>
      )}
      
      {/* 未连接提示 */}
      {!isConnected && !hasError && (
        <Loader2 className="w-4 h-4 text-gray-400 animate-spin" />
      )}
    </div>
  );
}

/**
 * VoiceStateIndicator 样式
 * 添加到全局 CSS 中
 */
export const voiceStateStyles = `
@keyframes progress {
  0% { width: 0%; }
  50% { width: 100%; }
  100% { width: 0%; }
}
`;

export default VoiceStateIndicator;
