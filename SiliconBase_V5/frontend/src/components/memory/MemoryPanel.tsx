/**
 * MemoryPanel - 记忆面板组件
 * Phase 5 Week 9 - 用户体验优化
 * 
 * 功能：
 * - 侧边栏展示当前会话的记忆，按时间倒序排列
 * - 支持关键词搜索和高亮显示
 * - 记忆分类筛选（全部/重要/最近）
 * - 标记记忆为重要
 * - 删除不需要的记忆
 */
import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Brain, X, Clock, Filter, Sparkles, RefreshCw,
  ChevronDown, MemoryStick, Search, Pin, AlertCircle, WifiOff
} from 'lucide-react';
import { memoryAPI, Memory, SessionMemory } from '../../utils/api/memory';
import MemoryCard from './MemoryCard';
import { useNetworkStatus, APIErrorToast } from '../ErrorHandler';

interface MemoryPanelProps {
  sessionId: string;
  isOpen: boolean;
  onClose: () => void;
  highlightMemoryId?: string;
}

// 过滤选项
 type MemoryFilter = 'all' | 'important' | 'recent' | 'high_rated';

// 缓存类型
interface MemoryCache {
  memories: Memory[];
  timestamp: number;
  sessionId: string;
}

// 内存缓存（5分钟）
const memoryCache: Map<string, MemoryCache> = new Map();
const CACHE_DURATION = 5 * 60 * 1000; // 5分钟

export const clearMemoryCache = () => memoryCache.clear();

