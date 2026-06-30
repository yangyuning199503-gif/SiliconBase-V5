import { useState, useEffect, useCallback } from "react";
import { ToggleLeft, ToggleRight, RefreshCw, Loader2, AlertTriangle } from "lucide-react";
import { fetchAPI } from "../utils/api/core";
import { featuresAPI } from "../utils/api/features";
import { PageLayout } from "../components/ui/PageLayout";
import { Loading } from "../components/ui/Loading";

interface Dependency {
  name: string;
  status: string;
  description?: string;
}

interface SubFeature {
  id: string;
  name: string;
  enabled: boolean;
  available: boolean;
  description?: string;
  config_path?: string;
}

interface Feature {
  id: string;
  name: string;
  description: string;
  category: string;
  enabled: boolean;
  available: boolean;
  state: string;
  configurable: boolean;
  requires_restart: boolean;
  dependencies: Dependency[];
  sub_features: SubFeature[];
  error_message?: string;
}

interface FeatureSummary {
  total: number;
  enabled: number;
  available: number;
}

interface FeaturesResponse {
  features: Feature[];
  summary: FeatureSummary;
}

export function FeaturesPage() {
  const [data, setData] = useState<FeaturesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState<string | null>(null);
  const [subToggling, setSubToggling] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchAPI<FeaturesResponse>("/api/features");
      setData({
        features: res.features || [],
        summary: res.summary || { total: 0, enabled: 0, available: 0 },
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    document.title = "功能开关 - SiliconBase V5";
  }, [load]);

  const toggleFeature = async (featureId: string, enable: boolean) => {
    setToggling(featureId);
    setError(null);
    try {
      const res = await fetchAPI<{ success: boolean; message?: string; requires_restart?: boolean }>(
        `/api/features/${featureId}/${enable ? "enable" : "disable"}`,
        { method: "POST" },
      );
      if (!res.success) {
        setError(res.message || `${enable ? "启用" : "禁用"}失败`);
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : `${enable ? "启用" : "禁用"}失败`);
    } finally {
      setToggling(null);
    }
  };

  const toggleSubFeature = async (
    feature: Feature,
    sub: SubFeature,
    enable: boolean
  ) => {
    if (!sub.config_path) return;
    const toggleId = `${feature.id}.${sub.id}`;
    setSubToggling(toggleId);
    setError(null);
    try {
      const res = await featuresAPI.toggleSubFeature(
        feature.id,
        sub.id,
        sub.config_path,
        enable
      );
      if (!res.success) {
        setError(res.message || `${enable ? "启用" : "禁用"}失败`);
      }
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : `${enable ? "启用" : "禁用"}失败`);
    } finally {
      setSubToggling(null);
    }
  };

  const grouped = (data?.features || []).reduce<Record<string, Feature[]>>(
    (acc, f) => {
      acc[f.category] = acc[f.category] || [];
      acc[f.category].push(f);
      return acc;
    },
    {},
  );

  const categoryNames: Record<string, string> = {
    core: "核心功能",
    perception: "感知功能",
    cognition: "认知功能",
    memory: "记忆功能",
    consciousness: "意识功能",
    extension: "扩展功能",
  };

  const missingDeps = (feature: Feature) =>
    feature.dependencies?.filter((d) => d.status !== "available") || [];

  return (
    <PageLayout
      title="功能开关"
      subtitle="管理系统功能开关与依赖状态"
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
            {error && (
              <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
                {error}
              </div>
            )}

            {data?.summary && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                <div className="bg-slate-900/50 border border-white/10 rounded-xl p-4">
                  <p className="text-sm text-slate-400">总功能</p>
                  <p className="text-2xl font-bold text-white">{data.summary.total}</p>
                </div>
                <div className="bg-slate-900/50 border border-white/10 rounded-xl p-4">
                  <p className="text-sm text-slate-400">已启用</p>
                  <p className="text-2xl font-bold text-green-400">{data.summary.enabled}</p>
                </div>
                <div className="bg-slate-900/50 border border-white/10 rounded-xl p-4">
                  <p className="text-sm text-slate-400">可用</p>
                  <p className="text-2xl font-bold text-cyan-400">{data.summary.available}</p>
                </div>
              </div>
            )}

            <div className="space-y-6">
              {Object.entries(grouped).map(([category, items]) => (
                <div
                  key={category}
                  className="bg-slate-900/50 border border-white/10 rounded-xl p-4"
                >
                  <h2 className="text-lg font-semibold text-white mb-3">
                    {categoryNames[category] || category}
                  </h2>
                  <div className="space-y-2">
                    {items.map((feature) => {
                      const missing = missingDeps(feature);
                      const unavailable = !feature.available;
                      return (
                        <div
                          key={feature.id}
                          className={`flex items-start justify-between p-3 rounded-lg border ${
                            feature.enabled
                              ? "bg-cyan-500/5 border-cyan-500/20"
                              : "bg-white/5 border-white/5"
                          }`}
                        >
                          <div className="flex-1 min-w-0 mr-4">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-medium text-white">{feature.name}</span>
                              {unavailable && (
                                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-yellow-500/20 text-yellow-400 border border-yellow-500/30">
                                  <AlertTriangle className="w-3 h-3" />
                                  依赖未满足
                                </span>
                              )}
                              {feature.requires_restart && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] bg-orange-500/20 text-orange-400 border border-orange-500/30">
                                  需重启
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-slate-400 mt-0.5">{feature.description}</p>

                            {feature.error_message && (
                              <p className="text-xs text-red-400 mt-1">{feature.error_message}</p>
                            )}

                            {missing.length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-1">
                                {missing.map((dep) => (
                                  <span
                                    key={dep.name}
                                    className="text-[10px] px-1.5 py-0.5 rounded border bg-red-500/10 text-red-400 border-red-500/20"
                                    title={dep.description || dep.name}
                                  >
                                    {dep.name}: {dep.status}
                                  </span>
                                ))}
                              </div>
                            )}

                            {feature.sub_features && feature.sub_features.length > 0 && (
                              <div className="mt-2 pt-2 border-t border-white/5">
                                <p className="text-[10px] text-slate-500 mb-1">子功能</p>
                                <div className="flex flex-wrap gap-1.5">
                                  {feature.sub_features.map((sub) => {
                                    const toggleId = `${feature.id}.${sub.id}`;
                                    const canToggle = !!sub.config_path;
                                    const isToggling = subToggling === toggleId;
                                    return (
                                      <button
                                        key={sub.id}
                                        disabled={!canToggle || isToggling}
                                        onClick={() => toggleSubFeature(feature, sub, !sub.enabled)}
                                        className={`text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
                                          sub.enabled
                                            ? "bg-cyan-500/10 text-cyan-400 border-cyan-500/20"
                                            : "bg-white/5 text-slate-400 border-white/10"
                                        } ${
                                          canToggle && !isToggling
                                            ? "hover:bg-white/10 cursor-pointer"
                                            : "cursor-default opacity-70"
                                        }`}
                                        title={
                                          canToggle
                                            ? sub.description || sub.name
                                            : `${sub.name}（不可单独切换）`
                                        }
                                      >
                                        {isToggling ? (
                                          <span className="inline-block w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />
                                        ) : (
                                          <>{sub.enabled ? "●" : "○"} {sub.name}</>
                                        )}
                                      </button>
                                    );
                                  })}
                                </div>
                              </div>
                            )}
                          </div>
                          <button
                            disabled={toggling === feature.id}
                            onClick={() => toggleFeature(feature.id, !feature.enabled)}
                            className="shrink-0 disabled:opacity-40 mt-0.5"
                            title={unavailable ? "功能依赖未满足，但仍可切换开关" : undefined}
                          >
                            {toggling === feature.id ? (
                              <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
                            ) : feature.enabled ? (
                              <ToggleRight className="w-8 h-8 text-cyan-400" />
                            ) : (
                              <ToggleLeft className="w-8 h-8 text-slate-500" />
                            )}
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </PageLayout>
  );
}

export default FeaturesPage;
