/**
 * MemoryAwareness - 记忆感知提示组件
 * 在AI回复下方显示，提示用户AI基于多少条记忆回复
 */
import { useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain, Sparkles, ChevronRight, Clock, Target,
  Lightbulb, MessageSquare, BookOpen
} from 'lucide-react';

interface MemoryAwarenessProps {
  memoryCount: number;
  memoryIds?: string[] | null;
  onClick?: () => void;
  relevanceScore?: number; // 关联度分数 0-1
  memoryTypes?: string[] | null; // 使用的记忆类型
  className?: string;
}

// 记忆类型图标映射
const TYPE_ICONS: Record<string, React.ReactNode> = {
  context: <BookOpen className="w-3 h-3" />,
  reference: <Target className="w-3 h-3" />,
  experience: <Lightbulb className="w-3 h-3" />,
  preference: <MessageSquare className="w-3 h-3" />,
  default: <Brain className="w-3 h-3" />
};

// 获取友好描述
function getMemoryDescription(count: number): string {
  if (count === 0) return '基于当前上下文';
  if (count === 1) return '基于1条相关记忆';
  if (count <= 3) return `基于${count}条相关记忆`;
  if (count <= 10) return `基于${count}条记忆综合回复`;
  return `基于${count}条深度记忆`;
}

// 获取关联度描述
function getRelevanceDescription(score: number): { text: string; color: string } {
  if (score >= 0.8) return { text: '高度相关', color: 'text-emerald-400' };
  if (score >= 0.6) return { text: '比较相关', color: 'text-cyan-400' };
  if (score >= 0.4) return { text: '部分相关', color: 'text-yellow-400' };
  return { text: '弱相关', color: 'text-slate-400' };
}

export default function MemoryAwareness({
  memoryCount,
  memoryIds: _memoryIds = [],
  onClick,
  relevanceScore = 0,
  memoryTypes = [],
  className = ''
}: MemoryAwarenessProps) {
  const [showTooltip, setShowTooltip] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const hasMemories = memoryCount > 0;
  const relevanceDesc = getRelevanceDescription(relevanceScore);

  // 如果没有记忆且不显示零状态，返回null
  if (!hasMemories && !showTooltip) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className={`inline-flex items-center gap-1.5 text-xs text-slate-500 ${className}`}
      >
        <Brain className="w-3.5 h-3.5" />
        <span>基于当前上下文理解</span>
      </motion.div>
    );
  }

  return (
    <div className={`relative inline-block ${className}`}>
      {/* 主按钮 */}
      <motion.button
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
        onClick={onClick}
        onMouseEnter={() => {
          setIsHovered(true);
          if (hasMemories) {
            setShowTooltip(true);
          }
        }}
        onMouseLeave={() => {
          setIsHovered(false);
          setShowTooltip(false);
        }}
        className={`
          inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs
          transition-all duration-200 group
          ${hasMemories
            ? 'bg-gradient-to-r from-purple-500/10 to-cyan-500/10 text-slate-300 border border-purple-500/20 hover:border-purple-500/40 hover:from-purple-500/20 hover:to-cyan-500/20'
            : 'bg-slate-800/50 text-slate-500 border border-slate-700/50'
          }
        `}
      >
        {/* 图标动画 */}
        <motion.div
          animate={isHovered ? { 
            rotate: [0, -10, 10, 0],
            scale: [1, 1.1, 1]
          } : {}}
          transition={{ duration: 0.5 }}
        >
          {hasMemories ? (
            <Sparkles className="w-3.5 h-3.5 text-purple-400 group-hover:text-cyan-400 transition-colors" />
          ) : (
            <Brain className="w-3.5 h-3.5" />
          )}
        </motion.div>

        {/* 文字 */}
        <span className="font-medium">
          {getMemoryDescription(memoryCount)}
        </span>

        {/* 关联度指示器 */}
        {hasMemories && relevanceScore > 0 && (
          <span className={`text-[10px] ${relevanceDesc.color}`}>
            {relevanceDesc.text}
          </span>
        )}

        {/* 箭头 */}
        {hasMemories && (
          <ChevronRight className="w-3 h-3 opacity-0 -ml-1 group-hover:opacity-100 group-hover:ml-0 transition-all" />
        )}
      </motion.button>

      {/* 悬停提示框 */}
      <AnimatePresence>
        {showTooltip && hasMemories && (
          <motion.div
            ref={tooltipRef}
            initial={{ opacity: 0, y: 10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.95 }}
            transition={{ duration: 0.15 }}
            className="absolute left-0 bottom-full mb-2 z-50"
          >
            <div className="w-72 p-4 rounded-xl bg-sb-bg-secondary border border-white/10 shadow-2xl">
              {/* 头部 */}
              <div className="flex items-center gap-2 mb-3">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-cyan-500 flex items-center justify-center">
                  <Brain className="w-4 h-4 text-white" />
                </div>
                <div>
                  <h4 className="text-sm font-medium text-white">记忆摘要</h4>
                  <p className="text-[10px] text-slate-400">
                    AI使用了 {memoryCount} 条记忆
                  </p>
                </div>
              </div>

              {/* 关联度进度条 */}
              {relevanceScore > 0 && (
                <div className="mb-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] text-slate-400">关联度</span>
                    <span className={`text-[10px] ${relevanceDesc.color}`}>
                      {(relevanceScore * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${relevanceScore * 100}%` }}
                      transition={{ duration: 0.5, delay: 0.1 }}
                      className={`h-full rounded-full ${
                        relevanceScore >= 0.8 ? 'bg-emerald-400' :
                        relevanceScore >= 0.6 ? 'bg-cyan-400' :
                        relevanceScore >= 0.4 ? 'bg-yellow-400' :
                        'bg-slate-400'
                      }`}
                    />
                  </div>
                </div>
              )}

              {/* 记忆类型分布 */}
              {memoryTypes && memoryTypes.length > 0 && (
                <div className="mb-3">
                  <span className="text-[10px] text-slate-400 block mb-2">记忆类型</span>
                  <div className="flex flex-wrap gap-1.5">
                    {Array.from(new Set(memoryTypes)).map((type) => {
                      const count = memoryTypes.filter(t => t === type).length;
                      return (
                        <span
                          key={type}
                          className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-white/5 text-[10px] text-slate-300"
                        >
                          {TYPE_ICONS[type] || TYPE_ICONS.default}
                          {type}
                          {count > 1 && <span className="text-slate-500">x{count}</span>}
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* 提示文字 */}
              <div className="pt-2 border-t border-white/5">
                <p className="text-[10px] text-slate-500 flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  点击可查看完整记忆列表
                </p>
              </div>
            </div>

            {/* 小三角 */}
            <div className="absolute left-6 -bottom-1 w-2 h-2 bg-sb-bg-secondary border-r border-b border-white/10 rotate-45" />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// 简化的内联版本（用于消息流中）
export function MemoryAwarenessInline({
  memoryCount,
  onClick
}: {
  memoryCount: number;
  onClick?: () => void;
}) {
  if (memoryCount === 0) return null;

  return (
    <motion.button
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      onClick={onClick}
      className="inline-flex items-center gap-1 text-[10px] text-slate-500 hover:text-sb-cyan transition-colors"
    >
      <Sparkles className="w-3 h-3" />
      基于{memoryCount}条记忆
    </motion.button>
  );
}
