/**
 * 用户确认节点组件 - "门下省-封驳" (User Confirmation Node)
 * 
 * 功能：
 * - 在关键步骤前添加用户确认
 * - 显示风险等级和操作详情
 * - 参考唐朝门下省封驳制度，体现审核机制
 */
import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Shield, 
  AlertTriangle, 
  AlertCircle, 
  Info,
  CheckCircle2, 
  XCircle,
  FileText,
  Clock,
  X,
  Eye,
  EyeOff,
  Gavel
} from 'lucide-react';

// 风险等级
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

// 用户确认属性
interface UserConfirmationProps {
  step: string;
  tool: string;
  params: Record<string, any>;
  riskLevel: RiskLevel;
  description?: string;
  timeout?: number; // 超时时间(秒)
  onConfirm: () => void;
  onReject: () => void;
  onTimeout?: () => void;
  className?: string;
  showDetails?: boolean;
}

// 风险等级配置
const RISK_CONFIG: Record<RiskLevel, { 
  label: string; 
  color: string;
  bgColor: string;
  borderColor: string;
  icon: React.ReactNode;
  description: string;
}> = {
  low: { 
    label: '低风险', 
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10',
    borderColor: 'border-blue-500/30',
    icon: <Info className="w-5 h-5" />,
    description: '常规操作，通常安全'
  },
  medium: { 
    label: '中风险', 
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/10',
    borderColor: 'border-amber-500/30',
    icon: <AlertCircle className="w-5 h-5" />,
    description: '需要留意的操作'
  },
  high: { 
    label: '高风险', 
    color: 'text-orange-400',
    bgColor: 'bg-orange-500/10',
    borderColor: 'border-orange-500/30',
    icon: <AlertTriangle className="w-5 h-5" />,
    description: '重要操作，请谨慎确认'
  },
  critical: { 
    label: '极高风险', 
    color: 'text-red-400',
    bgColor: 'bg-red-500/10',
    borderColor: 'border-red-500/50',
    icon: <Shield className="w-5 h-5" />,
    description: '危险操作，可能无法撤销'
  }
};

/**
 * 格式化参数
 */
function formatParams(params: Record<string, any>): { key: string; value: string; sensitive: boolean }[] {
  const sensitiveKeys = ['password', 'token', 'key', 'secret', 'credential', 'auth'];
  
  return Object.entries(params).map(([k, v]) => {
    const isSensitive = sensitiveKeys.some(sk => k.toLowerCase().includes(sk));
    let displayValue: string;
    
    if (isSensitive) {
      displayValue = '********';
    } else if (typeof v === 'object') {
      displayValue = JSON.stringify(v).slice(0, 50);
      if (JSON.stringify(v).length > 50) displayValue += '...';
    } else if (typeof v === 'string' && v.length > 50) {
      displayValue = v.slice(0, 50) + '...';
    } else {
      displayValue = String(v);
    }
    
    return { key: k, value: displayValue, sensitive: isSensitive };
  });
}

/**
 * 倒计时组件
 */
