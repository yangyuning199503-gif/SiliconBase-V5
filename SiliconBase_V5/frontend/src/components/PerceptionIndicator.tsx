import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Eye, 
  Monitor, 
  Cpu, 
  History,
  ChevronDown,
  ChevronUp,
  X
} from 'lucide-react';
import { usePerception, PerceptionData } from '../hooks/usePerception';

/**
 * PerceptionIndicator 组件 Props
 */
export interface PerceptionIndicatorProps {
  /** 是否强制显示（覆盖Hook状态，用于测试） */
  forceShow?: boolean;
  /** 强制显示时的感知数据 */
  forceData?: PerceptionData;
  /** 强制显示时的触发原因 */
  forceReason?: string;
  /** 位置：左上/右上/左下/右下 */
  position?: 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right';
  /** 自定义类名 */
  className?: string;
}

/**
 * 眼睛眨眼动画组件
 */
const BlinkingEye: React.FC<{ isActive: boolean }> = ({ isActive }) => {
  const [isBlinking, setIsBlinking] = useState(false);

  useEffect(() => {
    if (!isActive) return;

    // 随机眨眼动画
    const blinkInterval = setInterval(() => {
      setIsBlinking(true);
      setTimeout(() => setIsBlinking(false), 150);
    }, 2000 + Math.random() * 1000);

    return () => clearInterval(blinkInterval);
  }, [isActive]);

  return (
    <motion.div
      animate={{
        scaleY: isBlinking ? 0.1 : 1,
        scale: isActive ? [1, 1.1, 1] : 1,
      }}
      transition={{
        scaleY: { duration: 0.15, ease: 'easeInOut' },
        scale: { duration: 2, repeat: Infinity, ease: 'easeInOut' },
      }}
      className="relative"
    >
      <Eye className="w-5 h-5 text-sb-cyan" />
      {/* 视线扫描效果 */}
      {isActive && (
        <motion.div
          className="absolute inset-0 rounded-full bg-sb-cyan/20"
          animate={{
            scale: [1, 1.5, 1],
            opacity: [0.5, 0, 0.5],
          }}
          transition={{
            duration: 2,
            repeat: Infinity,
            ease: 'easeInOut',
          }}
        />
      )}
    </motion.div>
  );
};

/**
 * PerceptionIndicator 组件
 * 
 * 显示AI感知状态的悬浮指示器，包含：
 * - 眨眼动画的眼睛图标
 * - 触发原因
 * - 可展开的感知数据摘要
 * 
 * 特性：
 * - 3秒后自动隐藏
 * - 支持深色/浅色主题
 * - 流畅的动画效果
 * - 轻量级，不阻塞主界面
 */
