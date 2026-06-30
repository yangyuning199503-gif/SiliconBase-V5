import React, { useState, useEffect, useCallback } from 'react';
import {
  BarChart3,
  Star,
  TrendingUp,
  Clock,
  Target,
  Award,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Lightbulb,
  AlertCircle,
} from 'lucide-react';
import {
  getTemplateReport,
  getExperimentComparison,
  getLatestWeeklyReport,
  generateWeeklyReport,
  TemplateReport,
  ExperimentComparison,
  WeeklyReport,
} from '../services/templateExperiment';

/**
 * 模板效果对比Dashboard组件
 * 
 * 功能：
 * 1. 展示5个模板的效果对比图表
 * 2. 显示成功率、用户评分、执行时间等指标
 * 3. 展示每周实验报告
 * 4. 支持手动刷新数据
 * 5. 显示推荐建议
 */

const TEMPLATE_NAMES: Record<string, string> = {
  guardian: '守护者',
  explorer: '探索者',
  geek: '极客',
  artist: '艺术家',
  balanced: '均衡者',
};

const TEMPLATE_COLORS: Record<string, string> = {
  guardian: '#10B981',  // emerald
  explorer: '#8B5CF6',  // violet
  geek: '#3B82F6',      // blue
  artist: '#EC4899',    // pink
  balanced: '#F59E0B',  // amber
};

const TEMPLATE_ICONS: Record<string, string> = {
  guardian: '🛡️',
  explorer: '🔭',
  geek: '💻',
  artist: '🎨',
  balanced: '⚖️',
};

interface MetricCardProps {
  title: string;
  value: string | number;
  unit?: string;
  icon: React.ReactNode;
  trend?: 'up' | 'down' | 'neutral';
  color: string;
}

const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  unit,
  icon,
  trend,
  color,
}) => (
  <div className="bg-white dark:bg-gray-800 rounded-xl p-4 shadow-sm border border-gray-100 dark:border-gray-700">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-xs text-gray-500 dark:text-gray-400">{title}</p>
        <p className="text-2xl font-bold mt-1" style={{ color }}>
          {value}
          {unit && <span className="text-sm font-normal ml-1">{unit}</span>}
        </p>
      </div>
      <div
        className="p-3 rounded-lg"
        style={{ backgroundColor: `${color}20` }}
      >
        {icon}
      </div>
    </div>
    {trend && (
      <div className="flex items-center gap-1 mt-2">
        {trend === 'up' && <TrendingUp className="w-3 h-3 text-green-500" />}
        {trend === 'down' && (
          <TrendingUp className="w-3 h-3 text-red-500 rotate-180" />
        )}
        <span
          className={`text-xs ${
            trend === 'up'
              ? 'text-green-500'
              : trend === 'down'
              ? 'text-red-500'
              : 'text-gray-400'
          }`}
        >
          {trend === 'up' ? '上升' : trend === 'down' ? '下降' : '持平'}
        </span>
      </div>
    )}
  </div>
);

interface BarChartProps {
  data: {
    labels: string[];
    values: number[];
    colors: string[];
  };
  maxValue?: number;
  unit?: string;
}

