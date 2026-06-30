/**
 * ErrorHandler - 全局错误处理组件
 * Phase 5 Week 9 - 用户体验优化
 * 
 * 功能：
 * - 网络错误检测和提示
 * - 离线状态检测
 * - 重试机制
 * - 错误边界
 */

import { useState, useEffect, ReactNode, Component, ErrorInfo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  WifiOff, RefreshCw, AlertTriangle, X, 
  Signal, SignalHigh, SignalLow, Loader2 
} from 'lucide-react';

// ═══════════════════════════════════════════════════════════════════
// 网络状态监测
// ═══════════════════════════════════════════════════════════════════

interface NetworkStatus {
  online: boolean;
  type?: string;
  effectiveType?: string;
  downlink?: number;
  rtt?: number;
}

export function useNetworkStatus() {
  const [status, setStatus] = useState<NetworkStatus>({
    online: navigator.onLine,
  });

  useEffect(() => {
    const updateStatus = () => {
      const newStatus: NetworkStatus = {
        online: navigator.onLine,
      };

      // 获取网络信息（如果浏览器支持）
      const connection = (navigator as any).connection;
      if (connection) {
        newStatus.type = connection.type;
        newStatus.effectiveType = connection.effectiveType;
        newStatus.downlink = connection.downlink;
        newStatus.rtt = connection.rtt;
      }

      setStatus(newStatus);
    };

    window.addEventListener('online', updateStatus);
    window.addEventListener('offline', updateStatus);

    const connection = (navigator as any).connection;
    if (connection) {
      connection.addEventListener('change', updateStatus);
    }

    // 初始更新
    updateStatus();

    return () => {
      window.removeEventListener('online', updateStatus);
      window.removeEventListener('offline', updateStatus);
      if (connection) {
        connection.removeEventListener('change', updateStatus);
      }
    };
  }, []);

  return status;
}

// ═══════════════════════════════════════════════════════════════════
// 离线提示组件
// ═══════════════════════════════════════════════════════════════════

interface OfflineBannerProps {
  onRetry?: () => void;
}

