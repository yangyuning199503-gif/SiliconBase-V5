/**
 * MemoryCard - 记忆卡片组件
 * Phase 5 Week 9 - 用户体验优化
 * 
 * 功能：
 * - 单条记忆的展示，支持展开/收起
 * - 标记记忆为重要
 * - 删除记忆
 * - 搜索关键词高亮
 */
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain, Clock, Star, Trash2, ChevronDown, ChevronUp,
  MessageSquare, Lightbulb, Heart, Wrench, BookOpen,
  Sparkles, Pin, PinOff, Loader2
} from 'lucide-react';
import { Memory } from '../../utils/api/memory';
import HighlightText from '../HighlightText';

interface MemoryCardProps {
  memory: Memory;
  onDelete?: (id: string) => void;
  onToggleImportant?: (id: string, important: boolean) => void;
  isImportant?: boolean;
  isDeleting?: boolean;
  highlightText?: string; // 需要高亮的文本
  compact?: boolean; // 紧凑模式（用于侧边栏）
  isHighlighted?: boolean; // 是否被外部高亮（如 MemoryAwareness 点击）
}

// 记忆类型配置
const MEMORY_TYPE_CONFIG: Record<string, { icon: React.ReactNode; label: string; color: string; bgColor: string }> = {
  internal_thought: {
    icon: <Brain className="w-3.5 h-3.5" />,
    label: 'AI思考',
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/10'
  },
  thinking_flow: {
    icon: <Sparkles className="w-3.5 h-3.5" />,
    label: '思维流',
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/10'
  },
  tool_execution: {
    icon: <Wrench className="w-3.5 h-3.5" />,
    label: '工具执行',
    color: 'text-orange-400',
    bgColor: 'bg-orange-500/10'
  },
  experience: {
    icon: <BookOpen className="w-3.5 h-3.5" />,
    label: '经验',
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10'
  },
  user_preference: {
    icon: <Heart className="w-3.5 h-3.5" />,
    label: '用户偏好',
    color: 'text-pink-400',
    bgColor: 'bg-pink-500/10'
  },
  optimization: {
    icon: <Lightbulb className="w-3.5 h-3.5" />,
    label: '优化',
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-500/10'
  },
  chat: {
    icon: <MessageSquare className="w-3.5 h-3.5" />,
    label: '对话',
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10'
  },
  default: {
    icon: <Brain className="w-3.5 h-3.5" />,
    label: '记忆',
    color: 'text-slate-400',
    bgColor: 'bg-slate-500/10'
  }
};

// 层级颜色
const LAYER_COLORS: Record<string, string> = {
  short: 'bg-cyan-500',
  medium: 'bg-green-400',
  long: 'bg-purple-400',
  evolve: 'bg-pink-400',
  vector: 'bg-blue-400',
  execution: 'bg-orange-400'
};

// 格式化时间
function formatTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return '刚刚';
  if (diffMins < 60) return `${diffMins}分钟前`;
  if (diffHours < 24) return `${diffHours}小时前`;
  if (diffDays < 7) return `${diffDays}天前`;
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

// 获取内容摘要
function getContentSummary(content: string, maxLength: number = 60): string {
  if (!content) return '';
  const text = typeof content === 'string' ? content : JSON.stringify(content);
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength) + '...';
}

