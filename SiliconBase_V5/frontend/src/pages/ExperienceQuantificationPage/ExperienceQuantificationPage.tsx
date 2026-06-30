import { useState, useEffect, useCallback } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip as RechartsTooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell
} from 'recharts';
import {
  TrendingUp, FileBarChart, FlaskConical as Science, Trash2 as DeleteSweep,
  RefreshCw as Refresh, Info, Trophy as EmojiEvents, AlertTriangle as Warning,
  CheckCircle, Loader2
} from 'lucide-react';
import { fetchAPI } from '../../utils/api/index';

// 类型定义
interface ABTestMetrics {
  total_tasks: number;
  treatment_count: number;
  control_count: number;
  treatment_success_rate: number;
  control_success_rate: number;
  success_rate_lift: number;
  treatment_avg_time_ms: number;
  control_avg_time_ms: number;
  time_improvement_pct: number;
  treatment_avg_satisfaction: number;
  control_avg_satisfaction: number;
  satisfaction_lift: number;
  confidence_level: string;
}

interface ExperienceStats {
  experience_id: string;
  usage_count: number;
  success_count: number;
  failure_count: number;
  success_rate: number;
  avg_execution_time_ms: number;
  avg_satisfaction: number;
  contribution_score: number;
  is_effective: boolean;
  is_ineffective: boolean;
  needs_review: boolean;
}

interface GlobalStats {
  total_experiences: number;
  total_usage: number;
  overall_success_rate: number;
  effective_count: number;
  ineffective_count: number;
  needs_review_count: number;
  avg_contribution_score: number;
}

interface PurgeCandidate {
  experience_id: string;
  reason: string;
  reason_code: string;
  success_rate: number;
  usage_count: number;
  recommended_action: string;
  priority: number;
}

const PIE_COLORS = ['#22c55e', '#f59e0b', '#ef4444', '#3b82f6'];

// 安全格式化数字，避免 undefined/null 导致 .toFixed() 崩溃
const fmtNum = (value: number | undefined | null, digits: number = 1): string => {
  if (value === undefined || value === null || Number.isNaN(value)) return '--';
  return value.toFixed(digits);
};

const fmtPct = (value: number | undefined | null, digits: number = 1): string => {
  if (value === undefined || value === null || Number.isNaN(value)) return '--%';
  return `${(value * 100).toFixed(digits)}%`;
};