const SimpleBarChart: React.FC<BarChartProps> = ({ data, maxValue, unit }) => {
  const max = maxValue || Math.max(...data.values, 1);

  return (
    <div className="space-y-3">
      {data.labels.map((label, index) => (
        <div key={label} className="space-y-1">
          <div className="flex justify-between text-sm">
            <span className="flex items-center gap-2">
              <span>{TEMPLATE_ICONS[label]}</span>
              <span className="text-gray-700 dark:text-gray-300">
                {TEMPLATE_NAMES[label] || label}
              </span>
            </span>
            <span className="font-medium text-gray-900 dark:text-white">
              {data.values[index].toFixed(2)}
              {unit}
            </span>
          </div>
          <div className="h-2 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${(data.values[index] / max) * 100}%`,
                backgroundColor: data.colors[index],
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
};

export const TemplateExperimentDashboard: React.FC = () => {
  const [templateReport, setTemplateReport] = useState<
    Record<string, TemplateReport>
  >({});
  const [comparison, setComparison] = useState<ExperimentComparison | null>(
    null
  );
  const [weeklyReport, setWeeklyReport] = useState<WeeklyReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRecommendations, setExpandedRecommendations] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [report, comp, weekly] = await Promise.all([
        getTemplateReport(),
        getExperimentComparison(),
        getLatestWeeklyReport(),
      ]);

      setTemplateReport(report);
      setComparison(comp);
      setWeeklyReport(weekly);
    } catch (err) {
      setError('加载数据失败，请稍后重试');
      console.error('[TemplateDashboard] 加载数据失败:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleGenerateReport = async () => {
    setLoading(true);
    try {
      const report = await generateWeeklyReport();
      if (report) {
        setWeeklyReport(report);
      }
    } catch (err) {
      console.error('[TemplateDashboard] 生成报告失败:', err);
    } finally {
      setLoading(false);
    }
  };

  // 计算总体统计
  const totalTasks = Object.values(templateReport).reduce(
    (sum, t) => sum + t.total_tasks,
    0
  );
  const avgSuccessRate =
    Object.values(templateReport).reduce(
      (sum, t) => sum + t.success_rate * t.total_tasks,
      0
    ) / (totalTasks || 1);
  const avgRating =
    Object.values(templateReport).reduce(
      (sum, t) => sum + t.avg_rating * t.rating_count,
      0
    ) /
    (Object.values(templateReport).reduce(
      (sum, t) => sum + t.rating_count,
      0
    ) || 1);

  // 找出最佳模板
  const bestTemplate = Object.entries(templateReport).reduce(
    (best, [name, stats]) => {
      const score =
        stats.success_rate * 0.5 + (stats.avg_rating / 5) * 0.5;
      return score > best.score ? { name, score, stats } : best;
    },
    { name: '', score: 0, stats: null as TemplateReport | null }
  );

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-blue-500" />
            模板效果实验
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            A/B测试数据分析与推荐系统
          </p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          刷新数据
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 p-4 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 rounded-lg">
          <AlertCircle className="w-5 h-5" />
          {error}
        </div>
      )}

      {/* Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="总任务数"
          value={totalTasks}
          icon={<Target className="w-5 h-5 text-blue-500" />}
          color="#3B82F6"
        />
        <MetricCard
          title="平均成功率"
          value={(avgSuccessRate * 100).toFixed(1)}
          unit="%"
          icon={<TrendingUp className="w-5 h-5 text-green-500" />}
          color="#10B981"
        />
        <MetricCard
          title="平均评分"
          value={avgRating.toFixed(2)}
          unit="/5"
          icon={<Star className="w-5 h-5 text-amber-500" />}
          color="#F59E0B"
        />
        <MetricCard
          title="最佳模板"
          value={bestTemplate.name ? TEMPLATE_NAMES[bestTemplate.name] : '-'}
          icon={<Award className="w-5 h-5 text-purple-500" />}
          color="#8B5CF6"
        />
      </div>

      {/* Charts */}
      {comparison && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Success Rate Chart */}
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm border border-gray-100 dark:border-gray-700">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
              <TrendingUp className="w-5 h-5 text-green-500" />
              任务成功率对比
            </h3>
            <SimpleBarChart
              data={{
                labels: comparison.templates,
                values: comparison.success_rates,
                colors: comparison.templates.map(
                  (t) => TEMPLATE_COLORS[t] || '#6B7280'
                ),
              }}
              maxValue={1}
              unit="%"
            />
          </div>

          {/* User Rating Chart */}
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm border border-gray-100 dark:border-gray-700">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
              <Star className="w-5 h-5 text-amber-500" />
              用户评分对比
            </h3>
            <SimpleBarChart
              data={{
                labels: comparison.templates,
                values: comparison.avg_ratings,
                colors: comparison.templates.map(
                  (t) => TEMPLATE_COLORS[t] || '#6B7280'
                ),
              }}
              maxValue={5}
              unit="/5"
            />
          </div>

          {/* Execution Time Chart */}
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm border border-gray-100 dark:border-gray-700">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
              <Clock className="w-5 h-5 text-blue-500" />
              平均执行时间
            </h3>
            <SimpleBarChart
              data={{
                labels: comparison.templates,
                values: comparison.avg_execution_times.map((t) => t / 1000),
                colors: comparison.templates.map(
                  (t) => TEMPLATE_COLORS[t] || '#6B7280'
                ),
              }}
              unit="s"
            />
          </div>

          {/* Task Count Chart */}
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 shadow-sm border border-gray-100 dark:border-gray-700">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-purple-500" />
              任务数量分布
            </h3>
            <SimpleBarChart
              data={{
                labels: comparison.templates,
                values: comparison.total_tasks,
                colors: comparison.templates.map(
                  (t) => TEMPLATE_COLORS[t] || '#6B7280'
                ),
              }}
            />
          </div>
        </div>
      )}

      {/* Weekly Report */}
      {weeklyReport && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 overflow-hidden">
          <div
            className="flex items-center justify-between p-4 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
            onClick={() => setExpandedRecommendations(!expandedRecommendations)}
          >
            <div className="flex items-center gap-2">
              <Lightbulb className="w-5 h-5 text-yellow-500" />
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                本周实验报告
              </h3>
              <span className="text-sm text-gray-500 dark:text-gray-400">
                ({weeklyReport.week_start} ~ {weeklyReport.week_end})
              </span>
            </div>
            {expandedRecommendations ? (
              <ChevronUp className="w-5 h-5 text-gray-400" />
            ) : (
              <ChevronDown className="w-5 h-5 text-gray-400" />
            )}
          </div>

          {expandedRecommendations && (
            <div className="p-4 pt-0 space-y-4">
              {weeklyReport.winner_template && (
                <div className="flex items-center gap-3 p-4 bg-gradient-to-r from-yellow-50 to-amber-50 dark:from-yellow-900/20 dark:to-amber-900/20 rounded-lg border border-yellow-200 dark:border-yellow-800">
                  <Award className="w-8 h-8 text-yellow-500" />
                  <div>
                    <p className="text-sm text-gray-600 dark:text-gray-400">
                      本周最佳模板
                    </p>
                    <p className="text-xl font-bold text-gray-900 dark:text-white">
                      {TEMPLATE_ICONS[weeklyReport.winner_template]}{' '}
                      {TEMPLATE_NAMES[weeklyReport.winner_template]}
                    </p>
                  </div>
                </div>
              )}

              <div className="space-y-2">
                <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  优化建议
                </h4>
                <ul className="space-y-2">
                  {weeklyReport.recommendations.map((rec, index) => (
                    <li
                      key={index}
                      className="flex items-start gap-2 text-sm text-gray-600 dark:text-gray-400"
                    >
                      <span className="w-1.5 h-1.5 bg-blue-500 rounded-full mt-2 flex-shrink-0" />
                      {rec}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Template Details Table */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 overflow-hidden">
        <div className="p-4 border-b border-gray-100 dark:border-gray-700">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            模板详细数据
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50 dark:bg-gray-700/50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  模板
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  任务数
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  成功率
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  评分
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  执行时间
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                  平均步骤
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {Object.entries(templateReport).map(([name, stats]) => (
                <tr
                  key={name}
                  className="hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors"
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span>{TEMPLATE_ICONS[name]}</span>
                      <span className="font-medium text-gray-900 dark:text-white">
                        {TEMPLATE_NAMES[name]}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right text-gray-600 dark:text-gray-400">
                    {stats.total_tasks}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span
                      className={`font-medium ${
                        stats.success_rate >= 0.8
                          ? 'text-green-600 dark:text-green-400'
                          : stats.success_rate >= 0.6
                          ? 'text-yellow-600 dark:text-yellow-400'
                          : 'text-red-600 dark:text-red-400'
                      }`}
                    >
                      {(stats.success_rate * 100).toFixed(1)}%
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Star className="w-4 h-4 text-amber-400 fill-amber-400" />
                      <span className="text-gray-900 dark:text-white">
                        {stats.avg_rating.toFixed(2)}
                      </span>
                      <span className="text-xs text-gray-400">
                        ({stats.rating_count})
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right text-gray-600 dark:text-gray-400">
                    {(stats.avg_execution_time_ms / 1000).toFixed(2)}s
                  </td>
                  <td className="px-4 py-3 text-right text-gray-600 dark:text-gray-400">
                    {stats.avg_steps.toFixed(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Generate Report Button */}
      <div className="flex justify-end">
        <button
          onClick={handleGenerateReport}
          disabled={loading}
          className="flex items-center gap-2 px-6 py-3 text-sm font-medium text-white bg-gradient-to-r from-blue-500 to-purple-600 rounded-xl hover:from-blue-600 hover:to-purple-700 disabled:opacity-50 transition-all"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          生成新报告
        </button>
      </div>
    </div>
  );
};

export default TemplateExperimentDashboard;