export default function MemoryCard({
  memory,
  onDelete,
  onToggleImportant,
  isImportant = false,
  isDeleting = false,
  highlightText = '',
  compact = false,
  isHighlighted = false
}: MemoryCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [isHovered, setIsHovered] = useState(false);

  const typeConfig = MEMORY_TYPE_CONFIG[memory.mem_type] || MEMORY_TYPE_CONFIG.default;
  const layerColor = LAYER_COLORS[memory.layer] || LAYER_COLORS.short;

  const content = typeof memory.content === 'string' ? memory.content : JSON.stringify(memory.content);
  const hasLongContent = content.length > 100;
  const scene = typeof memory.scene === 'string' ? memory.scene : JSON.stringify(memory.scene || '');

  // 紧凑模式（侧边栏用）
  if (compact) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: isDeleting ? 0.5 : 1, y: 0 }}
        className="group relative"
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        <div className={`
          relative p-3 rounded-xl border transition-all duration-200
          ${isImportant 
            ? 'bg-amber-500/5 border-amber-500/30' 
            : 'bg-sb-bg-secondary/50 border-white/5 hover:border-white/15'
          }
          ${isDeleting ? 'pointer-events-none' : ''}
          ${isHighlighted ? 'ring-2 ring-sb-cyan shadow-[0_0_12px_rgba(34,211,238,0.3)]' : ''}
        `}>
          {/* 重要标记指示器 */}
          {isImportant && (
            <div className="absolute -top-1 -right-1">
              <Star className="w-4 h-4 text-amber-400 fill-amber-400" />
            </div>
          )}

          {/* 头部：类型和时间 */}
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <div className={`w-1.5 h-1.5 rounded-full ${layerColor}`} />
              <span className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] ${typeConfig.bgColor} ${typeConfig.color}`}>
                {typeConfig.icon}
                {typeConfig.label}
              </span>
            </div>
            <span className="text-[10px] text-slate-500 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {formatTime(memory.created_at)}
            </span>
          </div>

          {/* 内容摘要 - 支持高亮 */}
          <p className="text-xs text-white/80 leading-relaxed line-clamp-2">
            {highlightText ? (
              <HighlightText 
                text={getContentSummary(content, 80)} 
                keywords={highlightText}
                highlightClassName="bg-yellow-500/40 text-yellow-100 px-0.5 rounded"
              />
            ) : (
              getContentSummary(content, 80)
            )}
          </p>

          {/* 场景 - 支持高亮 */}
          {scene && (
            <p className="text-[10px] text-slate-500 truncate max-w-[100%] mt-1">
              {highlightText ? (
                <HighlightText 
                  text={scene} 
                  keywords={highlightText}
                  highlightClassName="bg-yellow-500/40 text-yellow-100 px-0.5 rounded"
                />
              ) : (
                scene
              )}
            </p>
          )}

          {/* 评分 */}
          <div className="flex items-center justify-between mt-2">
            <div className="flex items-center gap-1">
              <Star className="w-3 h-3 text-yellow-400" />
              <span className="text-[10px] text-slate-400">{memory.rating ?? 0}</span>
            </div>
            
            {/* 删除中状态 */}
            {isDeleting && (
              <span className="flex items-center gap-1 text-[10px] text-red-400">
                <Loader2 className="w-3 h-3 animate-spin" />
                删除中...
              </span>
            )}
          </div>

          {/* 悬停操作按钮 */}
          <AnimatePresence>
            {isHovered && !isDeleting && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="absolute top-2 right-2 flex items-center gap-1"
              >
                {onToggleImportant && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onToggleImportant(memory.id, !isImportant);
                    }}
                    disabled={isDeleting}
                    className={`
                      p-1.5 rounded-lg transition-colors
                      ${isImportant 
                        ? 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30' 
                        : 'bg-white/10 text-slate-400 hover:bg-white/20 hover:text-amber-400'
                      }
                    `}
                    title={isImportant ? '取消标记' : '标记重要'}
                  >
                    {isImportant ? <PinOff className="w-3 h-3" /> : <Pin className="w-3 h-3" />}
                  </button>
                )}
                {onDelete && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(memory.id);
                    }}
                    disabled={isDeleting}
                    className="p-1.5 rounded-lg bg-white/10 text-slate-400 hover:bg-red-500/20 hover:text-red-400 transition-colors"
                    title="删除"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </motion.div>
    );
  }

  // 完整模式
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: isDeleting ? 0.5 : 1, y: 0 }}
      className="group"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className={`
        relative p-4 rounded-xl border transition-all duration-200
        ${isImportant 
          ? 'bg-amber-500/5 border-amber-500/30 shadow-lg shadow-amber-500/5' 
          : 'bg-sb-bg-secondary/50 border-white/5 hover:border-white/15 hover:bg-sb-bg-secondary'
        }
        ${isDeleting ? 'pointer-events-none' : ''}
        ${isHighlighted ? 'ring-2 ring-sb-cyan shadow-[0_0_12px_rgba(34,211,238,0.3)]' : ''}
      `}>
        {/* 重要标记 */}
        {isImportant && (
          <div className="absolute -top-2 -right-2">
            <div className="bg-amber-500/20 p-1.5 rounded-full border border-amber-500/30">
              <Star className="w-3.5 h-3.5 text-amber-400 fill-amber-400" />
            </div>
          </div>
        )}

        {/* 头部信息 */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            {/* 层级指示器 */}
            <div className="flex items-center gap-1.5">
              <div className={`w-2 h-2 rounded-full ${layerColor}`} />
              <span className="text-[10px] uppercase text-slate-500">{memory.layer}</span>
            </div>
            
            {/* 类型标签 */}
            <span className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs ${typeConfig.bgColor} ${typeConfig.color}`}>
              {typeConfig.icon}
              {typeConfig.label}
            </span>

            {/* 来源标记 */}
            {memory.source && (
              <span className="text-[10px] text-slate-500">
                {memory.source === 'auto_save' && '🤖 自动'}
                {memory.source === 'user' && '👤 手动'}
                {memory.source === 'reflection' && '💭 反思'}
                {memory.source === 'evolution' && '✨ 进化'}
                {memory.source === 'ai' && '🧠 AI'}
              </span>
            )}
          </div>

          {/* 时间和操作 */}
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-500 flex items-center gap-1">
              <Clock className="w-3.5 h-3.5" />
              {formatTime(memory.created_at)}
            </span>
            
            {/* 删除中状态 */}
            {isDeleting && (
              <span className="flex items-center gap-1 text-xs text-red-400">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                删除中...
              </span>
            )}
            
            {/* 操作按钮 */}
            <div className={`
              flex items-center gap-1 transition-opacity duration-200
              ${isHovered && !isDeleting ? 'opacity-100' : 'opacity-0'}
            `}>
              {onToggleImportant && (
                <button
                  onClick={() => onToggleImportant(memory.id, !isImportant)}
                  disabled={isDeleting}
                  className={`
                    p-2 rounded-lg transition-colors
                    ${isImportant 
                      ? 'bg-amber-500/20 text-amber-400' 
                      : 'hover:bg-white/10 text-slate-400 hover:text-amber-400'
                    }
                  `}
                  title={isImportant ? '取消标记' : '标记重要'}
                >
                  {isImportant ? <PinOff className="w-4 h-4" /> : <Pin className="w-4 h-4" />}
                </button>
              )}
              {onDelete && (
                <button
                  onClick={() => onDelete(memory.id)}
                  disabled={isDeleting}
                  className="p-2 rounded-lg hover:bg-red-500/20 text-slate-400 hover:text-red-400 transition-colors"
                  title="删除"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>
        </div>

        {/* 内容区域 */}
        <div className="space-y-2">
          <div 
            className={`
              text-sm text-white/90 leading-relaxed
              ${expanded ? '' : 'line-clamp-3'}
            `}
          >
            {highlightText ? (
              <HighlightText 
                text={content} 
                keywords={highlightText}
                highlightClassName="bg-yellow-500/40 text-yellow-100 px-0.5 rounded"
              />
            ) : (
              content
            )}
          </div>
          
          {/* 展开/收起按钮 */}
          {hasLongContent && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-xs text-sb-cyan hover:text-sb-cyan-hover transition-colors"
            >
              {expanded ? (
                <>
                  <ChevronUp className="w-4 h-4" />
                  收起
                </>
              ) : (
                <>
                  <ChevronDown className="w-4 h-4" />
                  展开
                </>
              )}
            </button>
          )}
        </div>

        {/* 场景 - 支持高亮 */}
        {scene && (
          <div className="mt-3 pt-3 border-t border-white/5">
            <span className="text-xs text-slate-500">
              场景: {highlightText ? (
                <HighlightText 
                  text={scene} 
                  keywords={highlightText}
                  highlightClassName="bg-yellow-500/40 text-yellow-100 px-0.5 rounded"
                />
              ) : (
                scene
              )}
            </span>
          </div>
        )}

        {/* 底部信息 */}
        <div className="flex items-center justify-between mt-3 pt-3 border-t border-white/5">
          <div className="flex items-center gap-4">
            {/* 评分 */}
            <div className="flex items-center gap-1">
              {[1, 2, 3, 4, 5].map((star) => (
                <Star
                  key={star}
                  className={`w-3.5 h-3.5 ${
                    star <= (memory.rating ?? 0) 
                      ? 'text-yellow-400 fill-yellow-400' 
                      : 'text-slate-600'
                  }`}
                />
              ))}
              <span className="text-xs text-slate-400 ml-1">{memory.rating ?? 0}/5</span>
            </div>
          </div>

          {/* ID（可选显示） */}
          <span className="text-[10px] text-slate-600 font-mono">
            #{memory.id?.slice(0, 8)}
          </span>
        </div>
      </div>
    </motion.div>
  );
}