export function OfflineBanner({ onRetry }: OfflineBannerProps) {
  const [isRetrying, setIsRetrying] = useState(false);

  const handleRetry = async () => {
    setIsRetrying(true);
    try {
      await onRetry?.();
    } finally {
      setIsRetrying(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="fixed top-0 left-0 right-0 z-50 bg-gradient-to-r from-amber-500/20 to-orange-500/20 border-b border-amber-500/30"
    >
      <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-amber-500/20">
            <WifiOff className="w-5 h-5 text-amber-400" />
          </div>
          <div>
            <p className="text-sm font-medium text-amber-200">
              网络连接已断开
            </p>
            <p className="text-xs text-amber-400/70">
              请检查网络设置，部分功能可能无法使用
            </p>
          </div>
        </div>
        
        <button
          onClick={handleRetry}
          disabled={isRetrying}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-500/20 text-amber-300 text-sm hover:bg-amber-500/30 transition-colors disabled:opacity-50"
        >
          {isRetrying ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          重试连接
        </button>
      </div>
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 网络状态指示器
// ═══════════════════════════════════════════════════════════════════

interface NetworkIndicatorProps {
  className?: string;
}

export function NetworkIndicator({ className = '' }: NetworkIndicatorProps) {
  const status = useNetworkStatus();

  const getIcon = () => {
    if (!status.online) {
      return <WifiOff className="w-4 h-4 text-red-400" />;
    }
    
    if (status.effectiveType) {
      switch (status.effectiveType) {
        case '4g':
          return <SignalHigh className="w-4 h-4 text-emerald-400" />;
        case '3g':
          return <Signal className="w-4 h-4 text-yellow-400" />;
        default:
          return <SignalLow className="w-4 h-4 text-orange-400" />;
      }
    }
    
    return <Signal className="w-4 h-4 text-emerald-400" />;
  };

  return (
    <div 
      className={`flex items-center gap-1.5 ${className}`}
      title={status.online ? `在线 - ${status.effectiveType || 'unknown'}` : '离线'}
    >
      {getIcon()}
      {!status.online && (
        <span className="text-xs text-red-400">离线</span>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// API错误提示组件
// ═══════════════════════════════════════════════════════════════════

interface APIErrorToastProps {
  error: Error | null;
  onRetry?: () => void;
  onDismiss?: () => void;
  duration?: number; // 自动关闭时间，0表示不自动关闭
}

export function APIErrorToast({ 
  error, 
  onRetry, 
  onDismiss, 
  duration = 5000 
}: APIErrorToastProps) {
  const [isRetrying, setIsRetrying] = useState(false);
  const [progress, setProgress] = useState(100);

  useEffect(() => {
    if (duration > 0 && error) {
      const startTime = Date.now();
      const timer = setInterval(() => {
        const elapsed = Date.now() - startTime;
        const remaining = Math.max(0, 100 - (elapsed / duration) * 100);
        setProgress(remaining);
        
        if (remaining <= 0) {
          onDismiss?.();
        }
      }, 50);

      return () => clearInterval(timer);
    }
  }, [error, duration, onDismiss]);

  if (!error) return null;

  const handleRetry = async () => {
    setIsRetrying(true);
    try {
      await onRetry?.();
      onDismiss?.();
    } finally {
      setIsRetrying(false);
    }
  };

  // 解析错误类型
  const getErrorInfo = () => {
    const message = error.message.toLowerCase();
    
    if (message.includes('timeout') || message.includes('超时')) {
      return {
        icon: <RefreshCw className="w-5 h-5 text-orange-400" />,
        title: '请求超时',
        description: '服务器响应时间过长，请稍后重试',
        color: 'orange'
      };
    }
    
    if (message.includes('network') || message.includes('fetch') || message.includes('网络')) {
      return {
        icon: <WifiOff className="w-5 h-5 text-red-400" />,
        title: '网络错误',
        description: '无法连接到服务器，请检查网络',
        color: 'red'
      };
    }
    
    if (message.includes('401') || message.includes('unauthorized') || message.includes('登录')) {
      return {
        icon: <AlertTriangle className="w-5 h-5 text-amber-400" />,
        title: '登录已过期',
        description: '请重新登录以继续使用',
        color: 'amber'
      };
    }
    
    return {
      icon: <AlertTriangle className="w-5 h-5 text-red-400" />,
      title: '操作失败',
      description: error.message,
      color: 'red'
    };
  };

  const errorInfo = getErrorInfo();

  return (
    <motion.div
      initial={{ opacity: 0, x: 100 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 100 }}
      className={`
        fixed bottom-4 right-4 z-50
        max-w-md w-full
        bg-sb-bg-secondary border border-${errorInfo.color}-500/30
        rounded-xl shadow-2xl overflow-hidden
      `}
    >
      {/* 进度条 */}
      {duration > 0 && (
        <div 
          className={`h-1 bg-${errorInfo.color}-500/30`}
          style={{ width: `${progress}%`, transition: 'width 50ms linear' }}
        />
      )}
      
      <div className="p-4 flex items-start gap-3">
        <div className={`p-2 rounded-lg bg-${errorInfo.color}-500/10 shrink-0`}>
          {errorInfo.icon}
        </div>
        
        <div className="flex-1 min-w-0">
          <h4 className={`text-sm font-medium text-${errorInfo.color}-400`}>
            {errorInfo.title}
          </h4>
          <p className="text-xs text-slate-400 mt-1">
            {errorInfo.description}
          </p>
          
          <div className="flex items-center gap-2 mt-3">
            {onRetry && (
              <button
                onClick={handleRetry}
                disabled={isRetrying}
                className={`
                  flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs
                  bg-${errorInfo.color}-500/20 text-${errorInfo.color}-300
                  hover:bg-${errorInfo.color}-500/30
                  disabled:opacity-50
                  transition-colors
                `}
              >
                {isRetrying ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="w-3.5 h-3.5" />
                )}
                重试
              </button>
            )}
            
            <button
              onClick={onDismiss}
              className="px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white hover:bg-white/5 transition-colors"
            >
              关闭
            </button>
          </div>
        </div>
        
        <button
          onClick={onDismiss}
          className="p-1 rounded hover:bg-white/10 text-slate-400 hover:text-white transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 错误边界组件
// ═══════════════════════════════════════════════════════════════════

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('[ErrorBoundary] 捕获到错误:', error, errorInfo);
    this.props.onError?.(error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="min-h-[200px] flex items-center justify-center p-6">
          <div className="text-center max-w-md">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-red-500/10 flex items-center justify-center">
              <AlertTriangle className="w-8 h-8 text-red-400" />
            </div>
            <h3 className="text-lg font-semibold text-white mb-2">
              出现了一些问题
            </h3>
            <p className="text-sm text-slate-400 mb-4">
              {this.state.error?.message || '组件渲染出错，请尝试刷新页面'}
            </p>
            <div className="flex items-center justify-center gap-3">
              <button
                onClick={this.handleReset}
                className="px-4 py-2 rounded-lg bg-cyan-500/20 text-cyan-300 text-sm hover:bg-cyan-500/30 transition-colors"
              >
                重试
              </button>
              <button
                onClick={() => window.location.reload()}
                className="px-4 py-2 rounded-lg bg-white/5 text-slate-300 text-sm hover:bg-white/10 transition-colors"
              >
                刷新页面
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

// ═══════════════════════════════════════════════════════════════════
// 全局错误处理器
// ═══════════════════════════════════════════════════════════════════

interface GlobalErrorHandlerProps {
  children: ReactNode;
}

export function GlobalErrorHandler({ children }: GlobalErrorHandlerProps) {
  const networkStatus = useNetworkStatus();
  const [apiError, setApiError] = useState<Error | null>(null);

  // 监听全局API错误
  useEffect(() => {
    const handleApiError = (event: CustomEvent<Error>) => {
      setApiError(event.detail);
    };

    window.addEventListener('api:error' as any, handleApiError);
    return () => window.removeEventListener('api:error' as any, handleApiError);
  }, []);

  const handleRetry = async () => {
    // 触发全局重试事件
    window.dispatchEvent(new CustomEvent('api:retry'));
  };

  return (
    <>
      {/* 离线提示 */}
      <AnimatePresence>
        {!networkStatus.online && (
          <OfflineBanner onRetry={handleRetry} />
        )}
      </AnimatePresence>

      {/* API错误提示 */}
      <AnimatePresence>
        {apiError && (
          <APIErrorToast
            error={apiError}
            onRetry={handleRetry}
            onDismiss={() => setApiError(null)}
            duration={8000}
          />
        )}
      </AnimatePresence>

      {/* 网络状态指示器（可选显示在UI中） */}
      {/* <NetworkIndicator className="fixed bottom-4 left-4" /> */}

      {children}
    </>
  );
}

// 导出工具函数
export function triggerApiError(error: Error) {
  window.dispatchEvent(new CustomEvent('api:error', { detail: error }));
}

export function isNetworkError(error: unknown): boolean {
  if (error instanceof Error) {
    const message = error.message.toLowerCase();
    return message.includes('network') || 
           message.includes('fetch') ||
           message.includes('timeout') ||
           message.includes('failed to fetch') ||
           message.includes('网络');
  }
  return false;
}
