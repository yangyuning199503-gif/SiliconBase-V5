/**
 * 失败分析仪表盘
 * SiliconBase V5 - Failure Analytics Dashboard
 * 
 * 功能：
 *   ✓ 显示最近失败统计
 *   ✓ 按根因分类可视化
 *   ✓ 提示词补丁建议
 *   ✓ 版本对比
 */

import React, { useState, useEffect } from 'react';
import { 
  AlertTriangle, 
  BarChart3, 
  Clock, 
  FileText, 
  CheckCircle,
  XCircle,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
  RefreshCw,
  Lightbulb,
  TrendingUp,
  TrendingDown
} from 'lucide-react';
import { FailureStats, ROOT_CAUSES } from '../types/prompt';
import { getFailureStats, generateDailyReport } from '../utils/api/prompt';

interface FailureAnalyticsDashboardProps {
  className?: string;
}

export const FailureAnalyticsDashboard: React.FC<FailureAnalyticsDashboardProps> = ({
  className = ''
}) => {
  const [stats, setStats] = useState<FailureStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(7);
  const [expandedCause, setExpandedCause] = useState<string | null>(null);
  const [copiedPatch, setCopiedPatch] = useState<string | null>(null);
  const [dailyReport, setDailyReport] = useState<string>('');

  // 加载数据
  const loadStats = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getFailureStats(days);
      setStats(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  // 生成每日报告
  const loadDailyReport = async () => {
    try {
      const report = await generateDailyReport();
      setDailyReport(report);
    } catch (err) {
      console.error('加载报告失败:', err);
    }
  };

  useEffect(() => {
    loadStats();
    loadDailyReport();
  }, [days]);

  // 复制补丁到剪贴板
  const copyPatch = (patch: string, id: string) => {
    navigator.clipboard.writeText(patch);
    setCopiedPatch(id);
    setTimeout(() => setCopiedPatch(null), 2000);
  };

  // 如果没有数据
  if (!stats && !loading && !error) {
    return (
      <div className={`bg-sb-bg-secondary border border-white/10 rounded-xl p-8 ${className}`}>
        <div className="text-center text-sb-text-secondary">
          <AlertTriangle className="w-12 h-12 mx-auto mb-4 opacity-50" />
          <p>暂无失败分析数据</p>
          <p className="text-sm mt-2">系统需要积累一些运行数据后才能生成分析</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`space-y-6 ${className}`}>
      {/* 头部控制栏 */}
      <div className="flex items-center justify-between bg-sb-bg-secondary border border-white/10 rounded-xl px-4 py-3">
        <div className="flex items-center gap-3">
          <BarChart3 className="w-5 h-5 text-sb-cyan" />
          <span className="font-medium text-sb-text-primary">失败分析仪表盘</span>
        </div>
        
        <div className="flex items-center gap-3">
          {/* 时间范围选择 */}
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-sb-cyan/50"
          >
            <option value={1}>最近1天</option>
            <option value={7}>最近7天</option>
            <option value={30}>最近30天</option>
          </select>
          
          {/* 刷新按钮 */}
          <button
            onClick={loadStats}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-white/5 hover:bg-white/10 rounded-lg text-sm transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </button>
        </div>
      </div>

      {loading && (
        <div className="bg-sb-bg-secondary border border-white/10 rounded-xl p-8 text-center">
          <RefreshCw className="w-8 h-8 text-sb-cyan animate-spin mx-auto" />
          <p className="mt-4 text-sb-text-secondary">加载统计数据...</p>
        </div>
      )}

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400">
          <div className="flex items-center gap-2">
            <XCircle className="w-5 h-5" />
            <span>加载失败: {error}</span>
          </div>
        </div>
      )}

      {stats && (
        <>
          {/* 概览卡片 */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* 总失败数 */}
            <div className="bg-sb-bg-secondary border border-white/10 rounded-xl p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-sb-text-secondary">总失败数</p>
                  <p className="text-2xl font-bold text-sb-text-primary mt-1">
                    {stats.totalFailures}
                  </p>
                  <p className="text-xs text-sb-text-secondary mt-1">
                    最近{stats.periodDays}天
                  </p>
                </div>
                <div className="p-3 bg-red-500/10 rounded-lg">
                  <AlertTriangle className="w-6 h-6 text-red-400" />
                </div>
              </div>
            </div>

            {/* 最高失败率任务 */}
            <div className="bg-sb-bg-secondary border border-white/10 rounded-xl p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-sb-text-secondary">失败最多任务</p>
                  <p className="text-lg font-bold text-sb-text-primary mt-1 truncate max-w-[150px]">
                    {stats.topFailingTasks[0]?.[0] || '无数据'}
                  </p>
                  <p className="text-xs text-sb-text-secondary mt-1">
                    {stats.topFailingTasks[0]?.[1] || 0}次失败
                  </p>
                </div>
                <div className="p-3 bg-amber-500/10 rounded-lg">
                  <TrendingUp className="w-6 h-6 text-amber-400" />
                </div>
              </div>
            </div>

            {/* 提示词版本对比 */}
            <div className="bg-sb-bg-secondary border border-white/10 rounded-xl p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-sb-text-secondary">提示词版本</p>
                  <p className="text-lg font-bold text-sb-text-primary mt-1">
                    {Object.keys(stats.byVersion).length}个
                  </p>
                  <p className="text-xs text-sb-text-secondary mt-1">
                    统计不同版本表现
                  </p>
                </div>
                <div className="p-3 bg-blue-500/10 rounded-lg">
                  <FileText className="w-6 h-6 text-blue-400" />
                </div>
              </div>
            </div>
          </div>

          {/* 根因分析 */}
          <div className="bg-sb-bg-secondary border border-white/10 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-white/10 bg-white/5">
              <h3 className="font-medium text-sb-text-primary flex items-center gap-2">
                <Lightbulb className="w-5 h-5 text-sb-cyan" />
                失败根因分析
              </h3>
            </div>

            <div className="divide-y divide-white/5">
              {Object.entries(stats.byCause)
                .sort((a, b) => b[1].count - a[1].count)
                .map(([causeName, data]) => {
                  const isExpanded = expandedCause === causeName;
                  const rootCause = Object.values(ROOT_CAUSES).find(r => r.name === causeName);
                  const percent = stats.totalFailures > 0 
                    ? (data.count / stats.totalFailures) * 100 
                    : 0;

                  return (
                    <div key={causeName}>
                      <button
                        onClick={() => setExpandedCause(isExpanded ? null : causeName)}
                        className="w-full px-4 py-4 flex items-center justify-between hover:bg-white/5 transition-colors"
                      >
                        <div className="flex-1">
                          <div className="flex items-center gap-3">
                            {/* 颜色指示器 */}
                            <div 
                              className="w-3 h-3 rounded-full"
                              style={{ backgroundColor: rootCause?.color || '#6B7280' }}
                            />
                            
                            <span className="font-medium text-sb-text-primary">
                              {causeName}
                            </span>
                            
                            <span className="px-2 py-0.5 text-xs bg-white/10 rounded">
                              {data.count}次
                            </span>
                            
                            <span className="text-xs text-sb-text-secondary">
                              {percent.toFixed(1)}%
                            </span>
                          </div>

                          {/* 进度条 */}
                          <div className="mt-2 h-2 bg-white/10 rounded-full overflow-hidden">
                            <div
                              className="h-full rounded-full transition-all duration-500"
                              style={{ 
                                width: `${percent}%`,
                                backgroundColor: rootCause?.color || '#6B7280'
                              }}
                            />
                          </div>
                        </div>

                        {isExpanded ? (
                          <ChevronUp className="w-5 h-5 text-sb-text-secondary ml-3" />
                        ) : (
                          <ChevronDown className="w-5 h-5 text-sb-text-secondary ml-3" />
                        )}
                      </button>

                      {/* 展开详情 */}
                      {isExpanded && (
                        <div className="px-4 pb-4 bg-black/20">
                          {/* 描述 */}
                          <p className="text-sm text-sb-text-secondary mb-3">
                            {rootCause?.description}
                          </p>

                          {/* 典型案例 */}
                          {data.examples.length > 0 && (
                            <div className="mb-4">
                              <p className="text-sm font-medium text-sb-text-primary mb-2">
                                典型案例
                              </p>
                              <div className="space-y-2">
                                {data.examples.map((ex, idx) => (
                                  <div 
                                    key={idx}
                                    className="p-2 bg-white/5 rounded text-sm"
                                  >
                                    <div className="flex items-start justify-between gap-2">
                                      <p className="text-sb-cyan font-medium">{ex.task}</p>
                                      {ex.patch && (
                                        <button
                                          onClick={() => copyPatch(ex.patch!, `${causeName}_${idx}`)}
                                          className="flex-shrink-0 flex items-center gap-1 px-2 py-0.5 rounded bg-white/10 hover:bg-white/20 transition-colors text-xs text-sb-text-secondary"
                                          title="复制提示词补丁"
                                        >
                                          {copiedPatch === `${causeName}_${idx}` ? (
                                            <>
                                              <Check className="w-3 h-3 text-green-400" />
                                              <span className="text-green-400">已复制</span>
                                            </>
                                          ) : (
                                            <>
                                              <Copy className="w-3 h-3" />
                                              <span>复制补丁</span>
                                            </>
                                          )}
                                        </button>
                                      )}
                                    </div>
                                    <p className="text-sb-text-secondary mt-1">
                                      {ex.explanation}
                                    </p>
                                    {ex.suggestedFix && (
                                      <p className="text-xs text-green-400/80 mt-1">
                                        建议: {ex.suggestedFix}
                                      </p>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* 优化建议 */}
                          {causeName === '提示词描述不清' && (
                            <div className="p-3 bg-green-500/10 border border-green-500/30 rounded-lg">
                              <div className="flex items-center gap-2 text-green-400 mb-2">
                                <CheckCircle className="w-4 h-4" />
                                <span className="font-medium">优化建议</span>
                              </div>
                              <p className="text-sm text-sb-text-secondary">
                                考虑为该模块添加更多示例，或使用更明确的指令格式。
                                建议尝试&quot;精简版&quot;变体以减少歧义。
                              </p>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
            </div>
          </div>

          {/* 版本对比 */}
          {Object.keys(stats.byVersion).length > 0 && (
            <div className="bg-sb-bg-secondary border border-white/10 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-white/10 bg-white/5">
                <h3 className="font-medium text-sb-text-primary flex items-center gap-2">
                  <Clock className="w-5 h-5 text-sb-cyan" />
                  提示词版本对比
                </h3>
              </div>

              <div className="divide-y divide-white/5">
                {Object.entries(stats.byVersion)
                  .sort((a, b) => b[1].failures - a[1].failures)
                  .map(([version, data]) => (
                    <div key={version} className="px-4 py-3 flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="font-mono text-sm">{version}</span>
                        <span className="px-2 py-0.5 text-xs bg-white/10 rounded">
                          {data.failures}次失败
                        </span>
                      </div>
                      
                      {data.failureRate !== undefined && (
                        <div className="flex items-center gap-2">
                          {data.failureRate > 0.2 ? (
                            <TrendingUp className="w-4 h-4 text-red-400" />
                          ) : (
                            <TrendingDown className="w-4 h-4 text-green-400" />
                          )}
                          <span className={`text-sm ${
                            data.failureRate > 0.2 ? 'text-red-400' : 'text-green-400'
                          }`}>
                            {(data.failureRate * 100).toFixed(1)}% 失败率
                          </span>
                        </div>
                      )}
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* 每日报告 */}
          {dailyReport && (
            <div className="bg-sb-bg-secondary border border-white/10 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-white/10 bg-white/5">
                <h3 className="font-medium text-sb-text-primary flex items-center gap-2">
                  <FileText className="w-5 h-5 text-sb-cyan" />
                  每日分析报告
                </h3>
              </div>
              <div className="p-4">
                <pre className="text-sm text-sb-text-secondary whitespace-pre-wrap font-mono">
                  {dailyReport}
                </pre>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default FailureAnalyticsDashboard;
