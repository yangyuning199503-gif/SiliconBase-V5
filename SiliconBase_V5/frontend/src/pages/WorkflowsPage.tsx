import { useState, useEffect, useCallback } from 'react';
import { Play, Trash2, RefreshCw } from 'lucide-react';
import { fetchAPI } from '../utils/api/core';
import { PageLayout } from '../components/ui/PageLayout';
import { Loading } from '../components/ui/Loading';

interface Workflow {
  id: string;
  name: string;
  description: string;
  steps: number;
  created_at: string;
}

export function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchAPI<{ success: boolean; workflows?: Workflow[] }>('/api/tasks/workflows');
      if (res.success) setWorkflows(res.workflows || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    document.title = '工作流 - SiliconBase V5';
  }, [load]);

  const execute = async (id: string) => {
    await fetchAPI(`/api/tasks/workflows/${id}/execute`, { method: 'POST' });
    alert('工作流已触发执行');
  };

  const remove = async (id: string) => {
    if (!confirm('确定删除该工作流？')) return;
    await fetchAPI(`/api/tasks/workflows/${id}`, { method: 'DELETE' });
    await load();
  };

  return (
    <PageLayout
      title="工作流"
      subtitle="查看与执行自动化工作流"
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
            <div className="bg-slate-900/50 border border-white/10 rounded-xl overflow-hidden">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-800/50 text-slate-300">
                  <tr>
                    <th className="px-4 py-3">名称</th>
                    <th className="px-4 py-3">描述</th>
                    <th className="px-4 py-3">步骤数</th>
                    <th className="px-4 py-3">创建时间</th>
                    <th className="px-4 py-3">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {workflows.map((w) => (
                    <tr key={w.id} className="border-t border-white/5 hover:bg-white/5">
                      <td className="px-4 py-3 font-medium text-white">{w.name}</td>
                      <td className="px-4 py-3 text-slate-400">{w.description}</td>
                      <td className="px-4 py-3">{w.steps}</td>
                      <td className="px-4 py-3 text-slate-400">{new Date(w.created_at).toLocaleString()}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => execute(w.id)}
                            className="p-1.5 rounded hover:bg-cyan-500/20 text-cyan-400"
                            title="执行"
                          >
                            <Play className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => remove(w.id)}
                            className="p-1.5 rounded hover:bg-red-500/20 text-red-400"
                            title="删除"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {workflows.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-4 py-8 text-center text-slate-500">暂无工作流</td>
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

export default WorkflowsPage;
