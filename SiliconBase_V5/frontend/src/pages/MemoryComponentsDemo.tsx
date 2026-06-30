/**
 * 记忆组件演示页面
 * 用于测试和展示 MemoryPanel、MemoryAwareness、MemoryCard 组件
 */
import { useState } from 'react';
import { motion } from 'framer-motion';
import { Brain, Sparkles, BookOpen, MessageSquare, ArrowLeft } from 'lucide-react';
import { MemoryPanel, MemoryAwareness, MemoryCard } from '../components/memory';
import { Memory } from '../utils/api/memory';

// 模拟记忆数据
const mockMemories: Memory[] = [
  {
    id: 'mem-1',
    layer: 'short',
    mem_type: 'chat',
    content: '用户询问如何提高编程效率，我建议使用快捷键和代码片段功能。',
    scene: '编程助手对话',
    rating: 4,
    created_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
    source: 'auto_save'
  },
  {
    id: 'mem-2',
    layer: 'medium',
    mem_type: 'experience',
    content: '用户偏好使用深色主题，对亮色敏感。在推荐工具时应优先考虑支持深色模式的选项。',
    scene: '用户偏好收集',
    rating: 5,
    created_at: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(),
    source: 'reflection'
  },
  {
    id: 'mem-3',
    layer: 'short',
    mem_type: 'internal_thought',
    content: '用户正在开发一个 React 项目，可能需要状态管理方案的建议。',
    scene: '上下文理解',
    rating: 3,
    created_at: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    source: 'ai'
  },
  {
    id: 'mem-4',
    layer: 'evolve',
    mem_type: 'optimization',
    content: '用户习惯在收到建议后询问具体实现步骤，应主动提供详细代码示例。',
    scene: '交互模式优化',
    rating: 5,
    created_at: new Date(Date.now() - 1000 * 60 * 60 * 24).toISOString(),
    source: 'evolution'
  },
  {
    id: 'mem-5',
    layer: 'short',
    mem_type: 'tool_execution',
    content: '执行了文件搜索工具，找到了用户项目中的 package.json 文件。',
    scene: '工具调用',
    rating: 4,
    created_at: new Date(Date.now() - 1000 * 60 * 10).toISOString(),
    source: 'auto_save'
  }
];

