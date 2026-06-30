import { useState, useEffect, useCallback } from "react";
import { TrendingUp, AlertTriangle, RefreshCw } from "lucide-react";
import { fetchAPI } from "../utils/api/core";
import { PageLayout } from "../components/ui/PageLayout";
import { Loading } from "../components/ui/Loading";

interface CostStatus {
  daily_budget: number;
  daily_used: number;
  monthly_budget: number;
  monthly_used: number;
  alert_level: "none" | "warning" | "critical";
}

interface CostStats {
  overall?: Record<string, any>;
  by_model: Array<{
    model: string;
    tokens: number;
    cost: number;
    requests?: number;
  }>;
  by_day: Array<{ date: string; cost: number; requests?: number }>;
  period?: { start: string; end: string };
}

export function CostsPage() {
  const [status, setStatus] = useState<CostStatus | null>(null);
  const [stats, setStats] = useState<CostStats | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [sRes, stRes] = await Promise.all([
        fetchAPI<CostStatus>("/api/cost/status"),
        fetchAPI<CostStats>("/api/cost/stats"),
      ]);
      setStatus(sRes ?? null);
      setStats(stRes ?? null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    document.title = "成本中心 - SiliconBase V5";
  }, [load]);

  return (
    <PageLayout
      title="成本中心"
      subtitle="监控每日与月度成本预算及使用情况"
      actions={
        <button
          onClick={load}
          className="flex items-center gap-2 px-3 py-2 rounded-lg bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 hover:bg-cyan-500/30"
        >
          <RefreshCw className="w-4 h-4" />
          刷新
        </button>
      }
    >
      {loading ? (
        <Loading />
      ) : (
        <div className="p-6">
          <div className="max-w-6xl mx-auto">
            {status && (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                {[
                  {
                    label: "日预算",
                    value: `¥${status.daily_budget.toFixed(2)}`,
                    color: "text-cyan-400",
                  },
                  {
                    label: "日已用",
                    value: `¥${status.daily_used.toFixed(2)}`,
                    color:
                      status.daily_used > status.daily_budget * 0.8
                        ? "text-red-400"
                        : "text-green-400",
                  },
                  {
                    label: "月预算",
                    value: `¥${status.monthly_budget.toFixed(2)}`,
                    color: "text-cyan-400",
                  },
                  {
                    label: "月已用",
                    value: `¥${status.monthly_used.toFixed(2)}`,
                    color:
                      status.monthly_used > status.monthly_budget * 0.8
                        ? "text-red-400"
                        : "text-green-400",
                  },
                ].map((item, i) => (
                  <div
                    key={i}
                    className="bg-slate-900/50 border border-white/10 rounded-xl p-4"
                  >
                    <p className="text-sm text-slate-400">{item.label}</p>
                    <p className={`text-2xl font-bold ${item.color}`}>
                      {item.value}
                    </p>
                  </div>
                ))}
              </div>
            )}

            {status && status.alert_level !== "none" && (
              <div
                className={`mb-6 p-4 rounded-lg border flex items-center gap-3 ${
                  status.alert_level === "critical"
                    ? "bg-red-500/10 border-red-500/30 text-red-400"
                    : "bg-amber-500/10 border-amber-500/30 text-amber-400"
                }`}
              >
                <AlertTriangle className="w-5 h-5" />
                <div>
                  <p className="font-medium">
                    预算{status.alert_level === "critical" ? "严重" : ""}告警
                  </p>
                  <p className="text-sm opacity-80">请及时关注成本使用情况</p>
                </div>
              </div>
            )}

            {stats && (
              <div className="bg-slate-900/50 border border-white/10 rounded-xl p-4">
                <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                  <TrendingUp className="w-5 h-5 text-cyan-400" />
                  按模型统计
                </h2>
                <table className="w-full text-sm text-left">
                  <thead className="bg-slate-800/50 text-slate-300">
                    <tr>
                      <th className="px-4 py-2">模型</th>
                      <th className="px-4 py-2">Token 数</th>
                      <th className="px-4 py-2">成本</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(stats.by_model || []).map((data) => (
                      <tr key={data.model} className="border-t border-white/5">
                        <td className="px-4 py-2">{data.model}</td>
                        <td className="px-4 py-2">
                          {(data.tokens || 0).toLocaleString()}
                        </td>
                        <td className="px-4 py-2">
                          ¥{(data.cost || 0).toFixed(4)}
                        </td>
                      </tr>
                    ))}
                    {(stats.by_model || []).length === 0 && (
                      <tr>
                        <td
                          colSpan={3}
                          className="px-4 py-6 text-center text-slate-500"
                        >
                          暂无数据
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </PageLayout>
  );
}

export default CostsPage;