const Countdown: React.FC<{ 
  seconds: number; 
  onTimeout: () => void;
  className?: string;
}> = ({ seconds, onTimeout, className = '' }) => {
  const [remaining, setRemaining] = useState(seconds);
  
  useEffect(() => {
    if (remaining <= 0) {
      onTimeout();
      return;
    }
    
    const timer = setInterval(() => {
      setRemaining(prev => {
        if (prev <= 1) {
          clearInterval(timer);
          onTimeout();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    
    return () => clearInterval(timer);
  }, [remaining, onTimeout]);
  
  const percentage = (remaining / seconds) * 100;
  
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <Clock className="w-4 h-4 text-slate-400" />
      <span className={`text-sm font-mono ${remaining < 10 ? 'text-red-400' : 'text-slate-400'}`}>
        {remaining}s
      </span>
      <div className="w-16 h-1 bg-white/10 rounded-full overflow-hidden">
        <motion.div
          initial={{ width: '100%' }}
          animate={{ width: `${percentage}%` }}
          transition={{ duration: 1, ease: 'linear' }}
          className={`h-full rounded-full ${remaining < 10 ? 'bg-red-500' : 'bg-blue-500'}`}
        />
      </div>
    </div>
  );
};

/**
 * 用户确认组件
 */
export const UserConfirmation: React.FC<UserConfirmationProps> = ({
  step,
  tool,
  params,
  riskLevel,
  description,
  timeout,
  onConfirm,
  onReject,
  onTimeout,
  className = '',
  showDetails = true
}) => {
  const config = RISK_CONFIG[riskLevel];
  const [showParams, setShowParams] = useState(true);
  const [isConfirming, setIsConfirming] = useState(false);
  const [isRejecting, setIsRejecting] = useState(false);
  const formattedParams = formatParams(params);
  
  const handleConfirm = () => {
    setIsConfirming(true);
    setTimeout(() => {
      onConfirm();
      setIsConfirming(false);
    }, 300);
  };
  
  const handleReject = () => {
    setIsRejecting(true);
    setTimeout(() => {
      onReject();
      setIsRejecting(false);
    }, 300);
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className={`rounded-lg border ${config.borderColor} ${config.bgColor} overflow-hidden ${className}`}
    >
      {/* 头部 - 门下省封驳标识 */}
      <div className={`px-4 py-3 border-b ${config.borderColor} bg-gradient-to-r from-white/5 to-transparent`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Gavel className={`w-5 h-5 ${config.color}`} />
            <span className="text-sm font-medium text-white">操作确认</span>
            <span className={`text-xs px-2 py-0.5 rounded-full ${config.bgColor} ${config.color}`}>
              门下省封驳
            </span>
          </div>
          
          <div className="flex items-center gap-2">
            {/* 风险等级 */}
            <div className={`flex items-center gap-1 px-2 py-1 rounded ${config.bgColor}`}>
              {config.icon}
              <span className={`text-xs font-medium ${config.color}`}>{config.label}</span>
            </div>
            
            {/* 倒计时 */}
            {timeout && timeout > 0 && (
              <Countdown 
                seconds={timeout} 
                onTimeout={() => onTimeout?.()} 
              />
            )}
          </div>
        </div>
        
        {/* 风险描述 */}
        <p className={`text-xs mt-2 ${config.color}`}>
          {config.description}
        </p>
      </div>
      
      {/* 内容区 */}
      <div className="p-4 space-y-3">
        {/* 操作步骤 */}
        <div className="flex items-start gap-2">
          <FileText className="w-4 h-4 text-slate-400 mt-0.5" />
          <div>
            <span className="text-xs text-slate-500">即将执行</span>
            <p className="text-sm text-white font-medium">{step}</p>
          </div>
        </div>
        
        {/* 工具信息 */}
        <div className="flex items-start gap-2">
          <Shield className="w-4 h-4 text-slate-400 mt-0.5" />
          <div className="flex-1">
            <span className="text-xs text-slate-500">调用工具</span>
            <p className="text-sm text-white font-mono">{tool}</p>
          </div>
        </div>
        
        {/* 详细描述 */}
        {description && (
          <div className="p-2 rounded bg-black/20">
            <p className="text-xs text-slate-400">{description}</p>
          </div>
        )}
        
        {/* 参数详情 */}
        {showDetails && formattedParams.length > 0 && (
          <div className="mt-3">
            <button
              onClick={() => setShowParams(!showParams)}
              className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 mb-2"
            >
              {showParams ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
              {showParams ? '隐藏参数' : '查看参数'} ({formattedParams.length})
            </button>
            
            <AnimatePresence>
              {showParams && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="space-y-1"
                >
                  {formattedParams.map(({ key, value, sensitive }) => (
                    <div 
                      key={key}
                      className="flex items-center gap-2 text-xs p-1.5 rounded bg-black/20"
                    >
                      <span className="text-slate-500 font-mono">{key}:</span>
                      <span className={`font-mono truncate ${sensitive ? 'text-amber-400' : 'text-slate-300'}`}>
                        {value}
                      </span>
                      {sensitive && (
                        <span className="text-[10px] px-1 py-0.5 rounded bg-amber-500/20 text-amber-400 ml-auto">
                          敏感
                        </span>
                      )}
                    </div>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
      </div>
      
      {/* 按钮区 */}
      <div className="px-4 py-3 border-t border-white/5 bg-black/20 flex items-center justify-end gap-3">
        <button
          onClick={handleReject}
          disabled={isConfirming || isRejecting}
          className="px-4 py-2 rounded-lg text-sm font-medium text-slate-300 
                     bg-white/5 hover:bg-white/10 border border-white/10
                     disabled:opacity-50 disabled:cursor-not-allowed
                     transition-all flex items-center gap-2"
        >
          {isRejecting ? (
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
            >
              <XCircle className="w-4 h-4" />
            </motion.div>
          ) : (
            <X className="w-4 h-4" />
          )}
          拒绝
        </button>
        
        <button
          onClick={handleConfirm}
          disabled={isConfirming || isRejecting}
          className={`px-4 py-2 rounded-lg text-sm font-medium text-white 
                     ${riskLevel === 'critical' ? 'bg-red-500 hover:bg-red-600' : 
                       riskLevel === 'high' ? 'bg-orange-500 hover:bg-orange-600' :
                       'bg-emerald-500 hover:bg-emerald-600'}
                     disabled:opacity-50 disabled:cursor-not-allowed
                     transition-all flex items-center gap-2`}
        >
          {isConfirming ? (
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
            >
              <CheckCircle2 className="w-4 h-4" />
            </motion.div>
          ) : (
            <CheckCircle2 className="w-4 h-4" />
          )}
          确认执行
        </button>
      </div>
    </motion.div>
  );
};

/**
 * 用户确认队列组件 - 管理多个确认请求
 */
export const UserConfirmationQueue: React.FC<{
  confirmations: Array<UserConfirmationProps & { id: string }>;
  className?: string;
}> = ({ confirmations, className = '' }) => {
  if (confirmations.length === 0) return null;
  
  const current = confirmations[0];
  
  return (
    <div className={`relative ${className}`}>
      {/* 待处理数量徽章 */}
      {confirmations.length > 1 && (
        <div className="absolute -top-2 -right-2 z-10">
          <span className="px-2 py-0.5 rounded-full bg-amber-500 text-white text-xs font-medium">
            +{confirmations.length - 1}
          </span>
        </div>
      )}
      
      <UserConfirmation {...current} />
    </div>
  );
};

/**
 * 使用用户确认的Hook
 */
export function useUserConfirmation() {
  type ConfirmationItem = Omit<UserConfirmationProps, 'onConfirm' | 'onReject' | 'onTimeout'> & { 
    id: string; 
    resolve: (value: boolean) => void 
  };
  const [confirmations, setConfirmations] = useState<ConfirmationItem[]>([]);
  
  const requestConfirmation = React.useCallback((props: Omit<UserConfirmationProps, 'onConfirm' | 'onReject' | 'onTimeout'>): Promise<boolean> => {
    return new Promise((resolve) => {
      const id = `confirm_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      const newItem: ConfirmationItem = { ...props, id, resolve };
      setConfirmations(prev => [...prev, newItem]);
    });
  }, []);
  
  const confirm = React.useCallback((id: string) => {
    setConfirmations(prev => {
      const confirmation = prev.find(c => c.id === id);
      if (confirmation) {
        confirmation.resolve(true);
      }
      return prev.filter(c => c.id !== id);
    });
  }, []);
  
  const reject = React.useCallback((id: string) => {
    setConfirmations(prev => {
      const confirmation = prev.find(c => c.id === id);
      if (confirmation) {
        confirmation.resolve(false);
      }
      return prev.filter(c => c.id !== id);
    });
  }, []);
  
  const timeout = React.useCallback((id: string) => {
    setConfirmations(prev => {
      const confirmation = prev.find(c => c.id === id);
      if (confirmation) {
        confirmation.resolve(false);
      }
      return prev.filter(c => c.id !== id);
    });
  }, []);
  
  const clearAll = React.useCallback(() => {
    confirmations.forEach(c => c.resolve(false));
    setConfirmations([]);
  }, [confirmations]);
  
  return {
    confirmations: confirmations.map(({ id, step, tool, params, riskLevel, description, timeout: timeoutValue }) => ({
      id, step, tool, params, riskLevel, description, timeout: timeoutValue,
      onConfirm: () => confirm(id),
      onReject: () => reject(id),
      onTimeout: () => timeout(id)
    })),
    requestConfirmation,
    confirm,
    reject,
    timeout,
    clearAll,
    hasPending: confirmations.length > 0,
    count: confirmations.length
  };
}

export default UserConfirmation;
