/**
 * 监控面板页面
 */
import React, { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import {
  Activity, Cpu, HardDrive, Layers, ListTodo,
  Brain, Clock, TrendingUp, RefreshCw, AlertTriangle,
  Star, Zap, Trophy, Target
} from 'lucide-react';
import { useGamification } from '../hooks/useGamification';
import { metricsAPI, SystemMetrics, TaskMetrics, MemoryMetrics, Reflection } from '../utils/api/metrics';

// 简化的图表组件
function SimpleChart({ data, color = '#00d4ff' }: { data: number[]; color?: string }) {
  if (!data || data.length < 2) {
    return <div className="h-32 flex items-center justify-center text-xs text-sb-text-secondary">数据不足</div>;
  }
  
  const validData = data.filter(v => typeof v === 'number' && !isNaN(v));
  if (validData.length < 2) {
    return <div className="h-32 flex items-center justify-center text-xs text-sb-text-secondary">无效数据</div>;
  }
  
  const max = Math.max(...validData, 1);
  const min = Math.min(...validData, 0);
  const range = max - min || 1;
  
  const points = validData.map((value, index) => {
    const x = (index / (validData.length - 1)) * 100;
    const y = 100 - ((value - min) / range) * 100;
    return `${x},${y}`;
  }).join(' ');

  return (
    <svg viewBox="0 0 100 100" className="w-full h-32" preserveAspectRatio="none">
      <defs>
        <linearGradient id={`gradient-${color}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon
        points={`0,100 ${points} 100,100`}
        fill={`url(#gradient-${color})`}
      />
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// 指标卡片组件
const MetricCard = React.memo(function MetricCard({
  title,
  value,
  subtitle,
  icon: Icon,
  color,
  trend,
  chart
}: {
  title: string;
  value: string;
  subtitle?: string;
  icon: any;
  color: string;
  trend?: number;
  chart?: number[];
}) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="bg-sb-bg-secondary/50 border border-white/5 rounded-xl p-5 hover:border-sb-cyan/30 transition-all"
    >
      <div className="flex items-start justify-between mb-4">
        <div>
          <p className="text-sb-text-secondary text-sm">{title}</p>
          <p className="text-2xl font-bold text-white mt-1">{value}</p>
          {subtitle && <p className="text-xs text-sb-text-secondary mt-1">{subtitle}</p>}
        </div>
        <div className="p-2 rounded-lg" style={{ backgroundColor: `${color}20` }}>
          <Icon className="w-5 h-5" style={{ color }} />
        </div>
      </div>
      
      {trend !== undefined && (
        <div className="flex items-center gap-2 mb-2">
          <TrendingUp className={`w-4 h-4 ${trend >= 0 ? 'text-green-400' : 'text-red-400'}`} />
          <span className={`text-sm ${trend >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {trend >= 0 ? '+' : ''}{(trend ?? 0).toFixed(1)}%
          </span>
        </div>
      )}
      
      {chart && chart.length > 0 && (
        <SimpleChart data={chart} color={color} />
      )}
    </motion.div>
  );
});

async function fetchDashboardData() {
  const system = await metricsAPI.getSystemMetrics().catch(() => null);
  const tasks = await metricsAPI.getTaskMetrics().catch(() => null);
  const memory = await metricsAPI.getMemoryMetrics().catch(() => null);
  const refs = await metricsAPI.getReflections().catch(() => ({ reflections: [] }));
  return { system, tasks, memory, refs };
}

export function DashboardPage() {
  const [systemMetrics, setSystemMetrics] = useState<SystemMetrics | null>(null);
  const [taskMetrics, setTaskMetrics] = useState<TaskMetrics | null>(null);
  const [memoryMetrics, setMemoryMetrics] = useState<MemoryMetrics | null>(null);
  const [reflections, setReflections] = useState<Reflection[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  
  // 游戏化状态
  const { status: gamificationStatus } = useGamification();
  
  // 历史数据用于图表
  const [cpuHistory, setCpuHistory] = useState<number[]>([]);
  const [memoryHistory, setMemoryHistory] = useState<number[]>([]);

  const { data: queryData, isLoading: loading, refetch: loadData, error: queryError } = useQuery({
    queryKey: ['dashboard'],
    queryFn: fetchDashboardData,
    refetchInterval: autoRefresh ? 5000 : false,
  });

  useEffect(() => {
    if (queryError) {
      setError(queryError instanceof Error ? queryError.message : '加载数据失败');
    } else if (queryData) {
      setError(null);
      const { system, tasks, memory, refs } = queryData;
      if (system) {
        setSystemMetrics(system);
        setCpuHistory(prev => [...prev.slice(-19), system.cpu_percent || 0]);
        setMemoryHistory(prev => [...prev.slice(-19), system.memory?.percent || 0]);
      }
      if (tasks) setTaskMetrics(tasks);
      if (memory) setMemoryMetrics(memory);
      if (refs) setReflections(refs.reflections.slice(0, 5));
    }
  }, [queryData, queryError]);

  if (loading && !systemMetrics) {
    return (
      <div className="h-full flex items-center justify-center">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
          className="w-8 h-8 border-2 border-sb-cyan border-t-transparent rounded-full"
        />
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* 标题栏 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Activity className="w-6 h-6 text-sb-cyan" />
            <h1 className="text-2xl font-bold text-white">监控面板</h1>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-sb-text-secondary cursor-pointer">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="w-4 h-4 rounded border-white/20 bg-sb-bg-secondary text-sb-cyan"
              />
              自动刷新
            </label>
            <button
              onClick={() => loadData()}
              disabled={loading}
              className="p-2 text-sb-text-secondary hover:text-white transition-colors"
            >
              <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* 错误提示 */}
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-2 p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400"
          >
            <AlertTriangle className="w-5 h-5" />
            {error}
          </motion.div>
        )}

        {/* 系统资源指标 */}
        <div>
          <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <Cpu className="w-5 h-5 text-sb-cyan" />
            系统资源
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <MetricCard
              title="CPU 使用率"
              value={`${(systemMetrics?.cpu_percent ?? 0).toFixed(1)}%`}
              subtitle="过去5分钟平均"
              icon={Cpu}
              color="#00d4ff"
              chart={cpuHistory}
            />
            <MetricCard
              title="内存使用"
              value={`${(systemMetrics?.memory?.percent ?? 0).toFixed(1)}%`}
              subtitle={`${((systemMetrics?.memory?.used ?? 0) / 1e9).toFixed(2)} / ${((systemMetrics?.memory?.total ?? 0) / 1e9).toFixed(2)} GB`}
              icon={Layers}
              color="#00ff88"
              chart={memoryHistory}
            />
            <MetricCard
              title="磁盘使用"
              value={`${(systemMetrics?.disk?.percent ?? 0).toFixed(1)}%`}
              subtitle={`${((systemMetrics?.disk?.used ?? 0) / 1e9).toFixed(2)} / ${((systemMetrics?.disk?.total ?? 0) / 1e9).toFixed(2)} GB`}
              icon={HardDrive}
              color="#ffaa00"
            />
          </div>
        </div>

        {/* 任务队列指标 */}
        <div>
          <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <ListTodo className="w-5 h-5 text-sb-cyan" />
            任务队列
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              title="队列大小"
              value={(taskMetrics?.queue_size ?? 0).toString()}
              subtitle="待处理任务"
              icon={ListTodo}
              color="#00d4ff"
            />
            <MetricCard
              title="今日完成"
              value={(taskMetrics?.completed_today ?? 0).toString()}
              subtitle="成功任务"
              icon={CheckIcon}
              color="#00ff88"
            />
            <MetricCard
              title="今日失败"
              value={(taskMetrics?.failed_today ?? 0).toString()}
              subtitle="失败任务"
              icon={AlertTriangle}
              color="#ff4444"
            />
            <MetricCard
              title="平均等待"
              value={`${(taskMetrics?.average_wait_time ?? 0).toFixed(1)}s`}
              subtitle="任务等待时间"
              icon={Clock}
              color="#ffaa00"
            />
          </div>
        </div>

        {/* 记忆库统计 */}
        <div>
          <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <Brain className="w-5 h-5 text-sb-cyan" />
            记忆库
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              title="短期记忆"
              value={(memoryMetrics?.short_term_count ?? 0).toString()}
              subtitle="最近1小时"
              icon={Layers}
              color="#00d4ff"
            />
            <MetricCard
              title="长期记忆"
              value={(memoryMetrics?.long_term_count ?? 0).toString()}
              subtitle="持久化存储"
              icon={HardDrive}
              color="#00ff88"
            />
            <MetricCard
              title="进化记忆"
              value={(memoryMetrics?.evolution_count ?? 0).toString()}
              subtitle="反思与进化"
              icon={Brain}
              color="#ffaa00"
            />
            <MetricCard
              title="向量条目"
              value={(memoryMetrics?.vector_entries ?? 0).toString()}
              subtitle="语义索引"
              icon={Activity}
              color="#ff66ff"
            />
          </div>
        </div>

        {/* 最近反思 */}
        {reflections.length > 0 && (
          <div>
            <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
              <Brain className="w-5 h-5 text-purple-400" />
              最近反思
            </h2>
            <div className="space-y-3">
              {reflections.map((r) => (
                <div key={r.id} className="bg-sb-bg-secondary/50 border border-white/5 rounded-xl p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-sb-text-secondary">{r.scene || '通用场景'}</span>
                    <span className="text-xs text-sb-text-secondary">{new Date(r.created_at).toLocaleDateString('zh-CN')}</span>
                  </div>
                  <p className="text-sm text-white/80 line-clamp-2">{r.content}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 游戏化进度 - 新增 */}
        {gamificationStatus && (
          <div>
            <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
              <Trophy className="w-5 h-5 text-amber-400" />
              成长进度
              <span className="text-sm font-normal text-sb-text-secondary ml-2">
                Lv.{gamificationStatus.level.current_level} {gamificationStatus.level.level_name}
              </span>
            </h2>
            
            {/* 等级进度卡片 */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              <MetricCard
                title="当前等级"
                value={`Lv.${gamificationStatus.level.current_level}`}
                subtitle={gamificationStatus.level.level_name}
                icon={Star}
                color={gamificationStatus.level.level_color}
              />
              <MetricCard
                title="经验值"
                value={`${gamificationStatus.level.current_xp}`}
                subtitle={`距离下一级还需 ${gamificationStatus.level.xp_to_next} XP`}
                icon={Zap}
                color="#FFAA00"
              />
              <MetricCard
                title="使用工具"
                value={gamificationStatus.stats.unique_tools_used.toString()}
                subtitle={`累计 ${gamificationStatus.stats.total_tools_used} 次`}
                icon={Target}
                color="#00D4FF"
              />
              <MetricCard
                title="分类解锁"
                value={`${gamificationStatus.stats.categories_unlocked}/${gamificationStatus.stats.total_categories}`}
                subtitle={`已解锁 ${gamificationStatus.stats.categories_unlocked} 个分类`}
                icon={Trophy}
                color="#FF66FF"
              />
            </div>
            
            {/* 分类解锁进度 */}
            <div className="bg-sb-bg-secondary/50 border border-white/5 rounded-xl p-5">
              <h3 className="text-sm font-medium text-white/80 mb-4">工具分类解锁进度</h3>
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                {gamificationStatus.categories.map((category) => (
                  <motion.div
                    key={category.name}
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className={`p-3 rounded-lg border transition-all ${
                      category.is_unlocked
                        ? 'bg-white/5 border-white/10'
                        : 'bg-white/[0.02] border-white/5 opacity-60'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-lg">{category.icon}</span>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-white/90 truncate">{category.name}</div>
                        <div className="flex items-center gap-1 mt-1">
                          <div className="flex-1 h-1 bg-white/10 rounded-full overflow-hidden">
                            <div
                              className="h-full rounded-full transition-all"
                              style={{
                                width: `${category.progress}%`,
                                backgroundColor: category.color
                              }}
                            />
                          </div>
                          {category.is_unlocked ? (
                            <span className="text-[10px] text-green-400">✓</span>
                          ) : (
                            <span className="text-[10px] text-white/40">Lv.{category.unlock_level}</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// 简单的勾选图标
function CheckIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="20,6 9,17 4,12" />
    </svg>
  );
}
