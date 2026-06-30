import React, { useEffect, useState } from 'react';
import { useModeSwitch } from '../hooks/useModeSwitch';
import { 
  Loader2, 
  CheckCircle2, 
  AlertCircle, 
  MessageCircle, 
  Target,
  RefreshCw,
  WifiOff
} from 'lucide-react';

/**
 * ModeSwitchIndicator 组件
 * 
 * 显示模式切换的实时状态，包括：
 * - 切换动画
 * - 进度条
 * - 恢复的上下文
 * - 错误提示
 */
export const ModeSwitchIndicator: React.FC = () => {
  const { 
    mode, 
    switching, 
    progress, 
    context, 
    switchState,
    isConnected, 
    hasError, 
    errorMessage 
  } = useModeSwitch();

  // 是否显示组件
  const [isVisible, setIsVisible] = useState(false);
  
  // 动画进度（平滑过渡）
  const [animatedProgress, setAnimatedProgress] = useState(0);

  /**
   * 控制显示/隐藏
   */
  useEffect(() => {
    const isCompleted = switchState === 'completed'
    if (switching || hasError || isCompleted) {
      setIsVisible(true);
    } else {
      // 延迟隐藏，让用户看到完成状态
      const timer = setTimeout(() => {
        setIsVisible(false);
      }, isCompleted ? 2000 : 0);
      return () => clearTimeout(timer);
    }
  }, [switching, hasError, switchState]);

  /**
   * 平滑进度动画
   */
  useEffect(() => {
    if (progress > animatedProgress) {
      const diff = progress - animatedProgress;
      const step = diff * 0.1;
      const timer = setTimeout(() => {
        setAnimatedProgress(prev => Math.min(prev + step, progress));
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [progress, animatedProgress]);

  /**
   * 获取状态配置
   */
  const getStateConfig = () => {
    // WebSocket断开
    if (!isConnected && hasError) {
      return {
        icon: <WifiOff className="w-5 h-5 text-orange-500" />,
        title: '连接断开',
        message: errorMessage || '连接断开，正在重试...',
        bgColor: 'bg-orange-50',
        borderColor: 'border-orange-200',
        textColor: 'text-orange-700',
        progressColor: 'bg-orange-400',
        showProgress: false,
      };
    }

    // 切换失败
    if (switchState === 'failed' || hasError) {
      return {
        icon: <AlertCircle className="w-5 h-5 text-red-500" />,
        title: '状态恢复失败',
        message: errorMessage || '模式切换失败',
        bgColor: 'bg-red-50',
        borderColor: 'border-red-200',
        textColor: 'text-red-700',
        progressColor: 'bg-red-400',
        showProgress: false,
      };
    }

    // 切换完成
    if (switchState === 'completed') {
      const isTaskMode = mode === 'focus';
      return {
        icon: <CheckCircle2 className={`w-5 h-5 ${isTaskMode ? 'text-emerald-500' : 'text-amber-500'}`} />,
        title: isTaskMode ? '已进入专注模式' : '已进入日常模式',
        message: context?.goal ? `已恢复：${context.goal}` : '模式切换完成',
        bgColor: isTaskMode ? 'bg-emerald-50' : 'bg-amber-50',
        borderColor: isTaskMode ? 'border-emerald-200' : 'border-amber-200',
        textColor: isTaskMode ? 'text-emerald-700' : 'text-amber-700',
        progressColor: isTaskMode ? 'bg-emerald-400' : 'bg-amber-400',
        showProgress: false,
      };
    }

    // 切换中
    if (switching) {
      const targetMode = mode === 'daily' ? '专注' : '日常';
      return {
        icon: <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />,
        title: `正在切换到${targetMode}模式...`,
        message: context?.working_memory_summary || '正在恢复上下文...',
        bgColor: 'bg-blue-50',
        borderColor: 'border-blue-200',
        textColor: 'text-blue-700',
        progressColor: 'bg-blue-400',
        showProgress: true,
      };
    }

    // 默认
    return {
      icon: null,
      title: '',
      message: '',
      bgColor: 'bg-gray-50',
      borderColor: 'border-gray-200',
      textColor: 'text-gray-700',
      progressColor: 'bg-gray-400',
      showProgress: false,
    };
  };

  const config = getStateConfig();

  // 如果不显示，返回null
  if (!isVisible) {
    return null;
  }

  return (
    <div
      className={`
        fixed top-20 left-1/2 transform -translate-x-1/2
        z-50 animate-in fade-in slide-in-from-top-4 duration-300
      `}
    >
      <div
        className={`
          flex flex-col gap-3 px-5 py-4 rounded-xl
          border shadow-xl backdrop-blur-sm
          min-w-[320px] max-w-[480px]
          transition-all duration-300
          ${config.bgColor} ${config.borderColor}
        `}
      >
        {/* 头部：图标 + 标题 */}
        <div className="flex items-center gap-3">
          {/* 图标 */}
          {config.icon && (
            <div className={`
              flex-shrink-0 p-2 rounded-full
              ${switchState === 'completed' ? 'bg-white/80' : 'bg-white/50'}
            `}>
              {config.icon}
            </div>
          )}

          {/* 标题 */}
          <div className="flex-1 min-w-0">
            <h3 className={`font-semibold text-sm ${config.textColor}`}>
              {config.title}
            </h3>
            
            {/* 子消息 */}
            {config.message && (
              <p className={`text-xs mt-0.5 truncate ${config.textColor} opacity-80`}>
                {config.message}
              </p>
            )}
          </div>

          {/* 模式图标 */}
          {switchState === 'completed' && (
            <div className="flex-shrink-0">
              {mode === 'focus' ? (
                <Target className="w-5 h-5 text-emerald-500" />
              ) : (
                <MessageCircle className="w-5 h-5 text-amber-500" />
              )}
            </div>
          )}
        </div>

        {/* 进度条 */}
        {config.showProgress && (
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-gray-500">
              <span>切换进度</span>
              <span>{Math.round(animatedProgress * 100)}%</span>
            </div>
            <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className={`
                  h-full rounded-full transition-all duration-300 ease-out
                  ${config.progressColor}
                `}
                style={{
                  width: `${animatedProgress * 100}%`,
                }}
              />
            </div>
          </div>
        )}

        {/* 恢复的上下文详情 */}
        {switchState === 'completed' && context && (
          <div className={`
            mt-1 p-3 rounded-lg text-xs
            ${mode === 'focus' ? 'bg-emerald-100/50' : 'bg-amber-100/50'}
          `}>
            {context.goal && (
              <div className="flex items-start gap-2">
                <Target className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${mode === 'focus' ? 'text-emerald-600' : 'text-amber-600'}`} />
                <div>
                  <span className="font-medium opacity-70">目标：</span>
                  <span className={mode === 'focus' ? 'text-emerald-800' : 'text-amber-800'}>
                    {context.goal}
                  </span>
                </div>
              </div>
            )}
            {context.progress && (
              <div className="flex items-start gap-2 mt-1.5">
                <RefreshCw className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${mode === 'focus' ? 'text-emerald-600' : 'text-amber-600'}`} />
                <div>
                  <span className="font-medium opacity-70">进度：</span>
                  <span className={mode === 'focus' ? 'text-emerald-800' : 'text-amber-800'}>
                    {context.progress}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 错误时的操作提示 */}
        {(switchState === 'failed' || (hasError && !isConnected)) && (
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <RefreshCw className="w-3 h-3 animate-spin" />
            <span>
              {hasError && !isConnected 
                ? '尝试重新连接...' 
                : '正在创建新会话...'}
            </span>
          </div>
        )}
      </div>
    </div>
  );
};

/**
 * 小型模式指示器（用于嵌入其他组件）
 */
export const ModeSwitchBadge: React.FC = () => {
  const { mode, switching, progress } = useModeSwitch();

  if (switching) {
    return (
      <div className="flex items-center gap-2 px-2 py-1 bg-blue-100 text-blue-700 rounded-full text-xs">
        <Loader2 className="w-3 h-3 animate-spin" />
        <span>切换中 {Math.round(progress * 100)}%</span>
      </div>
    );
  }

  if (mode === 'focus') {
    return (
      <div className="flex items-center gap-1.5 px-2 py-1 bg-emerald-100 text-emerald-700 rounded-full text-xs">
        <Target className="w-3 h-3" />
        <span>专注模式</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1.5 px-2 py-1 bg-amber-100 text-amber-700 rounded-full text-xs">
      <MessageCircle className="w-3 h-3" />
      <span>日常模式</span>
    </div>
  );
};

export default ModeSwitchIndicator;
