/**
 * 实时执行日志组件 - "六部档案" (Real-time Execution Log)
 * 
 * 功能：
 * - 显示详细的执行日志
 * - 支持不同级别的日志条目
 * - 参考唐朝六部档案制度，记录详尽
 */
import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  ScrollText,
  Info,
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  Terminal,
  Brain,
  Wrench,
  Download,
  Trash2,
  Filter,
  Search,
  ChevronDown,
  ChevronUp,
  Maximize2,
  Minimize2,
  Activity
} from 'lucide-react';

// 日志级别
export type LogLevel = 'info' | 'action' | 'success' | 'warning' | 'error' | 'thinking' | 'tool';

// 日志条目接口
export interface LogEntry {
  id: string;
  time: string;
  level: LogLevel;
  message: string;
  params?: Record<string, any>;
  source?: string; // 日志来源
  duration?: number; // 执行耗时(ms)
  importance?: number; // 重要性分数 (0-1)
  isKeyDecision?: boolean; // 是否关键决策点
}

// 执行日志属性
interface ExecutionLogProps {
  entries: LogEntry[];
  className?: string;
  maxHeight?: string;
  showControls?: boolean;
  showTimestamp?: boolean;
  showLevel?: boolean;
  autoScroll?: boolean;
  onClear?: () => void;
  onExport?: () => void;
  // 【新增】重要性筛选
  importanceFilter?: 'all' | 'important' | 'critical';
  minImportance?: number; // 最小重要性阈值 (0-1)
  showImportanceBadge?: boolean; // 显示重要性徽章
}

// 级别配置
const LEVEL_CONFIG: Record<LogLevel, { 
  label: string; 
  color: string;
  bgColor: string;
  borderColor: string;
  icon: React.ReactNode;
}> = {
  info: { 
    label: '信息', 
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10',
    borderColor: 'border-blue-500/30',
    icon: <Info className="w-3 h-3" />
  },
  action: { 
    label: '操作', 
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/10',
    borderColor: 'border-amber-500/30',
    icon: <Activity className="w-3 h-3" />
  },
  success: { 
    label: '成功', 
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10',
    borderColor: 'border-emerald-500/30',
    icon: <CheckCircle2 className="w-3 h-3" />
  },
  warning: { 
    label: '警告', 
    color: 'text-orange-400',
    bgColor: 'bg-orange-500/10',
    borderColor: 'border-orange-500/30',
    icon: <AlertTriangle className="w-3 h-3" />
  },
  error: { 
    label: '错误', 
    color: 'text-red-400',
    bgColor: 'bg-red-500/10',
    borderColor: 'border-red-500/30',
    icon: <AlertCircle className="w-3 h-3" />
  },
  thinking: { 
    label: '思考', 
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/10',
    borderColor: 'border-purple-500/30',
    icon: <Brain className="w-3 h-3" />
  },
  tool: { 
    label: '工具', 
    color: 'text-cyan-400',
    bgColor: 'bg-cyan-500/10',
    borderColor: 'border-cyan-500/30',
    icon: <Wrench className="w-3 h-3" />
  }
};

/**
 * 格式化时间
 */
function formatTime(timeStr: string): string {
  try {
    const date = new Date(`2000-01-01T${timeStr}`);
    return date.toLocaleTimeString('zh-CN', { 
      hour: '2-digit', 
      minute: '2-digit', 
      second: '2-digit',
      hour12: false 
    });
  } catch (error) {
    console.error('[ExecutionLog] 格式化时间失败:', error);
    return timeStr;
  }
}

/**
 * 日志条目组件
 */
