import { useState, useEffect, useCallback } from "react";
import { Archive, RefreshCw } from "lucide-react";
import { fetchAPI } from "../utils/api/core";
import { PageLayout } from "../components/ui/PageLayout";
import { Loading } from "../components/ui/Loading";

interface Reflection {
  id: string;
  type: string;
  lesson: string;
  created_at: string;
  is_archived: boolean;
}

export function ReflectionsPage() {
  const [reflections, setReflections] = useState<Reflection[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchAPI<{
        success: boolean;
        data: { reflections: Reflection[]; total: number };
      }>("/api/reflections");
      if (res.success) setReflections(res.data?.reflections || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    document.title = "反思管理 - SiliconBase V5";
  }, [load]);

  const archive = async (id: string) => {
    await fetchAPI(`/api/reflections/${id}/archive`, { method: "POST" });
    await load();
  };

  return (
    <PageLayout
      title="反思管理"
      subtitle="查看与归档反思记录"
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
          <div className="max-w-5xl mx-auto">
            <div className="space-y-3">
              {reflections.map((r) => (
                <div
                  key={r.id}
                  className={`p-4 rounded-xl border ${
                    r.is_archived
                      ? "bg-slate-900/30 border-white/5"
                      : "bg-slate-900/50 border-white/10"
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-medium px-2 py-1 rounded bg-cyan-500/20 text-cyan-400 border border-cyan-500/30">
                      {r.type}
                    </span>
                    <span className="text-xs text-slate-500">
                      {new Date(r.created_at).toLocaleString()}
                    </span>
                  </div>
                  <p
                    className={`text-sm ${r.is_archived ? "text-slate-500 line-through" : "text-slate-200"}`}
                  >
                    {r.lesson}
                  </p>
                  {!r.is_archived && (
                    <div className="mt-3 flex justify-end">
                      <button
                        onClick={() => archive(r.id)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 text-slate-300 hover:bg-white/10 text-xs"
                      >
                        <Archive className="w-3.5 h-3.5" />
                        归档
                      </button>
                    </div>
                  )}
                </div>
              ))}
              {reflections.length === 0 && (
                <div className="text-center text-slate-500 py-12">
                  暂无反思记录
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </PageLayout>
  );
}

export default ReflectionsPage;
