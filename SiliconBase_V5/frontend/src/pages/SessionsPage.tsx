import { useState, useEffect, useCallback } from "react";
import { Trash2, RefreshCw } from "lucide-react";
import { fetchAPI } from "../utils/api/core";
import { PageLayout } from "../components/ui/PageLayout";
import { Loading } from "../components/ui/Loading";

interface Session {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export function SessionsPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchAPI<{
        items: Session[];
        total: number;
        limit: number;
        offset: number;
      }>("/api/sessions");
      setSessions(res.items || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    document.title = "会话管理 - SiliconBase V5";
  }, [load]);

  const remove = async (id: string) => {
    if (!confirm("确定删除该会话？")) return;
    await fetchAPI(`/api/sessions/${id}`, { method: "DELETE" });
    await load();
  };

  return (
    <PageLayout
      title="会话管理"
      subtitle="管理历史会话记录"
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
            <div className="bg-slate-900/50 border border-white/10 rounded-xl overflow-hidden">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-800/50 text-slate-300">
                  <tr>
                    <th className="px-4 py-3">标题</th>
                    <th className="px-4 py-3">消息数</th>
                    <th className="px-4 py-3">创建时间</th>
                    <th className="px-4 py-3">更新时间</th>
                    <th className="px-4 py-3">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((s) => (
                    <tr
                      key={s.id}
                      className="border-t border-white/5 hover:bg-white/5"
                    >
                      <td className="px-4 py-3 font-medium text-white">
                        {s.title || "未命名会话"}
                      </td>
                      <td className="px-4 py-3">{s.message_count}</td>
                      <td className="px-4 py-3 text-slate-400">
                        {new Date(s.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-slate-400">
                        {new Date(s.updated_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => remove(s.id)}
                          className="p-1.5 rounded hover:bg-red-500/20 text-red-400"
                          title="删除"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {sessions.length === 0 && (
                    <tr>
                      <td
                        colSpan={5}
                        className="px-4 py-8 text-center text-slate-500"
                      >
                        暂无会话
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </PageLayout>
  );
}

export default SessionsPage;