export default function MemoryComponentsDemo() {
  const [showPanel, setShowPanel] = useState(false);
  const [importantIds, setImportantIds] = useState<Set<string>>(new Set(['mem-2']));

  const handleToggleImportant = (id: string, important: boolean) => {
    setImportantIds(prev => {
      const next = new Set(prev);
      if (important) {
        next.add(id);
      } else {
        next.delete(id);
      }
      return next;
    });
  };

  const handleDelete = (id: string) => {
    alert(`删除记忆: ${id}`);
  };

  return (
    <div className="min-h-screen bg-sb-bg-primary p-8">
      {/* 头部导航 */}
      <div className="flex items-center gap-4 mb-8">
        <button
          onClick={() => window.history.back()}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-white/5 text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          返回
        </button>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <Brain className="w-7 h-7 text-purple-400" />
          记忆展示组件测试
        </h1>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* 左侧：组件展示 */}
        <div className="space-y-8">
          {/* MemoryAwareness 演示 */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-sb-bg-secondary rounded-2xl p-6 border border-white/10"
          >
            <h2 className="text-lg font-medium text-white mb-4 flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-cyan-400" />
              MemoryAwareness 组件
            </h2>
            
            <div className="space-y-4">
              <div className="p-4 bg-sb-bg-primary rounded-xl">
                <p className="text-sm text-slate-400 mb-3">多条记忆 + 高关联度</p>
                <MemoryAwareness
                  memoryCount={5}
                  memoryIds={['mem-1', 'mem-2', 'mem-3', 'mem-4', 'mem-5']}
                  relevanceScore={0.85}
                  memoryTypes={['context', 'context', 'experience', 'preference', 'reference']}
                  onClick={() => setShowPanel(true)}
                />
              </div>

              <div className="p-4 bg-sb-bg-primary rounded-xl">
                <p className="text-sm text-slate-400 mb-3">单条记忆</p>
                <MemoryAwareness
                  memoryCount={1}
                  memoryIds={['mem-1']}
                  relevanceScore={0.65}
                  memoryTypes={['context']}
                  onClick={() => setShowPanel(true)}
                />
              </div>

              <div className="p-4 bg-sb-bg-primary rounded-xl">
                <p className="text-sm text-slate-400 mb-3">无记忆（基础模式）</p>
                <MemoryAwareness
                  memoryCount={0}
                  onClick={() => setShowPanel(true)}
                />
              </div>

              <div className="p-4 bg-sb-bg-primary rounded-xl">
                <p className="text-sm text-slate-400 mb-3">大量记忆</p>
                <MemoryAwareness
                  memoryCount={15}
                  memoryIds={Array.from({ length: 15 }, (_, i) => `mem-${i}`)}
                  relevanceScore={0.72}
                  memoryTypes={['context', 'experience', 'preference']}
                  onClick={() => setShowPanel(true)}
                />
              </div>
            </div>
          </motion.div>

          {/* MemoryCard 演示 */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="bg-sb-bg-secondary rounded-2xl p-6 border border-white/10"
          >
            <h2 className="text-lg font-medium text-white mb-4 flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-emerald-400" />
              MemoryCard 组件
            </h2>
            
            <div className="space-y-4">
              <div>
                <p className="text-sm text-slate-400 mb-3">完整模式</p>
                <MemoryCard
                  memory={mockMemories[0]}
                  onToggleImportant={handleToggleImportant}
                  onDelete={handleDelete}
                  isImportant={importantIds.has(mockMemories[0].id)}
                />
              </div>

              <div>
                <p className="text-sm text-slate-400 mb-3">紧凑模式（侧边栏用）</p>
                <MemoryCard
                  memory={mockMemories[1]}
                  onToggleImportant={handleToggleImportant}
                  onDelete={handleDelete}
                  isImportant={importantIds.has(mockMemories[1].id)}
                  compact
                />
              </div>
            </div>
          </motion.div>
        </div>

        {/* 右侧：交互演示 */}
        <div className="space-y-8">
          {/* 模拟聊天场景 */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="bg-sb-bg-secondary rounded-2xl p-6 border border-white/10"
          >
            <h2 className="text-lg font-medium text-white mb-4 flex items-center gap-2">
              <MessageSquare className="w-5 h-5 text-amber-400" />
              聊天场景演示
            </h2>
            
            <div className="bg-sb-bg-primary rounded-xl p-4 space-y-4">
              {/* 用户消息 */}
              <div className="flex justify-end">
                <div className="max-w-[80%] bg-cyan-600/30 border border-cyan-500/40 rounded-2xl rounded-tr-sm p-4">
                  <p className="text-sm text-white">帮我优化一下这个 React 组件的性能</p>
                </div>
              </div>

              {/* AI 回复 */}
              <div className="flex justify-start">
                <div className="max-w-[80%]">
                  <div className="bg-gradient-to-br from-purple-600/25 to-pink-600/25 border border-purple-500/35 rounded-2xl rounded-tl-sm p-4">
                    <p className="text-sm text-white/90 leading-relaxed">
                      根据你之前的开发习惯，我建议从以下几个方面优化：
                    </p>
                    <ul className="mt-2 space-y-1 text-sm text-white/80 list-disc list-inside">
                      <li>使用 React.memo 避免不必要的重渲染</li>
                      <li>将大型列表拆分为虚拟列表</li>
                      <li>使用 useMemo 缓存计算结果</li>
                    </ul>
                  </div>
                  
                  {/* 记忆感知提示 */}
                  <div className="mt-2">
                    <MemoryAwareness
                      memoryCount={3}
                      relevanceScore={0.78}
                      memoryTypes={['experience', 'context', 'preference']}
                      onClick={() => setShowPanel(true)}
                    />
                  </div>
                </div>
              </div>
            </div>
          </motion.div>

          {/* MemoryPanel 控制 */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="bg-sb-bg-secondary rounded-2xl p-6 border border-white/10"
          >
            <h2 className="text-lg font-medium text-white mb-4 flex items-center gap-2">
              <Brain className="w-5 h-5 text-purple-400" />
              MemoryPanel 演示
            </h2>
            
            <div className="space-y-4">
              <p className="text-sm text-slate-400">
                MemoryPanel 是一个侧边栏组件，展示当前会话的所有记忆。
                点击按钮打开面板：
              </p>
              
              <button
                onClick={() => setShowPanel(true)}
                className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-purple-500 to-pink-500 text-white rounded-xl font-medium hover:from-purple-600 hover:to-pink-600 transition-all shadow-lg shadow-purple-500/20"
              >
                <Brain className="w-5 h-5" />
                打开记忆面板
              </button>

              <div className="p-4 bg-sb-bg-primary rounded-xl text-sm text-slate-400 space-y-2">
                <p>面板功能：</p>
                <ul className="list-disc list-inside space-y-1 ml-2">
                  <li>按时间倒序排列记忆</li>
                  <li>搜索记忆内容</li>
                  <li>按类型/重要/时间筛选</li>
                  <li>标记重要记忆</li>
                  <li>删除记忆</li>
                  <li>显示关联度分数</li>
                </ul>
              </div>
            </div>
          </motion.div>

          {/* 使用说明 */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.4 }}
            className="bg-sb-bg-secondary rounded-2xl p-6 border border-white/10"
          >
            <h2 className="text-lg font-medium text-white mb-4">集成说明</h2>
            
            <div className="space-y-3 text-sm">
              <div className="p-3 bg-sb-bg-primary rounded-lg">
                <p className="text-slate-400 mb-2">1. 导入组件：</p>
                <code className="text-cyan-400">
                  import {'{ MemoryPanel, MemoryAwareness }'} from '../components/memory';
                </code>
              </div>
              
              <div className="p-3 bg-sb-bg-primary rounded-lg">
                <p className="text-slate-400 mb-2">2. 使用 Hook：</p>
                <code className="text-cyan-400">
                  const {'{ renderMemoryAwareness, renderMemoryPanel }'} = useMemoryIntegration(sessionId);
                </code>
              </div>
              
              <div className="p-3 bg-sb-bg-primary rounded-lg">
                <p className="text-slate-400 mb-2">3. 查看详细文档：</p>
                <p className="text-slate-300">src/components/memory/README.md</p>
              </div>
            </div>
          </motion.div>
        </div>
      </div>

      {/* 记忆面板 */}
      <MemoryPanel
        sessionId="demo-session-123"
        isOpen={showPanel}
        onClose={() => setShowPanel(false)}
      />
    </div>
  );
}