function StatusBadge({ status }: { status: 'effective' | 'ineffective' | 'review' | string }) {
  const styles: Record<string, string> = {
    effective: 'bg-green-500/20 text-green-400 border-green-500/30',
    ineffective: 'bg-red-500/20 text-red-400 border-red-500/30',
    review: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  };
  const labels: Record<string, string> = {
    effective: '有效',
    ineffective: '无效',
    review: '待审核',
  };
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium border ${styles[status] || styles.review}`}>
      {labels[status] || status}
    </span>
  );
}

export default function ExperienceQuantificationPage() {
  const [activeTab, setActiveTab] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [abTestMetrics, setAbTestMetrics] = useState<ABTestMetrics | null>(null);
  const [globalStats, setGlobalStats] = useState<GlobalStats | null>(null);
  const [leaderboard, setLeaderboard] = useState<ExperienceStats[]>([]);
  const [purgeCandidates, setPurgeCandidates] = useState<PurgeCandidate[]>([]);

  const fetchABTestData = useCallback(async () => {
    try {
      const data = await fetchAPI<{ success: boolean; metrics?: ABTestMetrics }>('/api/experience/ab-test/report');
      if (data.success) setAbTestMetrics(data.metrics ?? null);
    } catch (err) {
      console.error('Failed to fetch AB test data:', err);
    }
  }, []);

  const fetchGlobalStats = useCallback(async () => {
    try {
      const data = await fetchAPI<{ success: boolean; stats?: GlobalStats }>('/api/experience/effectiveness/global-stats');
      if (data.success) setGlobalStats(data.stats ?? null);
    } catch (err) {
      console.error('Failed to fetch global stats:', err);
    }
  }, []);

  const fetchLeaderboard = useCallback(async () => {
    try {
      const data = await fetchAPI<{ success: boolean; leaderboard?: ExperienceStats[] }>('/api/experience/effectiveness/leaderboard?limit=20');
      if (data.success) setLeaderboard(data.leaderboard ?? []);
    } catch (err) {
      console.error('Failed to fetch leaderboard:', err);
    }
  }, []);

  const fetchPurgeCandidates = useCallback(async () => {
    try {
      const data = await fetchAPI<{ success: boolean; candidates?: PurgeCandidate[] }>('/api/experience/purge/candidates');
      if (data.success) setPurgeCandidates(data.candidates ?? []);
    } catch (err) {
      console.error('Failed to fetch purge candidates:', err);
    }
  }, []);

  const loadAllData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([
        fetchABTestData(),
        fetchGlobalStats(),
        fetchLeaderboard(),
        fetchPurgeCandidates()
      ]);
    } catch (err) {
      setError('数据加载失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }, [fetchABTestData, fetchGlobalStats, fetchLeaderboard, fetchPurgeCandidates]);

  useEffect(() => {
    loadAllData();
  }, [loadAllData]);

  const handleRunPurgeScan = async () => {
    try {
      const data = await fetchAPI<{ success: boolean; candidates?: PurgeCandidate[] }>('/api/experience/purge/scan', { method: 'POST' });
      if (data.success) setPurgeCandidates(data.candidates ?? []);
    } catch (err) {
      console.error('Failed to run purge scan:', err);
    }
  };

  const tabs = [
    { label: '概览', icon: FileBarChart },
    { label: 'A/B测试', icon: Science },
    { label: '排行榜', icon: EmojiEvents },
    { label: '淘汰候选', icon: DeleteSweep },
  ];

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-slate-950 text-slate-400">
        <Loader2 className="w-6 h-6 animate-spin mr-2" />
        加载中...
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto bg-slate-950 text-slate-200 p-4 md:p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              <TrendingUp className="w-6 h-6 text-cyan-400" />
              经验量化分析
            </h1>
            <p className="text-sm text-slate-400 mt-1">追踪经验效果、运行A/B测试、识别低质量经验</p>
          </div>
          <button
            onClick={loadAllData}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 hover:bg-cyan-500/30 transition-colors"
          >
            <Refresh className="w-4 h-4" />
            刷新
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 flex items-center gap-2">
            <Warning className="w-5 h-5" />
            {error}
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-1 mb-6 border-b border-white/10">
          {tabs.map((t, i) => (
            <button
              key={i}
              onClick={() => setActiveTab(i)}
              className={`flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors border-b-2 ${
                activeTab === i
                  ? 'text-cyan-400 border-cyan-400'
                  : 'text-slate-400 border-transparent hover:text-white'
              }`}
            >
              <t.icon className="w-4 h-4" />
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab: Overview */}
        {activeTab === 0 && globalStats && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {[
                { title: '总经验数', value: globalStats.total_experiences, sub: `累计使用 ${globalStats.total_usage} 次`, icon: FileBarChart, color: 'text-cyan-400' },
                { title: '整体成功率', value: fmtPct(globalStats.overall_success_rate, 1), sub: '所有经验平均成功率', icon: TrendingUp, color: 'text-green-400' },
                { title: '有效经验', value: globalStats.effective_count, sub: '成功率 > 70%', icon: CheckCircle, color: 'text-green-400' },
                { title: '待处理经验', value: globalStats.ineffective_count + globalStats.needs_review_count, sub: `${globalStats.ineffective_count} 无效 | ${globalStats.needs_review_count} 待审核`, icon: Warning, color: 'text-amber-400' },
              ].map((card, i) => (
                <div key={i} className="bg-slate-900/50 border border-white/10 rounded-xl p-4 hover:border-cyan-500/30 transition-colors">
                  <div className="flex justify-between items-start">
                    <div>
                      <p className="text-sm text-slate-400">{card.title}</p>
                      <p className="text-2xl font-bold text-white mt-1">{card.value}</p>
                      <p className="text-xs text-slate-500 mt-1">{card.sub}</p>
                    </div>
                    <card.icon className={`w-6 h-6 ${card.color}`} />
                  </div>
                </div>
              ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="bg-slate-900/50 border border-white/10 rounded-xl p-4">
                <h3 className="text-lg font-semibold text-white mb-4">经验效果分布</h3>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={[
                          { name: '有效', value: globalStats.effective_count },
                          { name: '无效', value: globalStats.ineffective_count },
                          { name: '待审核', value: globalStats.needs_review_count },
                        ]}
                        cx="50%"
                        cy="50%"
                        outerRadius={80}
                        dataKey="value"
                        label
                      >
                        {[
                          globalStats.effective_count,
                          globalStats.ineffective_count,
                          globalStats.needs_review_count,
                        ].map((_, index) => (
                          <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <RechartsTooltip />
                      <Legend />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="bg-slate-900/50 border border-white/10 rounded-xl p-4">
                <h3 className="text-lg font-semibold text-white mb-4">平均贡献分</h3>
                <div className="flex items-center justify-center h-64">
                  <div className="text-center">
                    <p className="text-5xl font-bold text-cyan-400">
                      {fmtNum(globalStats.avg_contribution_score, 2)}
                    </p>
                    <p className="text-slate-400 mt-2">基于成功率、使用频率、满意度加权计算</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tab: AB Test */}
        {activeTab === 1 && (
          <div className="space-y-6">
            {!abTestMetrics ? (
              <div className="p-4 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400 flex items-center gap-2">
                <Info className="w-5 h-5" />
                暂无A/B测试数据，系统需要至少10个任务样本才能生成对比报告
              </div>
            ) : (
              <>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="bg-slate-900/50 border border-white/10 rounded-xl p-4">
                    <p className="text-sm text-slate-400">成功率提升</p>
                    <p className={`text-2xl font-bold ${abTestMetrics.success_rate_lift >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {fmtPct(abTestMetrics.success_rate_lift, 1)}
                    </p>
                  </div>
                  <div className="bg-slate-900/50 border border-white/10 rounded-xl p-4">
                    <p className="text-sm text-slate-400">时间改善</p>
                    <p className={`text-2xl font-bold ${abTestMetrics.time_improvement_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {fmtPct(abTestMetrics.time_improvement_pct, 1)}
                    </p>
                  </div>
                  <div className="bg-slate-900/50 border border-white/10 rounded-xl p-4">
                    <p className="text-sm text-slate-400">满意度提升</p>
                    <p className={`text-2xl font-bold ${abTestMetrics.satisfaction_lift >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {fmtPct(abTestMetrics.satisfaction_lift, 1)}
                    </p>
                  </div>
                </div>

                <div className="bg-slate-900/50 border border-white/10 rounded-xl p-4">
                  <h3 className="text-lg font-semibold text-white mb-4">实验组 vs 对照组成功率</h3>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={[
                        { name: '实验组', value: abTestMetrics.treatment_success_rate * 100 },
                        { name: '对照组', value: abTestMetrics.control_success_rate * 100 },
                      ]}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="name" stroke="#94a3b8" />
                        <YAxis stroke="#94a3b8" />
                        <RechartsTooltip />
                        <Bar dataKey="value" fill="#06b6d4" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* Tab: Leaderboard */}
        {activeTab === 2 && (
          <div className="bg-slate-900/50 border border-white/10 rounded-xl overflow-hidden">
            <table className="w-full text-sm text-left">
              <thead className="bg-slate-800/50 text-slate-300">
                <tr>
                  <th className="px-4 py-3">经验ID</th>
                  <th className="px-4 py-3">使用次数</th>
                  <th className="px-4 py-3">成功率</th>
                  <th className="px-4 py-3">满意度</th>
                  <th className="px-4 py-3">贡献分</th>
                  <th className="px-4 py-3">状态</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.map((item) => (
                  <tr key={item.experience_id} className="border-t border-white/5 hover:bg-white/5">
                    <td className="px-4 py-3 font-mono text-slate-400">{item.experience_id.slice(0, 12)}...</td>
                    <td className="px-4 py-3">{item.usage_count}</td>
                    <td className="px-4 py-3">{fmtPct(item.success_rate, 1)}</td>
                    <td className="px-4 py-3">{fmtNum(item.avg_satisfaction, 2)}</td>
                    <td className="px-4 py-3 text-cyan-400">{fmtNum(item.contribution_score, 2)}</td>
                    <td className="px-4 py-3">
                      {item.is_effective ? <StatusBadge status="effective" /> :
                       item.is_ineffective ? <StatusBadge status="ineffective" /> :
                       <StatusBadge status="review" />}
                    </td>
                  </tr>
                ))}
                {leaderboard.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-slate-500">暂无数据</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Tab: Purge */}
        {activeTab === 3 && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-white">淘汰候选列表</h3>
              <button
                onClick={handleRunPurgeScan}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-500/20 text-amber-400 border border-amber-500/30 hover:bg-amber-500/30 transition-colors"
              >
                <Refresh className="w-4 h-4" />
                运行扫描
              </button>
            </div>
            <div className="bg-slate-900/50 border border-white/10 rounded-xl overflow-hidden">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-800/50 text-slate-300">
                  <tr>
                    <th className="px-4 py-3">经验ID</th>
                    <th className="px-4 py-3">原因</th>
                    <th className="px-4 py-3">成功率</th>
                    <th className="px-4 py-3">使用次数</th>
                    <th className="px-4 py-3">推荐操作</th>
                    <th className="px-4 py-3">优先级</th>
                  </tr>
                </thead>
                <tbody>
                  {purgeCandidates.map((c) => (
                    <tr key={c.experience_id} className="border-t border-white/5 hover:bg-white/5">
                      <td className="px-4 py-3 font-mono text-slate-400">{c.experience_id.slice(0, 12)}...</td>
                      <td className="px-4 py-3">{c.reason}</td>
                      <td className="px-4 py-3">{fmtPct(c.success_rate, 1)}</td>
                      <td className="px-4 py-3">{c.usage_count}</td>
                      <td className="px-4 py-3">{c.recommended_action}</td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          c.priority >= 3 ? 'bg-red-500/20 text-red-400' :
                          c.priority >= 2 ? 'bg-amber-500/20 text-amber-400' :
                          'bg-blue-500/20 text-blue-400'
                        }`}>
                          P{c.priority}
                        </span>
                      </td>
                    </tr>
                  ))}
                  {purgeCandidates.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-8 text-center text-slate-500">暂无淘汰候选</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
