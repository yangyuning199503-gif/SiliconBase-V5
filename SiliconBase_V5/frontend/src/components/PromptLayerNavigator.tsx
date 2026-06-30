/**
 * 提示词层级导航组件 - 游戏化L1/L2/L3层级切换
 * 
 * L1: 概览层 - 工具分类列表
 * L2: 工具手册层 - 分类下的工具列表
 * L3: 工具详情层 - 具体工具参数
 * 
 * 【大纲规则3】切换时语音播报"正在查询中，请稍后"
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Layers,
  BookOpen,
  Wrench,
  ChevronRight,
  ChevronLeft,
  Home,
  Search,
  Loader2
} from 'lucide-react';
import { authFetch } from '../utils/api';

// 层级类型
export type PromptLayer = 'L1_OVERVIEW' | 'L2_MANUAL' | 'L3_TOOL_DETAIL';

// 工具分类
interface ToolCategory {
  name: string;
  description: string;
  icon: string;
  count: number;
}

// 工具简要信息
interface ToolBrief {
  id: string;
  name: string;
  description: string;
}

// 工具详情
interface ToolDetail {
  id: string;
  name: string;
  description: string;
  parameters: Record<string, any>;
  required: string[];
  example?: Record<string, any>;
  category?: string;
  rarity?: string;
}

// 组件属性
interface PromptLayerNavigatorProps {
  onLayerChange?: (layer: PromptLayer, data?: any) => void;
  initialLayer?: PromptLayer;
  className?: string;
}

// 分类图标映射（保留供未来使用）
// const CATEGORY_ICONS: Record<string, any> = {
//   '📋': ClipboardList,
//   '📁': Package,
//   '🔧': Terminal,
//   '🌐': Globe,
//   '📊': Database,
//   '🎵': Image,
//   '💻': Code,
//   '🔐': Shield,
// };

export function PromptLayerNavigator({ 
  onLayerChange, 
  initialLayer = 'L1_OVERVIEW',
  className = '' 
}: PromptLayerNavigatorProps) {
  // 组件挂载状态追踪 - 防止异步操作更新已卸载组件
  const isMountedRef = useRef(true);
  const abortControllerRef = useRef<AbortController | null>(null);
  
  // 状态
  const [currentLayer, setCurrentLayer] = useState<PromptLayer>(initialLayer);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // L1状态
  const [categories, setCategories] = useState<ToolCategory[]>([]);
  
  // L2状态
  const [, setSelectedCategory] = useState<string | null>(null);
  const [tools, setTools] = useState<Record<string, ToolBrief[]>>({});
  const [searchQuery, setSearchQuery] = useState('');
  
  // L3状态
  const [selectedTool, setSelectedTool] = useState<ToolDetail | null>(null);
  
  // 清理函数
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);
  
  // 播放语音播报（大纲规则3）
  const playVoiceAnnouncement = useCallback(() => {
    // 仅在客户端环境执行
    if (typeof window === 'undefined') return;
    
    // 尝试调用后端语音API或前端语音合成
    if ('speechSynthesis' in window) {
      try {
        const utterance = new SpeechSynthesisUtterance('正在查询中，请稍后');
        utterance.lang = 'zh-CN';
        utterance.rate = 1;
        window.speechSynthesis.speak(utterance);
      } catch (error) {
        console.error('[PromptLayerNavigator] 语音合成失败:', error);
      }
    }
    
    // 同时调用后端语音播报API
    authFetch('/api/voice/announce', {
      method: 'POST',
      body: JSON.stringify({ text: '正在查询中，请稍后', priority: 'normal' })
    }).catch(() => {
      // 后端语音失败不阻塞UI
    });
  }, []);

  // 加载L1层数据
  const loadLayer1 = useCallback(async () => {
    setLoading(true);
    setError(null);
    playVoiceAnnouncement();
    
    try {
      const response = await authFetch('/api/prompt/layer/l1');
      if (!response.ok) {
        throw new Error(`HTTP错误: ${response.status} ${response.statusText}`);
      }
      
      let result;
      try {
        result = await response.json();
      } catch (parseErr) {
        throw new Error('响应格式错误：无法解析JSON数据');
      }
      
      // 检查组件是否仍然挂载
      if (!isMountedRef.current) return;
      
      if (result?.success) {
        setCategories(result.data?.categories || []);
        setCurrentLayer('L1_OVERVIEW');
        onLayerChange?.('L1_OVERVIEW', result.data);
      } else {
        throw new Error(result?.message || '加载失败');
      }
    } catch (err) {
      if (isMountedRef.current) {
        setError(err instanceof Error ? err.message : '加载失败');
      }
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }
    }
  }, [onLayerChange, playVoiceAnnouncement]);

  // 加载L2层数据
  const loadLayer2 = useCallback(async (category?: string) => {
    setLoading(true);
    setError(null);
    playVoiceAnnouncement();
    
    try {
      const url = category 
        ? `/api/prompt/layer/l2?category=${encodeURIComponent(category)}`
        : '/api/prompt/layer/l2';
      
      const response = await authFetch(url);
      if (!response.ok) {
        throw new Error(`HTTP错误: ${response.status} ${response.statusText}`);
      }
      
      let result;
      try {
        result = await response.json();
      } catch (parseErr) {
        throw new Error('响应格式错误：无法解析JSON数据');
      }
      
      // 检查组件是否仍然挂载
      if (!isMountedRef.current) return;
      
      if (result?.success) {
        setTools(result.data?.tools_by_category || {});
        setSelectedCategory(category || null);
        setCurrentLayer('L2_MANUAL');
        onLayerChange?.('L2_MANUAL', result.data);
      } else {
        throw new Error(result?.message || '加载失败');
      }
    } catch (err) {
      if (isMountedRef.current) {
        setError(err instanceof Error ? err.message : '加载失败');
      }
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }
    }
  }, [onLayerChange, playVoiceAnnouncement]);

  // 加载L3层数据
  const loadLayer3 = useCallback(async (toolId: string) => {
    setLoading(true);
    setError(null);
    playVoiceAnnouncement();
    
    try {
      const response = await authFetch(`/api/prompt/layer/l3/${encodeURIComponent(toolId)}`);
      if (!response.ok) {
        throw new Error(`HTTP错误: ${response.status} ${response.statusText}`);
      }
      
      let result;
      try {
        result = await response.json();
      } catch (parseErr) {
        throw new Error('响应格式错误：无法解析JSON数据');
      }
      
      // 检查组件是否仍然挂载
      if (!isMountedRef.current) return;
      
      if (result?.success) {
        setSelectedTool(result.data?.tool || null);
        setCurrentLayer('L3_TOOL_DETAIL');
        onLayerChange?.('L3_TOOL_DETAIL', result.data);
      } else {
        throw new Error(result?.message || '加载失败');
      }
    } catch (err) {
      if (isMountedRef.current) {
        setError(err instanceof Error ? err.message : '加载失败');
      }
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }
    }
  }, [onLayerChange, playVoiceAnnouncement]);

  // 切换层级
  const switchLayer = useCallback(async (command: string) => {
    setLoading(true);
    setError(null);
    playVoiceAnnouncement();
    
    try {
      const response = await authFetch('/api/prompt/layer/switch', {
        method: 'POST',
        body: JSON.stringify({ command })
      });
      
      if (!response.ok) {
        throw new Error(`HTTP错误: ${response.status} ${response.statusText}`);
      }
      
      let result;
      try {
        result = await response.json();
      } catch (parseErr) {
        throw new Error('响应格式错误：无法解析JSON数据');
      }
      
      // 检查组件是否仍然挂载
      if (!isMountedRef.current) return;
      
      if (result?.success) {
        const newLayer = result.layer as PromptLayer;
        setCurrentLayer(newLayer);
        
        // 同步更新各层状态
        if (newLayer === 'L1_OVERVIEW') {
          await loadLayer1();
        } else if (newLayer === 'L2_MANUAL') {
          await loadLayer2();
        } else if (newLayer === 'L3_TOOL_DETAIL' && result.data?.current_tool) {
          await loadLayer3(result.data.current_tool);
        }
        
        // 再次检查挂载状态后再调用回调
        if (isMountedRef.current) {
          onLayerChange?.(newLayer, result.data);
        }
      } else {
        throw new Error(result?.message || '切换失败');
      }
    } catch (err) {
      if (isMountedRef.current) {
        setError(err instanceof Error ? err.message : '切换失败');
      }
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }
    }
  }, [loadLayer1, loadLayer2, loadLayer3, onLayerChange, playVoiceAnnouncement]);

  // 初始加载
  useEffect(() => {
    loadLayer1();
  }, []);

  // 过滤工具（搜索功能）
  const filteredTools = Object.entries(tools).reduce((acc, [cat, toolList]) => {
    const filtered = toolList.filter(tool => 
      tool.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      tool.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      tool.description.toLowerCase().includes(searchQuery.toLowerCase())
    );
    if (filtered.length > 0) {
      acc[cat] = filtered;
    }
    return acc;
  }, {} as Record<string, ToolBrief[]>);

  // 获取分类图标组件（保留供未来使用）
  // const getCategoryIcon = (iconStr: string) => {
  //   const IconComponent = CATEGORY_ICONS[iconStr] || Package;
  //   return <IconComponent className="w-5 h-5" />;
  // };

  // 渲染加载状态 - 使用唯一key防止React DOM冲突
  if (loading) {
    return (
      <div key="prompt-layer-loading" className={`flex items-center justify-center p-8 ${className}`}>
        <div key="prompt-layer-loading-inner" className="text-center">
          <Loader2 key="prompt-layer-loader" className="w-8 h-8 text-sb-cyan animate-spin mx-auto" />
          <p key="prompt-layer-loading-text" className="mt-2 text-sb-text-secondary">正在查询中，请稍后...</p>
        </div>
      </div>
    );
  }

  // 渲染错误状态
  if (error) {
    return (
      <div className={`p-4 bg-red-500/10 border border-red-500/30 rounded-lg ${className}`}>
        <p className="text-red-400">{error}</p>
        <button 
          onClick={loadLayer1}
          className="mt-2 text-sm text-sb-cyan hover:underline"
        >
          重新加载
        </button>
      </div>
    );
  }

  return (
    <div className={`bg-sb-bg-secondary border border-white/10 rounded-xl overflow-hidden ${className}`}>
      {/* 层级导航头部 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-white/5">
        <div className="flex items-center gap-2">
          <Layers className="w-5 h-5 text-sb-cyan" />
          <span className="font-medium">提示词层级导航</span>
        </div>
        
        {/* 面包屑导航 */}
        <div className="flex items-center gap-2 text-sm">
          <button
            onClick={() => switchLayer('首页')}
            className={`flex items-center gap-1 px-2 py-1 rounded transition-colors ${
              currentLayer === 'L1_OVERVIEW' 
                ? 'text-sb-cyan bg-sb-cyan/10' 
                : 'text-sb-text-secondary hover:text-sb-text-primary'
            }`}
          >
            <Home className="w-4 h-4" />
            <span>L1概览</span>
          </button>
          
          <ChevronRight className="w-4 h-4 text-sb-text-secondary" />
          
          <button
            onClick={() => switchLayer('手册')}
            className={`flex items-center gap-1 px-2 py-1 rounded transition-colors ${
              currentLayer === 'L2_MANUAL' 
                ? 'text-sb-cyan bg-sb-cyan/10' 
                : 'text-sb-text-secondary hover:text-sb-text-primary'
            }`}
          >
            <BookOpen className="w-4 h-4" />
            <span>L2手册</span>
          </button>
          
          {currentLayer === 'L3_TOOL_DETAIL' && selectedTool && (
            <>
              <ChevronRight className="w-4 h-4 text-sb-text-secondary" />
              <span className="flex items-center gap-1 px-2 py-1 text-sb-cyan bg-sb-cyan/10 rounded">
                <Wrench className="w-4 h-4" />
                <span>L3详情</span>
              </span>
            </>
          )}
        </div>
      </div>

      {/* L1 概览层 */}
      {currentLayer === 'L1_OVERVIEW' && (
        <div className="p-4">
          <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
            <Home className="w-5 h-5 text-sb-cyan" />
            工具分类概览
          </h3>
          <p className="text-sm text-sb-text-secondary mb-4">
            共 {categories.length} 个分类，点击查看工具列表
          </p>
          
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {categories.map((cat) => (
              <button
                key={cat.name}
                onClick={() => loadLayer2(cat.name)}
                className="p-4 bg-white/5 border border-white/10 rounded-lg hover:bg-white/10 hover:border-sb-cyan/30 transition-all text-left group"
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xl">{cat.icon}</span>
                  <span className="font-medium group-hover:text-sb-cyan transition-colors">
                    {cat.name.replace(/^\s*\S+\s*/, '')}
                  </span>
                </div>
                <p className="text-xs text-sb-text-secondary line-clamp-2">
                  {cat.description}
                </p>
                <span className="inline-block mt-2 text-xs bg-sb-cyan/10 text-sb-cyan px-2 py-0.5 rounded">
                  {cat.count} 个工具
                </span>
              </button>
            ))}
          </div>
          
          <div className="mt-4 p-3 bg-sb-cyan/5 border border-sb-cyan/20 rounded-lg">
            <p className="text-xs text-sb-text-secondary">
              <span className="text-sb-cyan">💡 提示：</span>
              输入"手册"进入L2工具手册层，或直接输入工具名进入L3详情层
            </p>
          </div>
        </div>
      )}

      {/* L2 工具手册层 */}
      {currentLayer === 'L2_MANUAL' && (
        <div className="p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-sb-cyan" />
              工具列表
            </h3>
            
            {/* 搜索框 */}
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-sb-text-secondary" />
              <input
                type="text"
                placeholder="搜索工具..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-sm focus:outline-none focus:border-sb-cyan/50 w-48"
              />
            </div>
          </div>
          
          {/* 工具列表 */}
          <div className="space-y-4 max-h-[400px] overflow-y-auto">
            {Object.entries(filteredTools).map(([catName, toolList]) => (
              <div key={catName} className="bg-white/5 border border-white/10 rounded-lg p-3">
                <h4 className="font-medium text-sb-cyan mb-2 flex items-center gap-2">
                  <span>{catName.split(' ')[0]}</span>
                  <span>{catName.replace(/^\s*\S+\s*/, '')}</span>
                  <span className="text-xs text-sb-text-secondary">({toolList.length}个)</span>
                </h4>
                
                <div className="space-y-1">
                  {toolList.map((tool) => (
                    <button
                      key={tool.id}
                      onClick={() => loadLayer3(tool.id)}
                      className="w-full text-left p-2 rounded hover:bg-white/5 transition-colors group"
                    >
                      <div className="flex items-center justify-between">
                        <div>
                          <span className="font-mono text-sm text-sb-cyan group-hover:underline">
                            {tool.id}
                          </span>
                          <span className="ml-2 text-sm">{tool.name}</span>
                        </div>
                        <ChevronRight className="w-4 h-4 text-sb-text-secondary opacity-0 group-hover:opacity-100 transition-opacity" />
                      </div>
                      <p className="text-xs text-sb-text-secondary mt-1">
                        {tool.description}
                      </p>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
          
          {searchQuery && Object.keys(filteredTools).length === 0 && (
            <div className="text-center py-8 text-sb-text-secondary">
              未找到匹配的工具
            </div>
          )}
        </div>
      )}

      {/* L3 工具详情层 */}
      {currentLayer === 'L3_TOOL_DETAIL' && selectedTool && (
        <div className="p-4">
          <div className="flex items-center gap-2 mb-4">
            <button
              onClick={() => switchLayer('手册')}
              className="p-2 hover:bg-white/10 rounded-lg transition-colors"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>
            <h3 className="text-lg font-medium flex items-center gap-2">
              <Wrench className="w-5 h-5 text-sb-cyan" />
              工具详情
            </h3>
          </div>
          
          {/* 工具基本信息 */}
          <div className="bg-white/5 border border-white/10 rounded-lg p-4 mb-4">
            <div className="flex items-start justify-between">
              <div>
                <h4 className="text-xl font-medium text-sb-cyan">
                  {selectedTool.name}
                </h4>
                <code className="text-sm text-sb-text-secondary bg-black/30 px-2 py-0.5 rounded mt-1 inline-block">
                  {selectedTool.id}
                </code>
              </div>
              {selectedTool.rarity && (
                <span className="px-2 py-1 text-xs bg-sb-cyan/10 text-sb-cyan rounded">
                  {selectedTool.rarity}
                </span>
              )}
            </div>
            <p className="mt-3 text-sm">{selectedTool.description}</p>
          </div>
          
          {/* 参数列表 */}
          {selectedTool.parameters && Object.keys(selectedTool.parameters).length > 0 && (
            <div className="mb-4">
              <h5 className="font-medium mb-2 flex items-center gap-2">
                <span className="w-1.5 h-1.5 bg-sb-cyan rounded-full" />
                参数说明
              </h5>
              <div className="bg-white/5 border border-white/10 rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-white/5">
                    <tr>
                      <th className="px-3 py-2 text-left text-xs text-sb-text-secondary">参数名</th>
                      <th className="px-3 py-2 text-left text-xs text-sb-text-secondary">类型</th>
                      <th className="px-3 py-2 text-left text-xs text-sb-text-secondary">必需</th>
                      <th className="px-3 py-2 text-left text-xs text-sb-text-secondary">描述</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(selectedTool.parameters).map(([paramName, paramInfo]) => {
                      const info = typeof paramInfo === 'object' ? paramInfo : {};
                      const isRequired = selectedTool.required?.includes(paramName) || info.required;
                      return (
                        <tr key={paramName} className="border-t border-white/10">
                          <td className="px-3 py-2 font-mono text-sb-cyan">{paramName}</td>
                          <td className="px-3 py-2 text-xs">{info.type || 'any'}</td>
                          <td className="px-3 py-2">
                            {isRequired ? (
                              <span className="text-xs text-red-400">必填</span>
                            ) : (
                              <span className="text-xs text-sb-text-secondary">可选</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-xs text-sb-text-secondary">
                            {info.description || '-'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          
          {/* 使用示例 */}
          {selectedTool.example && (
            <div>
              <h5 className="font-medium mb-2 flex items-center gap-2">
                <span className="w-1.5 h-1.5 bg-sb-cyan rounded-full" />
                使用示例
              </h5>
              <pre className="bg-black/50 border border-white/10 rounded-lg p-3 overflow-x-auto">
                <code className="text-xs text-green-400">
                  {JSON.stringify(selectedTool.example, null, 2)}
                </code>
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default PromptLayerNavigator;
