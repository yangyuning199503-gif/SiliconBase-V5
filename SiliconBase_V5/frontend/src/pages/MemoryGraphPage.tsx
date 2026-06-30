import { useState, useEffect, useCallback, useRef } from 'react';
import { RefreshCw, User } from 'lucide-react';
import CytoscapeComponent from 'react-cytoscapejs';
import cytoscape from 'cytoscape';
import { memoryAPI } from '../utils/api';
import { PageLayout } from '../components/ui/PageLayout';
import { Loading } from '../components/ui/Loading';

interface GraphNode {
  id: string;
  type?: string;
  content?: string;
}

interface GraphEdge {
  source: string;
  target: string;
  type?: string;
}

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

const NODE_COLORS: Record<string, string> = {
  memory: '#06b6d4',
  concept: '#8b5cf6',
  event: '#f59e0b',
  task: '#10b981',
  default: '#64748b',
};

const styles: any[] = [
  {
    selector: 'node',
    style: {
      width: 40,
      height: 40,
      'background-color': '#64748b',
      label: 'data(label)',
      color: '#e2e8f0',
      'font-size': '10px',
      'text-valign': 'bottom',
      'text-halign': 'center',
      'text-margin-y': 6,
      'text-wrap': 'wrap',
      'text-max-width': '80px',
      'border-width': 2,
      'border-color': '#1e293b',
    },
  },
  {
    selector: 'edge',
    style: {
      width: 2,
      'line-color': '#475569',
      'target-arrow-color': '#475569',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      label: 'data(label)',
      color: '#94a3b8',
      'font-size': '9px',
      'text-background-color': '#0f172a',
      'text-background-opacity': 0.8,
      'text-background-padding': '2px',
    },
  },
  {
    selector: ':selected',
    style: {
      'border-width': 4,
      'border-color': '#22d3ee',
      'line-color': '#22d3ee',
      'target-arrow-color': '#22d3ee',
    },
  },
];

function buildElements(data: GraphData): any[] {
  const nodes: cytoscape.ElementDefinition[] = data.nodes.map((n) => {
    const label = n.content
      ? n.content.length > 12
        ? n.content.slice(0, 12) + '...'
        : n.content
      : n.id.slice(0, 12);
    return {
      data: {
        id: n.id,
        label,
        type: n.type || 'default',
        content: n.content || '',
      },
      classes: n.type || 'default',
    };
  });

  const nodeIds = new Set(data.nodes.map((n) => n.id));
  const edges: cytoscape.ElementDefinition[] = data.edges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map((e, idx) => ({
      data: {
        id: `e-${idx}`,
        source: e.source,
        target: e.target,
        label: e.type || '',
      },
    }));

  return [...nodes, ...edges];
}

export function MemoryGraphPage() {
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [userId, setUserId] = useState('default');
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await memoryAPI.getGraphVisualization({
        user_id: userId,
        depth: 2,
        limit: 100,
      });
      if (res && (res.nodes || res.edges)) {
        setData({
          nodes: (res.nodes as GraphNode[]) || [],
          edges: (res.edges as GraphEdge[]) || [],
        });
      }
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    load();
    document.title = '记忆图谱 - SiliconBase V5';
  }, [load]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !data) return;

    // 按类型着色
    cy.nodes().forEach((node) => {
      const type = node.data('type') || 'default';
      node.style('background-color', NODE_COLORS[type] || NODE_COLORS.default);
    });

    const layout = cy.layout({
      name: 'cose',
      padding: 20,
      nodeOverlap: 20,
      refresh: 20,
      fit: true,
      randomize: true,
      componentSpacing: 100,
      nodeRepulsion: 400000,
      edgeElasticity: 100,
      nestingFactor: 5,
      gravity: 80,
      numIter: 1000,
      initialTemp: 200,
      coolingFactor: 0.95,
      minTemp: 1.0,
    });
    layout.run();

    const onTap = (evt: cytoscape.EventObject) => {
      const node = evt.target;
      if (node.isNode && node.isNode()) {
        setSelected({ id: node.id(), type: node.data('type'), content: node.data('content') });
      }
    };
    cy.on('tap', 'node', onTap);

    return () => {
      cy.off('tap', 'node', onTap);
    };
  }, [data]);

  return (
    <PageLayout
      title="记忆图谱"
      subtitle="可视化记忆节点与关联关系"
      actions={
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 bg-slate-900/50 border border-white/10 rounded-lg px-3 py-2">
            <User className="w-4 h-4 text-slate-400" />
            <input
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              className="bg-transparent text-sm text-white outline-none w-32"
              placeholder="用户ID"
            />
          </div>
          <button
            onClick={load}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 hover:bg-cyan-500/30"
          >
            <RefreshCw className="w-4 h-4" />
            刷新
          </button>
        </div>
      }
    >
      <div className="h-full p-6 flex flex-col">
        <div className="flex-1 bg-slate-900/50 border border-white/10 rounded-xl p-4 overflow-hidden relative">
          {loading ? (
            <Loading text="加载图谱数据..." />
          ) : data && (data.nodes.length > 0 || data.edges.length > 0) ? (
            <>
              <CytoscapeComponent
                elements={buildElements(data)}
                style={{ width: '100%', height: '100%' }}
                stylesheet={styles}
                cy={(cy: cytoscape.Core) => {
                  cyRef.current = cy;
                }}
              />
              {selected && (
                <div className="absolute bottom-4 left-4 max-w-sm bg-slate-900/90 border border-white/10 rounded-xl p-4 shadow-2xl">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm font-medium text-white">节点详情</h3>
                    <button
                      onClick={() => setSelected(null)}
                      className="text-xs text-slate-400 hover:text-white"
                    >
                      关闭
                    </button>
                  </div>
                  <div className="text-xs text-slate-400 mb-1">ID: {selected.id}</div>
                  <div className="text-xs text-slate-400 mb-2">类型: {selected.type || 'default'}</div>
                  <div className="text-sm text-slate-200 whitespace-pre-wrap">
                    {selected.content || '无内容'}
                  </div>
                </div>
              )}
              <div className="absolute top-4 right-4 text-xs text-slate-400 bg-slate-900/80 px-3 py-1.5 rounded-lg border border-white/10">
                节点 {data.nodes.length} · 边 {data.edges.length}
              </div>
            </>
          ) : (
            <div className="h-full flex items-center justify-center text-slate-500">
              暂无图谱数据
            </div>
          )}
        </div>
      </div>
    </PageLayout>
  );
}

export default MemoryGraphPage;