export default function MemoryPanel({ sessionId, isOpen, onClose, highlightMemoryId }: MemoryPanelProps) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [, setSessionMemories] = useState<SessionMemory[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<MemoryFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('');
  const [importantIds, setImportantIds] = useState<Set<string>>(new Set());
  const [showFilters, setShowFilters] = useState(false);
  const [totalRelevance, setTotalRelevance] = useState(0);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [highlightedId, setHighlightedId] = useState<string | null>(null);
  
  const networkStatus = useNetworkStatus();

  // 防抖搜索
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearchQuery(searchQuery);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // 外部高亮指定记忆（如 MemoryAwareness 点击）
  useEffect(() => {
    if (isOpen && highlightMemoryId) {
      setHighlightedId(highlightMemoryId);
      setFilter('all');
      setSearchQuery('');
    }
  }, [isOpen, highlightMemoryId]);

  // 获取会话记忆
  const fetchSessionMemories = useCallback(async (forceRefresh = false) => {
    if (!sessionId || !isOpen) return;

    // 离线检查
    if (!networkStatus.online) {
      setError('当前处于离线状态，无法获取记忆');
      return;
    }

    // 检查缓存
    const cached = memoryCache.get(sessionId);
    if (!forceRefresh && cached && Date.now() - cached.timestamp < CACHE_DURATION) {
      setMemories(cached.memories);
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const response = await memoryAPI.getSessionMemories(sessionId);
      
      // 【Fix】后端 /api/memories/by-session 直接返回 Memory[] 而非 SessionMemory[]
      // 兼容两种格式：直接 Memory 对象 或 带 memory 包裹层的 SessionMemory
      const memoryList = response.memories
        .map((sm: any) => {
          // 如果后端直接返回 Memory 对象（有 content 字段）
          if (sm.content !== undefined) {
            return sm as Memory;
          }
          // 否则按旧的 SessionMemory 格式解析
          return sm.memory || {
            id: sm.memory_id,
            layer: 'short',
            mem_type: sm.memory_type,
            content: '',
            scene: '',
            rating: 0,
            created_at: sm.created_at
          };
        })
        .filter((m: Memory | null) => m && m.id) as Memory[];

      // 按时间倒序排列
      const sortedMemories = memoryList.sort((a, b) => 
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      );

      setMemories(sortedMemories);
      setSessionMemories(response.memories);
      setTotalRelevance(response.total_relevance_score);

      // 更新缓存
      memoryCache.set(sessionId, {
        memories: sortedMemories,
        timestamp: Date.now(),
        sessionId
      });
    } catch (err) {
      console.error('[MemoryPanel] 获取记忆失败:', err);
      const errorMessage = err instanceof Error ? err.message : '获取记忆失败';
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [sessionId, isOpen, networkStatus.online]);

  // 监听会话ID变化和面板打开状态
  useEffect(() => {
    if (isOpen && sessionId) {
      fetchSessionMemories();
    }
  }, [isOpen, sessionId, fetchSessionMemories]);

  // 删除记忆
  const handleDelete = async (memoryId: string) => {
    if (!confirm('确定要删除这条记忆吗？此操作不可恢复。')) return;
    
    // 离线检查
    if (!networkStatus.online) {
      setError('当前处于离线状态，无法删除记忆');
      return;
    }
    
    setDeletingId(memoryId);
    try {
      await memoryAPI.deleteMemory(memoryId);
      setMemories(prev => prev.filter(m => m.id !== memoryId));
      // 清除缓存
      memoryCache.delete(sessionId);
      // 从重要列表中移除
      setImportantIds(prev => {
        const next = new Set(prev);
        next.delete(memoryId);
        return next;
      });
    } catch (err) {
      console.error('[MemoryPanel] 删除记忆失败:', err);
      setError('删除记忆失败');
    } finally {
      setDeletingId(null);
    }
  };

  // 标记重要
  const handleToggleImportant = async (memoryId: string, important: boolean) => {
    // 离线检查
    if (!networkStatus.online) {
      setError('当前处于离线状态，无法更新记忆');
      return;
    }

    try {
      // 调用API更新服务器端
      await memoryAPI.markMemoryImportant(memoryId, important);
      
      // 更新本地状态
      setImportantIds(prev => {
        const next = new Set(prev);
        if (important) {
          next.add(memoryId);
        } else {
          next.delete(memoryId);
        }
        return next;
      });
    } catch (err) {
      console.error('[MemoryPanel] 标记重要失败:', err);
      setError('标记重要失败');
    }
  };

  // 过滤记忆
  const filteredMemories = memories.filter(memory => {
    // 搜索过滤
    if (debouncedSearchQuery) {
      const content = typeof memory.content === 'string' ? memory.content : JSON.stringify(memory.content);
      const scene = typeof memory.scene === 'string' ? memory.scene : JSON.stringify(memory.scene || '');
      const query = debouncedSearchQuery.toLowerCase();
      
      if (!content.toLowerCase().includes(query) && !scene.toLowerCase().includes(query)) {
        return false;
      }
    }

    // 类型过滤
    switch (filter) {
      case 'important':
        return importantIds.has(memory.id);
      case 'recent': {
        const hours24 = 24 * 60 * 60 * 1000;
        return new Date().getTime() - new Date(memory.created_at).getTime() < hours24;
      }
      case 'high_rated':
        return (memory.rating ?? 0) >= 4;
      default:
        return true;
    }
  });

  // 获取统计信息
  const stats = {
    total: memories.length,
    important: importantIds.size,
    recent: memories.filter(m => {
      const hours24 = 24 * 60 * 60 * 1000;
      return new Date().getTime() - new Date(m.created_at).getTime() < hours24;
    }).length,
    highRated: memories.filter(m => (m.rating ?? 0) >= 4).length
  };

  // 清除搜索
  const handleClearSearch = () => {
    setSearchQuery('');
    setDebouncedSearchQuery('');
    setFilter('all');
  };

  // 重试加载
  const handleRetry = () => {
    fetchSessionMemories(true);
  };

  if (!isOpen) return null;

  return (
    <>
      {/* 遮罩层 */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        className="fixed inset-0 bg-black/40 backdrop-blur-sm z-40"
      />

      {/* 侧边栏面板 */}
      <motion.div
        initial={{ x: '100%' }}
        animate={{ x: 0 }}
        exit={{ x: '100%' }}
        transition={{ type: 'spring', damping: 25, stiffness: 200 }}
        className="fixed right-0 top-0 h-full w-96 bg-sb-bg-secondary border-l border-white/10 shadow-2xl z-50 flex flex-col"
      >
        {/* 头部 */}
        <div className="p-4 border-b border-white/10">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
                <Brain className="w-5 h-5 text-white" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white">会话记忆</h2>
                <p className="text-xs text-slate-400">
                  {stats.total} 条记忆
                  {totalRelevance > 0 && (
                    <span className="ml-2 text-sb-cyan">
                      关联度: {(totalRelevance * 100).toFixed(0)}%
                    </span>
                  )}
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              aria-label="关闭"
              className="p-2 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* 搜索框 */}
          <div className="relative mb-3">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索记忆内容..."
              className="w-full bg-sb-bg-primary border border-white/10 rounded-lg pl-10 pr-10 py-2 text-sm text-white placeholder-slate-500 focus:border-sb-cyan outline-none"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-0.5 rounded hover:bg-white/10 text-slate-500 hover:text-slate-300"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>

          {/* 过滤器和操作 */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowFilters(!showFilters)}
                className={`
                  flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs transition-colors
                  ${showFilters 
                    ? 'bg-sb-cyan/20 text-sb-cyan border border-sb-cyan/30' 
                    : 'bg-white/5 text-slate-400 hover:bg-white/10'
                  }
                `}
              >
                <Filter className="w-3.5 h-3.5" />
                筛选
                <ChevronDown className={`w-3 h-3 transition-transform ${showFilters ? 'rotate-180' : ''}`} />
              </button>
              
              <button
                onClick={() => fetchSessionMemories(true)}
                disabled={loading || !networkStatus.online}
                className="p-1.5 rounded-lg bg-white/5 text-slate-400 hover:bg-white/10 hover:text-sb-cyan transition-colors disabled:opacity-50"
                title="刷新"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>

            {/* 快捷统计标签 */}
            <div className="flex items-center gap-2">
              {stats.important > 0 && (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 text-[10px] border border-amber-500/20">
                  <Pin className="w-3 h-3" />
                  {stats.important}
                </span>
              )}
            </div>
          </div>

          {/* 过滤选项展开 */}
          <AnimatePresence>
            {showFilters && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden"
              >
                <div className="flex flex-wrap gap-2 pt-3">
                  {[
                    { key: 'all', label: '全部', count: stats.total, icon: MemoryStick },
                    { key: 'important', label: '重要', count: stats.important, icon: Pin },
                    { key: 'recent', label: '24小时内', count: stats.recent, icon: Clock },
                    { key: 'high_rated', label: '高评分', count: stats.highRated, icon: Sparkles }
                  ].map(({ key, label, count, icon: Icon }) => (
                    <button
                      key={key}
                      onClick={() => setFilter(key as MemoryFilter)}
                      className={`
                        flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs transition-all
                        ${filter === key
                          ? 'bg-sb-cyan/20 text-sb-cyan border border-sb-cyan/30'
                          : 'bg-white/5 text-slate-400 hover:bg-white/10 border border-transparent'
                        }
                      `}
                    >
                      <Icon className="w-3.5 h-3.5" />
                      {label}
                      <span className="ml-1 px-1.5 py-0.5 bg-white/10 rounded text-[10px]">
                        {count}
                      </span>
                    </button>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* 错误提示 */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="mx-4 mt-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg flex items-center gap-2 text-red-400 text-sm"
            >
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span className="flex-1 truncate">{error}</span>
              <button 
                onClick={handleRetry}
                className="p-1.5 rounded hover:bg-red-500/20 text-red-400 hover:text-red-300 shrink-0"
                title="重试"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
              <button 
                onClick={() => setError(null)}
                className="p-1.5 rounded hover:bg-red-500/20 text-red-400 hover:text-red-300 shrink-0"
                title="关闭"
              >
                <X className="w-4 h-4" />
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {/* 离线提示 */}
        <AnimatePresence>
          {!networkStatus.online && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="mx-4 mt-4 p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg flex items-center gap-2 text-amber-400 text-sm"
            >
              <WifiOff className="w-4 h-4 shrink-0" />
              <span>当前处于离线状态</span>
            </motion.div>
          )}
        </AnimatePresence>

        {/* 记忆列表 */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent">
          {loading && memories.length === 0 ? (
            // 加载状态
            <div className="flex flex-col items-center justify-center h-40 text-slate-500">
              <motion.div
                animate={{ rotate: 360 }}
                transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                className="w-8 h-8 border-2 border-sb-cyan border-t-transparent rounded-full mb-3"
              />
              <span className="text-sm">加载记忆中...</span>
            </div>
          ) : filteredMemories.length === 0 ? (
            // 空状态
            <div className="flex flex-col items-center justify-center h-40 text-slate-500">
              <Brain className="w-12 h-12 mb-3 opacity-30" />
              <span className="text-sm">
                {searchQuery || filter !== 'all' ? '没有找到匹配的记忆' : '暂无记忆'}
              </span>
              {(searchQuery || filter !== 'all') && (
                <button
                  onClick={handleClearSearch}
                  className="mt-2 text-xs text-sb-cyan hover:underline"
                >
                  清除筛选条件
                </button>
              )}
            </div>
          ) : (
            // 记忆卡片列表
            <>
              {filteredMemories.map((memory, index) => (
                <motion.div
                  key={memory.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                >
                  <MemoryCard
                    memory={memory}
                    onDelete={handleDelete}
                    onToggleImportant={handleToggleImportant}
                    isImportant={importantIds.has(memory.id)}
                    isDeleting={deletingId === memory.id}
                    isHighlighted={memory.id === highlightedId}
                    highlightText={debouncedSearchQuery}
                    compact
                  />
                </motion.div>
              ))}
              
              {/* 底部提示 */}
              <div className="text-center pt-4 pb-2">
                <span className="text-xs text-slate-600">
                  共 {filteredMemories.length} 条记忆
                  {filter !== 'all' && ` (已筛选)`}
                </span>
              </div>
            </>
          )}
        </div>

        {/* 底部操作栏 */}
        <div className="p-4 border-t border-white/10">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">
                ID: {(sessionId || 'unknown').slice(0, 8)}...
              </span>
              {!networkStatus.online && (
                <span className="flex items-center gap-1 text-[10px] text-amber-500">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                  离线
                </span>
              )}
            </div>
            <button
              onClick={() => fetchSessionMemories(true)}
              disabled={loading || !networkStatus.online}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 text-xs text-slate-400 hover:bg-white/10 hover:text-white transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              刷新
            </button>
          </div>
        </div>
      </motion.div>

      {/* 全局错误提示 */}
      <APIErrorToast
        error={error ? new Error(error) : null}
        onRetry={handleRetry}
        onDismiss={() => setError(null)}
        duration={5000}
      />
    </>
  );
}