const LogEntryItem: React.FC<{
  entry: LogEntry;
  showTimestamp: boolean;
  showLevel: boolean;
  showImportanceBadge?: boolean;
}> = ({ entry, showTimestamp, showLevel, showImportanceBadge = true }) => {
  const config = LEVEL_CONFIG[entry.level];
  const [expanded, setExpanded] = useState(false);
  const hasDetails = entry.params && Object.keys(entry.params).length > 0;
  
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      className="group"
    >
      <div className="flex items-start gap-2 py-1.5 px-2 hover:bg-white/5 rounded transition-colors">
        {/* 时间戳 */}
        {showTimestamp && (
          <span className="text-[10px] text-slate-600 font-mono flex-shrink-0 w-16 pt-0.5">
            {formatTime(entry.time)}
          </span>
        )}
        
        {/* 级别标识 */}
        {showLevel && (
          <div className={`flex-shrink-0 flex items-center gap-1 px-1.5 py-0.5 rounded 
                          ${config.bgColor} ${config.color} text-[10px]`}>
            {config.icon}
            <span className="hidden sm:inline">{config.label}</span>
          </div>
        )}
        
        {/* 内容 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start gap-2">
            <span className="text-xs text-slate-300 break-all">
              {entry.message}
            </span>
            
            {/* 来源 */}
            {entry.source && (
              <span className="text-[10px] text-slate-600 flex-shrink-0">
                [{entry.source}]
              </span>
            )}
            
            {/* 耗时 */}
            {entry.duration !== undefined && (
              <span className="text-[10px] text-slate-500 flex-shrink-0">
                ({entry.duration}ms)
              </span>
            )}
            
            {/* 【新增】重要性徽章 */}
            {showImportanceBadge && entry.importance !== undefined && entry.importance >= 0.7 && (
              <span className={`text-[10px] px-1 rounded flex-shrink-0 ${
                entry.importance >= 0.85 
                  ? 'bg-red-500/20 text-red-400' 
                  : 'bg-amber-500/20 text-amber-400'
              }`}>
                {entry.importance >= 0.85 ? '关键' : '重要'}
                {entry.isKeyDecision && ' ★'}
              </span>
            )}
            
            {/* 【新增】关键决策标记 */}
            {entry.isKeyDecision && (
              <span className="text-[10px] px-1 rounded bg-purple-500/20 text-purple-400 flex-shrink-0">
                决策点
              </span>
            )}
          </div>
          
          {/* 详情展开 */}
          {hasDetails && (
            <div className="mt-1">
              <button
                onClick={() => setExpanded(!expanded)}
                className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-300"
              >
                {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                {expanded ? '收起详情' : '查看详情'}
              </button>
              
              <AnimatePresence>
                {expanded && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    className="mt-1 p-2 rounded bg-black/30 overflow-x-auto"
                  >
                    <pre className="text-[10px] text-slate-400 font-mono">
                      {JSON.stringify(entry.params, null, 2)}
                    </pre>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
};

/**
 * 执行日志组件
 */
export const ExecutionLog: React.FC<ExecutionLogProps> = ({
  entries,
  className = '',
  maxHeight = '300px',
  showControls = true,
  showTimestamp = true,
  showLevel = true,
  autoScroll = true,
  onClear,
  onExport,
  importanceFilter = 'all',
  minImportance = 0.7,
  showImportanceBadge = true
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isExpanded, setIsExpanded] = useState(false);
  const [filter, setFilter] = useState<LogLevel | 'all'>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [isAutoScroll, setIsAutoScroll] = useState(autoScroll);
  const [importanceMode, setImportanceMode] = useState<'all' | 'important' | 'critical'>(importanceFilter);
  
  // 自动滚动
  useEffect(() => {
    if (isAutoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [entries, isAutoScroll]);
  
  // 过滤条目
  const filteredEntries = entries.filter(entry => {
    const matchesFilter = filter === 'all' || entry.level === filter;
    const matchesSearch = !searchTerm || 
      entry.message.toLowerCase().includes(searchTerm.toLowerCase()) ||
      entry.source?.toLowerCase().includes(searchTerm.toLowerCase());
    
    // 【新增】重要性筛选
    let matchesImportance = true;
    if (importanceMode === 'important') {
      matchesImportance = (entry.importance || 0) >= minImportance || entry.isKeyDecision || false;
    } else if (importanceMode === 'critical') {
      matchesImportance = (entry.importance || 0) >= 0.85 || entry.level === 'error' || false;
    }
    
    return matchesFilter && matchesSearch && matchesImportance;
  });
  
  // 【新增】重要性统计
  const importanceStats = {
    total: entries.length,
    important: entries.filter(e => (e.importance || 0) >= minImportance || e.isKeyDecision).length,
    critical: entries.filter(e => (e.importance || 0) >= 0.85 || e.level === 'error').length,
    keyDecisions: entries.filter(e => e.isKeyDecision).length
  };
  
  // 统计
  const stats = {
    total: entries.length,
    info: entries.filter(e => e.level === 'info').length,
    action: entries.filter(e => e.level === 'action').length,
    success: entries.filter(e => e.level === 'success').length,
    warning: entries.filter(e => e.level === 'warning').length,
    error: entries.filter(e => e.level === 'error').length,
    thinking: entries.filter(e => e.level === 'thinking').length,
    tool: entries.filter(e => e.level === 'tool').length
  };

  return (
    <div className={`rounded-lg bg-slate-900/50 border border-white/5 overflow-hidden ${className}`}>
      {/* 头部 - 六部档案标识 */}
      <div className="px-4 py-3 border-b border-white/5 bg-gradient-to-r from-slate-800/50 to-transparent">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ScrollText className="w-4 h-4 text-slate-400" />
            <span className="text-sm font-medium text-white">执行日志</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-500/20 text-slate-400">
              六部档案
            </span>
            <span className="text-xs text-slate-500">
              ({filteredEntries.length}/{entries.length})
            </span>
          </div>
          
          {/* 控制按钮 */}
          {showControls && (
            <div className="flex items-center gap-1">
              {/* 自动滚动开关 */}
              <button
                onClick={() => setIsAutoScroll(!isAutoScroll)}
                className={`p-1.5 rounded transition-colors ${isAutoScroll ? 'text-emerald-400 bg-emerald-500/10' : 'text-slate-500 hover:text-slate-300'}`}
                title={isAutoScroll ? '自动滚动开启' : '自动滚动关闭'}
              >
                <Activity className="w-3.5 h-3.5" />
              </button>
              
              {/* 展开/收起 */}
              <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="p-1.5 rounded text-slate-500 hover:text-slate-300 transition-colors"
                title={isExpanded ? '收起' : '展开'}
              >
                {isExpanded ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
              </button>
              
              {/* 导出 */}
              {onExport && (
                <button
                  onClick={onExport}
                  className="p-1.5 rounded text-slate-500 hover:text-slate-300 transition-colors"
                  title="导出日志"
                >
                  <Download className="w-3.5 h-3.5" />
                </button>
              )}
              
              {/* 清空 */}
              {onClear && (
                <button
                  onClick={onClear}
                  className="p-1.5 rounded text-slate-500 hover:text-red-400 transition-colors"
                  title="清空日志"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          )}
        </div>
        
        {/* 统计和过滤 */}
        <div className="flex flex-wrap items-center gap-2 mt-2">
          {/* 级别过滤 */}
          <div className="flex items-center gap-1">
            <Filter className="w-3 h-3 text-slate-500" />
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value as LogLevel | 'all')}
              className="text-xs bg-black/30 border border-white/10 rounded px-2 py-1 text-slate-300 focus:outline-none focus:border-white/20"
            >
              <option value="all">全部 ({stats.total})</option>
              <option value="info">信息 ({stats.info})</option>
              <option value="action">操作 ({stats.action})</option>
              <option value="success">成功 ({stats.success})</option>
              <option value="warning">警告 ({stats.warning})</option>
              <option value="error">错误 ({stats.error})</option>
              <option value="thinking">思考 ({stats.thinking})</option>
              <option value="tool">工具 ({stats.tool})</option>
            </select>
          </div>
          
          {/* 【新增】重要性过滤 */}
          <div className="flex items-center gap-1">
            <span className="text-xs text-slate-500">重要性:</span>
            <select
              value={importanceMode}
              onChange={(e) => setImportanceMode(e.target.value as 'all' | 'important' | 'critical')}
              className="text-xs bg-black/30 border border-white/10 rounded px-2 py-1 text-slate-300 focus:outline-none focus:border-white/20"
            >
              <option value="all">全部 ({importanceStats.total})</option>
              <option value="important">重要 ({importanceStats.important})</option>
              <option value="critical">关键 ({importanceStats.critical})</option>
            </select>
          </div>
          
          {/* 【新增】关键决策点标记 */}
          {importanceStats.keyDecisions > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400">
              {importanceStats.keyDecisions} 关键决策
            </span>
          )}
          
          {/* 搜索 */}
          <div className="flex items-center gap-1 flex-1 min-w-[120px]">
            <Search className="w-3 h-3 text-slate-500" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="搜索日志..."
              className="flex-1 text-xs bg-black/30 border border-white/10 rounded px-2 py-1 text-slate-300 placeholder:text-slate-600 focus:outline-none focus:border-white/20"
            />
          </div>
        </div>
      </div>
      
      {/* 日志列表 */}
      <div
        ref={scrollRef}
        className="overflow-y-auto scrollbar-thin"
        style={{ maxHeight: isExpanded ? '60vh' : maxHeight }}
      >
        {filteredEntries.length === 0 ? (
          <div className="py-8 flex flex-col items-center justify-center text-slate-600">
            <Terminal className="w-8 h-8 mb-2 opacity-30" />
            <p className="text-xs">暂无日志记录</p>
          </div>
        ) : (
          <div className="py-2 space-y-0.5">
            {filteredEntries.map((entry) => (
              <LogEntryItem
                key={entry.id}
                entry={entry}
                showTimestamp={showTimestamp}
                showLevel={showLevel}
                showImportanceBadge={showImportanceBadge}
              />
            ))}
          </div>
        )}
      </div>
      
      {/* 底部状态 */}
      {entries.length > 0 && (
        <div className="px-4 py-2 border-t border-white/5 bg-black/20">
          <div className="flex items-center gap-3 text-[10px] text-slate-500">
            {stats.error > 0 && (
              <span className="text-red-400">{stats.error} 错误</span>
            )}
            {stats.warning > 0 && (
              <span className="text-orange-400">{stats.warning} 警告</span>
            )}
            <span>{stats.success} 成功</span>
            <span>{stats.tool} 工具调用</span>
            <span className="ml-auto">
              {entries[entries.length - 1]?.time || '--:--:--'}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

/**
 * 紧凑版执行日志
 */
export const ExecutionLogCompact: React.FC<{
  entries: LogEntry[];
  className?: string;
}> = ({ entries, className = '' }) => {
  const latestEntry = entries[entries.length - 1];
  const errorCount = entries.filter(e => e.level === 'error').length;
  
  if (!latestEntry) return null;
  
  const config = LEVEL_CONFIG[latestEntry.level];
  
  return (
    <div className={`flex items-center gap-3 px-3 py-2 rounded-lg bg-slate-900/50 border border-white/5 ${className}`}>
      <ScrollText className="w-4 h-4 text-slate-400" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`${config.color}`}>
            {config.icon}
          </span>
          <span className="text-xs text-slate-300 truncate">
            {latestEntry.message}
          </span>
        </div>
      </div>
      {errorCount > 0 && (
        <span className="text-xs text-red-400">
          {errorCount} 错误
        </span>
      )}
      <span className="text-xs text-slate-500">
        {entries.length} 条
      </span>
    </div>
  );
};

/**
 * 使用执行日志的Hook
 */
export function useExecutionLog() {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [isRecording, setIsRecording] = useState(true);
  
  const addEntry = React.useCallback((entry: Omit<LogEntry, 'id' | 'time'>) => {
    if (!isRecording) return;
    
    const newEntry: LogEntry = {
      ...entry,
      id: `log_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      time: new Date().toLocaleTimeString('zh-CN', { 
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      })
    };
    
    setEntries(prev => [...prev, newEntry]);
  }, [isRecording]);
  
  const addInfo = React.useCallback((message: string, params?: Record<string, any>) => {
    addEntry({ level: 'info', message, params });
  }, [addEntry]);
  
  const addAction = React.useCallback((message: string, params?: Record<string, any>) => {
    addEntry({ level: 'action', message, params });
  }, [addEntry]);
  
  const addSuccess = React.useCallback((message: string, params?: Record<string, any>, duration?: number) => {
    addEntry({ level: 'success', message, params, duration });
  }, [addEntry]);
  
  const addWarning = React.useCallback((message: string, params?: Record<string, any>) => {
    addEntry({ level: 'warning', message, params });
  }, [addEntry]);
  
  const addError = React.useCallback((message: string, params?: Record<string, any>) => {
    addEntry({ level: 'error', message, params });
  }, [addEntry]);
  
  const addThinking = React.useCallback((message: string, params?: Record<string, any>) => {
    addEntry({ level: 'thinking', message, params });
  }, [addEntry]);
  
  const addTool = React.useCallback((message: string, params?: Record<string, any>, duration?: number) => {
    addEntry({ level: 'tool', message, params, duration });
  }, [addEntry]);
  
  const clear = React.useCallback(() => {
    setEntries([]);
  }, []);
  
  const exportLog = React.useCallback(() => {
    const logText = entries.map(e => 
      `[${e.time}] [${e.level.toUpperCase()}] ${e.message}${e.params ? ' ' + JSON.stringify(e.params) : ''}`
    ).join('\n');
    
    const blob = new Blob([logText], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `execution-log-${Date.now()}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [entries]);
  
  const startRecording = React.useCallback(() => {
    setIsRecording(true);
  }, []);
  
  const stopRecording = React.useCallback(() => {
    setIsRecording(false);
  }, []);
  
  return {
    entries,
    addEntry,
    addInfo,
    addAction,
    addSuccess,
    addWarning,
    addError,
    addThinking,
    addTool,
    clear,
    exportLog,
    startRecording,
    stopRecording,
    isRecording,
    count: entries.length,
    hasErrors: entries.some(e => e.level === 'error'),
    hasWarnings: entries.some(e => e.level === 'warning')
  };
}

export default ExecutionLog;