export const PerceptionIndicator: React.FC<PerceptionIndicatorProps> = ({
  forceShow,
  forceData,
  forceReason,
  position = 'top-right',
  className = '',
}) => {
  const { 
    isActive: hookIsActive, 
    perceptionData: hookData, 
    triggerReason: hookReason,
    isExpanded,
    setIsExpanded,
    close,
  } = usePerception();

  // 使用强制值或Hook值
  const isActive = forceShow ?? hookIsActive;
  const perceptionData = forceData ?? hookData;
  const triggerReason = forceReason ?? hookReason;

  // 位置样式
  const positionStyles = {
    'top-left': 'top-20 left-4',
    'top-right': 'top-20 right-4',
    'bottom-left': 'bottom-20 left-4',
    'bottom-right': 'bottom-20 right-4',
  };

  // 如果没有数据且不强制显示，不渲染
  if (!isActive && !forceShow) return null;

  return (
    <AnimatePresence mode="wait">
      {isActive && (
        <motion.div
          initial={{ opacity: 0, y: -20, scale: 0.9 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -20, scale: 0.9 }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
          className={`fixed ${positionStyles[position]} z-50 ${className}`}
        >
          <div className={`
            relative overflow-hidden
            bg-slate-900/90 dark:bg-slate-900/90
            backdrop-blur-xl
            border border-white/10 dark:border-white/10
            rounded-xl shadow-2xl
            min-w-[240px] max-w-[320px]
            transition-all duration-300
            ${isExpanded ? 'bg-slate-900/95' : ''}
          `}>
            {/* 背景装饰 */}
            <div className="absolute inset-0 pointer-events-none overflow-hidden">
              <div className="absolute -top-10 -right-10 w-20 h-20 bg-sb-cyan/5 rounded-full blur-2xl" />
              <div className="absolute -bottom-10 -left-10 w-16 h-16 bg-sb-accent-secondary/5 rounded-full blur-2xl" />
            </div>

            {/* 头部：图标 + 触发原因 + 操作按钮 */}
            <div className="relative px-3 py-2.5 flex items-center gap-3">
              {/* 眨眼眼睛图标 */}
              <div className="flex-shrink-0">
                <BlinkingEye isActive={isActive} />
              </div>

              {/* 触发原因 */}
              <div className="flex-1 min-w-0">
                <p className="text-xs text-white/80 font-medium truncate">
                  {triggerReason || 'AI正在观察...'}
                </p>
              </div>

              {/* 展开/收起按钮 */}
              {perceptionData && (
                <button
                  onClick={() => setIsExpanded(!isExpanded)}
                  className="p-1 rounded hover:bg-white/10 text-slate-400 hover:text-white transition-colors"
                  title={isExpanded ? '收起' : '展开'}
                >
                  {isExpanded ? (
                    <ChevronUp className="w-3.5 h-3.5" />
                  ) : (
                    <ChevronDown className="w-3.5 h-3.5" />
                  )}
                </button>
              )}

              {/* 关闭按钮 */}
              <button
                onClick={close}
                className="p-1 rounded hover:bg-white/10 text-slate-400 hover:text-white transition-colors"
                title="关闭"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* 展开的详情区域 */}
            <AnimatePresence>
              {isExpanded && perceptionData && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.3, ease: 'easeInOut' }}
                  className="overflow-hidden"
                >
                  <div className="border-t border-white/5 px-3 py-3 space-y-4">
                    {/* 感知类型 */}
                    <div className="flex items-start gap-2">
                      <Monitor className="w-3.5 h-3.5 text-sb-cyan mt-0.5 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <span className="text-[10px] text-slate-400 uppercase tracking-wider block mb-0.5">
                          感知类型
                        </span>
                        <span className="text-[11px] text-slate-200 line-clamp-1">
                          {perceptionData.type || 'Unknown'}
                        </span>
                      </div>
                    </div>

                    {/* 置信度 */}
                    <div className="flex items-start gap-2">
                      <Cpu className="w-3.5 h-3.5 text-sb-cyan mt-0.5 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <span className="text-[10px] text-slate-400 uppercase tracking-wider block mb-0.5">
                          置信度
                        </span>
                        <span className="text-[11px] text-slate-200 line-clamp-1">
                          {typeof perceptionData.confidence === 'number'
                            ? `${(perceptionData.confidence * 100).toFixed(1)}%`
                            : 'Unknown'}
                        </span>
                      </div>
                    </div>

                    {/* 内容预览 */}
                    {perceptionData.content_preview && (
                      <div className="flex items-start gap-2">
                        <History className="w-3.5 h-3.5 text-sb-cyan mt-0.5 flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <span className="text-[10px] text-slate-400 uppercase tracking-wider block mb-0.5">
                            内容预览
                          </span>
                          <span className="text-[11px] text-slate-200 line-clamp-2">
                            {perceptionData.content_preview}
                          </span>
                        </div>
                      </div>
                    )}

                    {/* 【P0修复】检测到的 UI 元素 */}
                    {perceptionData.metadata?.element_map && perceptionData.metadata.element_map.length > 0 && (
                      <div className="flex items-start gap-2">
                        <Eye className="w-3.5 h-3.5 text-sb-cyan mt-0.5 flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <span className="text-[10px] text-slate-400 uppercase tracking-wider block mb-1">
                            检测到 {perceptionData.metadata.element_map.length} 个元素
                          </span>
                          <div className="space-y-1">
                            {perceptionData.metadata.element_map.slice(0, 3).map((el: any, idx: number) => (
                              <div key={idx} className="flex items-center gap-1.5">
                                <span className="text-[11px] text-slate-300 truncate">
                                  {el.name || el.text || '未命名'}
                                </span>
                                <span className="px-1 py-0.5 rounded bg-white/5 text-slate-500 text-[9px] flex-shrink-0">
                                  {el.type}
                                </span>
                              </div>
                            ))}
                            {perceptionData.metadata.element_map.length > 3 && (
                              <span className="text-[10px] text-slate-500">
                                +{perceptionData.metadata.element_map.length - 3} 更多
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* 底部进度条（自动隐藏倒计时视觉提示） */}
            {!isExpanded && (
              <motion.div
                className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-sb-cyan/50 to-transparent"
                initial={{ opacity: 0 }}
                animate={{ opacity: [0.3, 0.8, 0.3] }}
                transition={{ duration: 2, repeat: Infinity }}
              />
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

/**
 * 简化的感知徽章组件（用于嵌入其他UI）
 */
export const PerceptionBadge: React.FC = () => {
  const { isActive, triggerReason } = usePerception();

  if (!isActive) return null;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.8 }}
      className="inline-flex items-center gap-1.5 px-2 py-1 
                 bg-slate-900/80 dark:bg-slate-900/80
                 backdrop-blur-sm
                 border border-sb-cyan/30 
                 rounded-full text-[10px] text-sb-cyan"
    >
      <motion.div
        animate={{ scale: [1, 1.2, 1] }}
        transition={{ duration: 1.5, repeat: Infinity }}
      >
        <Eye className="w-3 h-3" />
      </motion.div>
      <span className="truncate max-w-[120px]">{triggerReason}</span>
    </motion.div>
  );
};

export default PerceptionIndicator;
