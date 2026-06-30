/**
 * 云端工具市场页面 - Cloud Tool Market
 * 提供浏览、搜索、下载、安装云端工具的功能
 * 
 * 功能：
 * 1. 浏览云端工具分类
 * 2. 搜索工具
 * 3. 查看工具详情和版本
 * 4. 下载安装工具
 * 5. 检查更新
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Cloud, Download, Search, Star, Package,
  CheckCircle, XCircle, RefreshCw,
  Grid, List, Trash2,
  Zap, Globe,
  Image, Database, Lock, Code,
  Terminal, Clock,
  Plus
} from 'lucide-react';
import { useNotifications } from '../hooks/useNotifications';
import { authFetch } from '../utils/api';
import { API_BASE_URL } from '../config/system';

// ============================================================================
// 类型定义
// ============================================================================

interface CloudTool {
  tool_id: string;
  name: string;
  description: string;
  version: string;
  author: string;
  category: string;
  tags: string[];
  icon?: string;
  status: string;
  download_count: number;
  rating: number;
  rating_count: number;
  release_date: string;
  last_update: string;
  size_bytes: number;
  params_schema?: Array<{
    name: string;
    type: string;
    required: boolean;
    description: string;
  }>;
}

interface InstalledTool {
  tool_id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  category: string;
  install_date: string;
  source: string;
  auto_update: boolean;
}

interface UpdateInfo {
  tool_id: string;
  current: string;
  latest: string;
  changelog?: string;
}

interface InstallTask {
  task_id: string;
  tool_id: string;
  version: string;
  status: 'pending' | 'downloading' | 'verifying' | 'installing' | 'completed' | 'failed' | 'rolling_back';
  progress: number;
  message: string;
  error?: string;
}

interface ToolCategory {
  id: string;
  name: string;
  icon: React.ReactNode;
  description: string;
}

// ============================================================================
// API 客户端
// ============================================================================

const toolMarketAPI = {
  // 获取云端工具列表
  async getTools(category?: string, page: number = 1): Promise<{ tools: CloudTool[]; total: number }> {
    const params = new URLSearchParams();
    if (category && category !== 'all') params.append('category', category);
    params.append('page', page.toString());
    
    const response = await authFetch(`${API_BASE_URL}/api/cloud-tools/list?${params}`);
    if (!response.ok) throw new Error('获取工具列表失败');
    const data = await response.json();
    return { tools: data.tools || [], total: data.total || 0 };
  },

  // 获取工具详情
  async getToolDetail(toolId: string, version?: string): Promise<CloudTool | null> {
    const url = version 
      ? `${API_BASE_URL}/api/cloud-tools/${toolId}/${version}/detail`
      : `${API_BASE_URL}/api/cloud-tools/${toolId}/latest/detail`;
    
    const response = await authFetch(url);
    if (!response.ok) return null;
    const data = await response.json();
    return data.data || null;
  },

  // 获取工具版本列表
  async getToolVersions(toolId: string): Promise<string[]> {
    const response = await authFetch(`${API_BASE_URL}/api/cloud-tools/${toolId}/versions`);
    if (!response.ok) return [];
    const data = await response.json();
    return data.versions?.map((v: any) => v.version) || [];
  },

  // 下载并安装工具
  async installTool(toolId: string, version: string = 'latest'): Promise<{ task_id: string }> {
    // 通过WebSocket或轮询获取安装进度
    const response = await authFetch(`${API_BASE_URL}/api/tool-market/install`, {
      method: 'POST',
      body: JSON.stringify({ tool_id: toolId, version })
    });
    if (!response.ok) throw new Error('安装请求失败');
    return response.json();
  },

  // 获取已安装工具列表
  async getInstalledTools(): Promise<InstalledTool[]> {
    const response = await authFetch(`${API_BASE_URL}/api/tool-market/installed`);
    if (!response.ok) return [];
    const data = await response.json();
    return data.tools || [];
  },

  // 卸载工具
  async uninstallTool(toolId: string): Promise<boolean> {
    const response = await authFetch(`${API_BASE_URL}/api/tool-market/uninstall/${toolId}`, {
      method: 'POST'
    });
    return response.ok;
  },

  // 检查更新
  async checkUpdates(): Promise<UpdateInfo[]> {
    const response = await authFetch(`${API_BASE_URL}/api/tool-market/check-updates`, {
      method: 'POST',
      body: JSON.stringify({})
    });
    if (!response.ok) return [];
    const data = await response.json();
    return data.updates || [];
  },

  // 获取安装任务状态
  async getInstallTask(taskId: string): Promise<InstallTask | null> {
    const response = await authFetch(`${API_BASE_URL}/api/tool-market/task/${taskId}`);
    if (!response.ok) return null;
    return response.json();
  }
};

// ============================================================================
// 工具函数
// ============================================================================

const formatBytes = (bytes: number): string => {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};

const formatDate = (dateStr: string): string => {
  const date = new Date(dateStr);
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  });
};



// ============================================================================
// 子组件
// ============================================================================

// 星级评分组件
const StarRating = ({ rating, count }: { rating: number; count: number }) => (
  <div className="flex items-center gap-1">
    <Star className="w-4 h-4 text-yellow-400 fill-yellow-400" />
    <span className="text-sm font-medium text-white">{rating.toFixed(1)}</span>
    <span className="text-xs text-sb-text-secondary">({count})</span>
  </div>
);

// 工具卡片组件
const ToolCard = ({
  tool,
  installed,
  onClick,
  onInstall,
  updating
}: {
  tool: CloudTool;
  installed?: InstalledTool;
  onClick: () => void;
  onInstall: (e: React.MouseEvent) => void;
  updating?: boolean;
}) => {
  const isInstalled = !!installed;
  const hasUpdate = installed && installed.version !== tool.version;

  return (
    <motion.div
      layout
      onClick={onClick}
      className="bg-sb-bg-secondary border border-white/10 rounded-xl p-5 cursor-pointer
                 hover:border-sb-cyan/30 hover:bg-sb-bg-secondary/80 transition-all group"
      whileHover={{ y: -2 }}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-sb-cyan/10 rounded-xl flex items-center justify-center">
            {tool.icon ? (
              <img src={tool.icon} alt={tool.name} className="w-8 h-8 object-contain" loading="lazy" />
            ) : (
              <Package className="w-6 h-6 text-sb-cyan" />
            )}
          </div>
          <div>
            <h3 className="font-semibold text-white group-hover:text-sb-cyan transition-colors">
              {tool.name}
            </h3>
            <p className="text-xs text-sb-text-secondary">v{tool.version}</p>
          </div>
        </div>
        
        {isInstalled && (
          <div className={`flex items-center gap-1 px-2 py-1 rounded-full text-xs
            ${hasUpdate ? 'bg-yellow-500/20 text-yellow-400' : 'bg-green-500/20 text-green-400'}`}>
            {hasUpdate ? <RefreshCw className="w-3 h-3" /> : <CheckCircle className="w-3 h-3" />}
            {hasUpdate ? '可更新' : '已安装'}
          </div>
        )}
      </div>

      <p className="text-sm text-sb-text-secondary line-clamp-2 mb-3">
        {tool.description}
      </p>

      <div className="flex items-center justify-between text-xs text-sb-text-secondary mb-3">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <Download className="w-3 h-3" />
            {tool.download_count.toLocaleString()}
          </span>
          <StarRating rating={tool.rating} count={tool.rating_count} />
        </div>
        <span>{formatBytes(tool.size_bytes)}</span>
      </div>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {tool.tags.slice(0, 2).map((tag, i) => (
            <span key={i} className="px-2 py-0.5 bg-white/5 rounded text-xs text-sb-text-secondary">
              {tag}
            </span>
          ))}
        </div>

        <button
          onClick={onInstall}
          disabled={updating}
          className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors
            ${isInstalled 
              ? hasUpdate 
                ? 'bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30' 
                : 'bg-green-500/20 text-green-400 cursor-default'
              : 'bg-sb-cyan/20 text-sb-cyan hover:bg-sb-cyan/30'
            } ${updating ? 'opacity-50 cursor-wait' : ''}`}
        >
          {updating ? (
            <RefreshCw className="w-4 h-4 animate-spin" />
          ) : isInstalled ? (
            hasUpdate ? <><RefreshCw className="w-4 h-4" /> 更新</> : <CheckCircle className="w-4 h-4" />
          ) : (
            <><Download className="w-4 h-4" /> 安装</>
          )}
        </button>
      </div>
    </motion.div>
  );
};

// 工具详情面板
const ToolDetailPanel = ({
  tool,
  installed,
  versions,
  onClose,
  onInstall,
  onUninstall,
  installing
}: {
  tool: CloudTool;
  installed?: InstalledTool;
  versions: string[];
  onClose: () => void;
  onInstall: (version?: string) => void;
  onUninstall: () => void;
  installing: boolean;
}) => {
  const [selectedVersion, setSelectedVersion] = useState(tool.version);
  const isInstalled = !!installed;
  const hasUpdate = installed && installed.version !== tool.version;

  return (
    <motion.div
      initial={{ opacity: 0, x: 400 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 400 }}
      className="fixed right-0 top-0 h-full w-[450px] bg-sb-bg-secondary border-l border-white/10 
                 shadow-2xl z-50 overflow-auto"
    >
      {/* 头部 */}
      <div className="sticky top-0 bg-sb-bg-secondary/95 backdrop-blur border-b border-white/10 p-6">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 bg-sb-cyan/10 rounded-2xl flex items-center justify-center">
              {tool.icon ? (
                <img src={tool.icon} alt={tool.name} className="w-10 h-10 object-contain" loading="lazy" />
              ) : (
                <Package className="w-8 h-8 text-sb-cyan" />
              )}
            </div>
            <div>
              <h2 className="text-xl font-bold text-white">{tool.name}</h2>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-sm text-sb-text-secondary">by {tool.author}</span>
                <span className="text-xs px-2 py-0.5 bg-sb-cyan/10 text-sb-cyan rounded-full">
                  {tool.category}
                </span>
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/10 rounded-lg transition-colors"
          >
            <XCircle className="w-5 h-5 text-sb-text-secondary" />
          </button>
        </div>

        {/* 操作按钮 */}
        <div className="flex gap-3 mt-6">
          {isInstalled ? (
            <>
              {hasUpdate && (
                <button
                  onClick={() => onInstall()}
                  disabled={installing}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 
                           bg-yellow-500/20 text-yellow-400 rounded-lg 
                           hover:bg-yellow-500/30 transition-colors disabled:opacity-50"
                >
                  {installing ? <RefreshCw className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                  更新到 v{tool.version}
                </button>
              )}
              <button
                onClick={onUninstall}
                className="flex items-center justify-center gap-2 px-4 py-2.5 
                         bg-red-500/20 text-red-400 rounded-lg 
                         hover:bg-red-500/30 transition-colors"
              >
                <Trash2 className="w-4 h-4" />
                卸载
              </button>
            </>
          ) : (
            <button
              onClick={() => onInstall(selectedVersion)}
              disabled={installing}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 
                       bg-sb-cyan text-sb-bg-primary rounded-lg 
                       hover:bg-sb-cyan-hover transition-colors disabled:opacity-50"
            >
              {installing ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
              安装
            </button>
          )}
        </div>
      </div>

      {/* 内容 */}
      <div className="p-6 space-y-6">
        {/* 统计信息 */}
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-white/5 rounded-xl p-4 text-center">
            <Download className="w-5 h-5 text-sb-cyan mx-auto mb-1" />
            <p className="text-lg font-semibold text-white">{tool.download_count.toLocaleString()}</p>
            <p className="text-xs text-sb-text-secondary">下载</p>
          </div>
          <div className="bg-white/5 rounded-xl p-4 text-center">
            <Star className="w-5 h-5 text-yellow-400 mx-auto mb-1" />
            <p className="text-lg font-semibold text-white">{tool.rating.toFixed(1)}</p>
            <p className="text-xs text-sb-text-secondary">评分</p>
          </div>
          <div className="bg-white/5 rounded-xl p-4 text-center">
            <Clock className="w-5 h-5 text-green-400 mx-auto mb-1" />
            <p className="text-lg font-semibold text-white">{formatDate(tool.last_update)}</p>
            <p className="text-xs text-sb-text-secondary">更新</p>
          </div>
        </div>

        {/* 版本选择 */}
        <div>
          <h3 className="text-sm font-medium text-white mb-3">选择版本</h3>
          <select
            value={selectedVersion}
            onChange={(e) => setSelectedVersion(e.target.value)}
            className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-4 py-2 
                     text-white focus:border-sb-cyan outline-none"
          >
            {versions.map(v => (
              <option key={v} value={v}>v{v} {v === tool.version ? '(最新)' : ''}</option>
            ))}
          </select>
        </div>

        {/* 描述 */}
        <div>
          <h3 className="text-sm font-medium text-white mb-2">描述</h3>
          <p className="text-sm text-sb-text-secondary leading-relaxed">
            {tool.description}
          </p>
        </div>

        {/* 标签 */}
        <div>
          <h3 className="text-sm font-medium text-white mb-2">标签</h3>
          <div className="flex flex-wrap gap-2">
            {tool.tags.map((tag, i) => (
              <span key={i} className="px-3 py-1 bg-sb-cyan/10 text-sb-cyan rounded-full text-sm">
                {tag}
              </span>
            ))}
          </div>
        </div>

        {/* 参数说明 */}
        {tool.params_schema && tool.params_schema.length > 0 && (
          <div>
            <h3 className="text-sm font-medium text-white mb-3">参数说明</h3>
            <div className="bg-white/5 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/10">
                    <th className="text-left text-sb-text-secondary px-3 py-2 font-medium">参数</th>
                    <th className="text-left text-sb-text-secondary px-3 py-2 font-medium">类型</th>
                    <th className="text-left text-sb-text-secondary px-3 py-2 font-medium">必填</th>
                    <th className="text-left text-sb-text-secondary px-3 py-2 font-medium">描述</th>
                  </tr>
                </thead>
                <tbody>
                  {tool.params_schema.map((param, i) => (
                    <tr key={i} className="border-b border-white/5 last:border-0">
                      <td className="px-3 py-2 text-white font-mono text-xs">{param.name}</td>
                      <td className="px-3 py-2 text-sb-text-secondary text-xs">{param.type}</td>
                      <td className="px-3 py-2">
                        {param.required ? (
                          <span className="text-xs text-red-400">是</span>
                        ) : (
                          <span className="text-xs text-sb-text-secondary">否</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-sb-text-secondary text-xs">{param.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* 安装状态 */}
        {isInstalled && (
          <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <CheckCircle className="w-5 h-5 text-green-400" />
              <span className="text-green-400 font-medium">已安装</span>
            </div>
            <p className="text-sm text-sb-text-secondary">
              当前版本: v{installed.version}
            </p>
            <p className="text-xs text-sb-text-secondary mt-1">
              安装时间: {formatDate(installed.install_date)}
            </p>
            {hasUpdate && (
              <p className="text-sm text-yellow-400 mt-2">
                有新版本可用: v{tool.version}
              </p>
            )}
          </div>
        )}

        {/* 元信息 */}
        <div className="border-t border-white/10 pt-4 space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-sb-text-secondary">大小</span>
            <span className="text-white">{formatBytes(tool.size_bytes)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-sb-text-secondary">发布日期</span>
            <span className="text-white">{formatDate(tool.release_date)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-sb-text-secondary">分类</span>
            <span className="text-white">{tool.category}</span>
          </div>
        </div>
      </div>
    </motion.div>
  );
};

// 安装进度弹窗
const InstallProgressModal = ({
  task,
  onClose
}: {
  task: InstallTask | null;
  onClose: () => void;
}) => {
  if (!task) return null;

  const getStatusIcon = () => {
    switch (task.status) {
      case 'completed':
        return <CheckCircle className="w-12 h-12 text-green-400" />;
      case 'failed':
        return <XCircle className="w-12 h-12 text-red-400" />;
      case 'downloading':
        return <Download className="w-12 h-12 text-sb-cyan animate-bounce" />;
      default:
        return <RefreshCw className="w-12 h-12 text-sb-cyan animate-spin" />;
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="bg-sb-bg-secondary border border-white/10 rounded-2xl w-full max-w-md m-4 p-6"
      >
        <div className="text-center mb-6">
          {getStatusIcon()}
          <h3 className="text-lg font-semibold text-white mt-4">
            {task.status === 'completed' ? '安装完成' : 
             task.status === 'failed' ? '安装失败' : '安装中...'}
          </h3>
          <p className="text-sm text-sb-text-secondary mt-1">
            {toolMarketAPI ? task.message : '正在连接服务器...'}
          </p>
        </div>

        {/* 进度条 */}
        <div className="mb-4">
          <div className="h-2 bg-white/10 rounded-full overflow-hidden">
            <motion.div
              className="h-full bg-sb-cyan"
              initial={{ width: 0 }}
              animate={{ width: `${task.progress}%` }}
              transition={{ duration: 0.3 }}
            />
          </div>
          <p className="text-right text-xs text-sb-text-secondary mt-1">
            {task.progress}%
          </p>
        </div>

        {/* 错误信息 */}
        {task.error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 mb-4">
            <p className="text-sm text-red-400">{task.error}</p>
          </div>
        )}

        {/* 按钮 */}
        <div className="flex justify-center">
          <button
            onClick={onClose}
            disabled={task.status !== 'completed' && task.status !== 'failed'}
            className="px-6 py-2 bg-sb-cyan text-sb-bg-primary rounded-lg font-medium
                     hover:bg-sb-cyan-hover transition-colors disabled:opacity-50"
          >
            {task.status === 'completed' || task.status === 'failed' ? '关闭' : '请稍候...'}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

// ============================================================================
// 主页面组件
// ============================================================================

const categories: ToolCategory[] = [
  { id: 'all', name: '全部', icon: <Grid className="w-4 h-4" />, description: '所有工具' },
  { id: 'productivity', name: '生产力', icon: <Zap className="w-4 h-4" />, description: '提升效率的工具' },
  { id: 'development', name: '开发', icon: <Code className="w-4 h-4" />, description: '开发辅助工具' },
  { id: 'media', name: '媒体', icon: <Image className="w-4 h-4" />, description: '图像音视频处理' },
  { id: 'system', name: '系统', icon: <Terminal className="w-4 h-4" />, description: '系统管理工具' },
  { id: 'network', name: '网络', icon: <Globe className="w-4 h-4" />, description: '网络通信工具' },
  { id: 'data', name: '数据', icon: <Database className="w-4 h-4" />, description: '数据处理工具' },
  { id: 'security', name: '安全', icon: <Lock className="w-4 h-4" />, description: '安全加密工具' },
  { id: 'other', name: '其他', icon: <Package className="w-4 h-4" />, description: '其他工具' },
];

export function ToolMarketPage() {
  const navigate = useNavigate()
  
  // 状态
  const [activeTab, setActiveTab] = useState<'market' | 'installed' | 'updates'>('market');
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [sortBy, setSortBy] = useState<'popular' | 'newest' | 'rating'>('popular');
  
  const [cloudTools, setCloudTools] = useState<CloudTool[]>([]);
  const [installedTools, setInstalledTools] = useState<InstalledTool[]>([]);
  const [updates, setUpdates] = useState<UpdateInfo[]>([]);
  const [selectedTool, setSelectedTool] = useState<CloudTool | null>(null);
  const [toolVersions, setToolVersions] = useState<string[]>([]);
  const [installTask, setInstallTask] = useState<InstallTask | null>(null);
  
  const [loading, setLoading] = useState(true);
  const [installing, setInstalling] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  
  const { showNotification } = useNotifications();
  const pollingRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 加载云端工具列表
  const loadCloudTools = useCallback(async (reset = false) => {
    try {
      setLoading(true);
      const currentPage = reset ? 1 : page;
      const { tools, total } = await toolMarketAPI.getTools(
        selectedCategory === 'all' ? undefined : selectedCategory,
        currentPage
      );
      
      if (reset) {
        setCloudTools(tools);
        setPage(1);
      } else {
        setCloudTools(prev => [...prev, ...tools]);
      }
      
      setHasMore(cloudTools.length + tools.length < total);
    } catch (err) {
      showNotification({
        type: 'error',
        title: '加载失败',
        message: '无法获取云端工具列表'
      });
    } finally {
      setLoading(false);
    }
  }, [selectedCategory, page, cloudTools.length]);

  // 加载已安装工具
  const loadInstalledTools = useCallback(async () => {
    try {
      const tools = await toolMarketAPI.getInstalledTools();
      setInstalledTools(tools);
    } catch (err) {
      console.error('加载已安装工具失败:', err);
    }
  }, []);

  // 检查更新
  const checkUpdates = useCallback(async () => {
    try {
      const updateList = await toolMarketAPI.checkUpdates();
      setUpdates(updateList);
    } catch (err) {
      console.error('检查更新失败:', err);
    }
  }, []);

  // 初始加载
  useEffect(() => {
    loadCloudTools(true);
    loadInstalledTools();
    checkUpdates();
  }, []);

  // 分类切换时重新加载
  useEffect(() => {
    loadCloudTools(true);
  }, [selectedCategory]);

  // 轮询安装任务状态
  useEffect(() => {
    if (installTask && installTask.status !== 'completed' && installTask.status !== 'failed') {
      pollingRef.current = setInterval(async () => {
        const task = await toolMarketAPI.getInstallTask(installTask.task_id);
        if (task) {
          setInstallTask(task);
          if (task.status === 'completed' || task.status === 'failed') {
            if (pollingRef.current) {
              clearInterval(pollingRef.current);
            }
            setInstalling(false);
            loadInstalledTools();
            
            if (task.status === 'completed') {
              showNotification({
                type: 'success',
                title: '安装成功',
                message: `工具 ${task.tool_id} 安装完成`
              });
            }
          }
        }
      }, 1000);
    }

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, [installTask]);

  // 搜索过滤
  const filteredTools = cloudTools.filter(tool => {
    if (!searchQuery) return true;
    const query = searchQuery.toLowerCase();
    return (
      tool.name.toLowerCase().includes(query) ||
      tool.description.toLowerCase().includes(query) ||
      tool.tags.some(tag => tag.toLowerCase().includes(query))
    );
  });

  // 排序
  const sortedTools = [...filteredTools].sort((a, b) => {
    switch (sortBy) {
      case 'popular':
        return b.download_count - a.download_count;
      case 'newest':
        return new Date(b.release_date).getTime() - new Date(a.release_date).getTime();
      case 'rating':
        return b.rating - a.rating;
      default:
        return 0;
    }
  });

  // 安装工具
  const handleInstall = async (toolId: string, version?: string) => {
    try {
      setInstalling(true);
      const { task_id } = await toolMarketAPI.installTool(toolId, version || 'latest');
      
      setInstallTask({
        task_id,
        tool_id: toolId,
        version: version || 'latest',
        status: 'pending',
        progress: 0,
        message: '准备安装...'
      });
    } catch (err: any) {
      showNotification({
        type: 'error',
        title: '安装失败',
        message: err.message || '无法启动安装'
      });
      setInstalling(false);
    }
  };

  // 卸载工具
  const handleUninstall = async (toolId: string) => {
    try {
      const success = await toolMarketAPI.uninstallTool(toolId);
      if (success) {
        showNotification({
          type: 'success',
          title: '卸载成功',
          message: `工具 ${toolId} 已卸载`
        });
        loadInstalledTools();
        setSelectedTool(null);
      }
    } catch (err: any) {
      showNotification({
        type: 'error',
        title: '卸载失败',
        message: err.message
      });
    }
  };

  // 查看工具详情
  const handleViewDetail = async (tool: CloudTool) => {
    setSelectedTool(tool);
    const versions = await toolMarketAPI.getToolVersions(tool.tool_id);
    setToolVersions(versions);
  };

  // 获取已安装工具信息
  const getInstalledInfo = (toolId: string) => {
    return installedTools.find(t => t.tool_id === toolId);
  };

  return (
    <div className="h-full flex overflow-hidden">
      {/* 左侧边栏 */}
      <div className="w-64 bg-sb-bg-secondary/30 border-r border-white/5 flex flex-col">
        {/* Logo */}
        <div className="p-4 border-b border-white/5">
          <div className="flex items-center gap-2 text-white font-medium">
            <Cloud className="w-5 h-5 text-sb-cyan" />
            云端工具市场
          </div>
        </div>

        {/* 标签切换 */}
        <div className="p-2 border-b border-white/5">
          <button
            onClick={() => setActiveTab('market')}
            className={`w-full flex items-center gap-2 px-4 py-2.5 rounded-lg text-left transition-colors
              ${activeTab === 'market' ? 'bg-sb-cyan/20 text-sb-cyan' : 'text-sb-text-secondary hover:bg-white/5 hover:text-white'}`}
          >
            <Grid className="w-4 h-4" />
            浏览市场
          </button>
          <button
            onClick={() => setActiveTab('installed')}
            className={`w-full flex items-center gap-2 px-4 py-2.5 rounded-lg text-left transition-colors mt-1
              ${activeTab === 'installed' ? 'bg-sb-cyan/20 text-sb-cyan' : 'text-sb-text-secondary hover:bg-white/5 hover:text-white'}`}
          >
            <Package className="w-4 h-4" />
            已安装
            {installedTools.length > 0 && (
              <span className="ml-auto text-xs bg-sb-cyan/20 text-sb-cyan px-2 py-0.5 rounded-full">
                {installedTools.length}
              </span>
            )}
          </button>
          <button
            onClick={() => navigate('/tools?tab=custom')}
            className="w-full flex items-center gap-2 px-4 py-2.5 rounded-lg text-left transition-colors mt-1 text-sb-text-secondary hover:bg-white/5 hover:text-white"
          >
            <Plus className="w-4 h-4" />
            创建自定义工具
          </button>
          <button
            onClick={() => setActiveTab('updates')}
            className={`w-full flex items-center gap-2 px-4 py-2.5 rounded-lg text-left transition-colors mt-1
              ${activeTab === 'updates' ? 'bg-sb-cyan/20 text-sb-cyan' : 'text-sb-text-secondary hover:bg-white/5 hover:text-white'}`}
          >
            <RefreshCw className="w-4 h-4" />
            可更新
            {updates.length > 0 && (
              <span className="ml-auto text-xs bg-yellow-500/20 text-yellow-400 px-2 py-0.5 rounded-full">
                {updates.length}
              </span>
            )}
          </button>
        </div>

        {/* 分类列表（仅在浏览市场时显示） */}
        {activeTab === 'market' && (
          <div className="flex-1 overflow-auto p-2">
            <p className="text-xs text-sb-text-secondary px-4 py-2 uppercase tracking-wider">分类</p>
            {categories.map(cat => (
              <button
                key={cat.id}
                onClick={() => setSelectedCategory(cat.id)}
                className={`w-full flex items-center gap-2 px-4 py-2 rounded-lg text-left transition-colors
                  ${selectedCategory === cat.id 
                    ? 'bg-white/10 text-white' 
                    : 'text-sb-text-secondary hover:bg-white/5 hover:text-white'}`}
              >
                {cat.icon}
                <span>{cat.name}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 主内容区 */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* 顶部工具栏 */}
        <div className="p-4 border-b border-white/5 flex items-center justify-between">
          <div className="flex items-center gap-4 flex-1">
            {/* 搜索 */}
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-sb-text-secondary" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索工具..."
                className="w-full bg-sb-bg-secondary border border-white/10 rounded-lg pl-10 pr-4 py-2 
                         text-white text-sm focus:border-sb-cyan outline-none"
              />
            </div>

            {/* 排序 */}
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as any)}
              className="bg-sb-bg-secondary border border-white/10 rounded-lg px-3 py-2 
                       text-white text-sm focus:border-sb-cyan outline-none"
            >
              <option value="popular">最受欢迎</option>
              <option value="newest">最新发布</option>
              <option value="rating">评分最高</option>
            </select>
          </div>

          {/* 视图切换 */}
          <div className="flex items-center gap-1 bg-sb-bg-secondary rounded-lg p-1 ml-4">
            <button
              onClick={() => setViewMode('grid')}
              className={`p-1.5 rounded transition-colors ${viewMode === 'grid' ? 'bg-white/10 text-white' : 'text-sb-text-secondary'}`}
            >
              <Grid className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`p-1.5 rounded transition-colors ${viewMode === 'list' ? 'bg-white/10 text-white' : 'text-sb-text-secondary'}`}
            >
              <List className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* 内容区 */}
        <div className="flex-1 overflow-auto p-4">
          {activeTab === 'market' && (
            <>
              {loading && cloudTools.length === 0 ? (
                <div className="flex items-center justify-center h-full">
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                    className="w-8 h-8 border-2 border-sb-cyan border-t-transparent rounded-full"
                  />
                </div>
              ) : sortedTools.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-sb-text-secondary">
                  <Package className="w-16 h-16 mb-4 opacity-50" />
                  <p>暂无工具</p>
                </div>
              ) : (
                <div className={viewMode === 'grid' 
                  ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
                  : "space-y-2"
                }>
                  {sortedTools.map((tool, index) => (
                    <motion.div
                      key={tool.tool_id}
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: index * 0.05 }}
                    >
                      <ToolCard
                        tool={tool}
                        installed={getInstalledInfo(tool.tool_id)}
                        onClick={() => handleViewDetail(tool)}
                        onInstall={(e) => {
                          e.stopPropagation();
                          handleInstall(tool.tool_id);
                        }}
                        updating={installing}
                      />
                    </motion.div>
                  ))}
                </div>
              )}

              {/* 加载更多 */}
              {hasMore && !loading && (
                <div className="flex justify-center mt-6">
                  <button
                    onClick={() => {
                      setPage(p => p + 1);
                      loadCloudTools();
                    }}
                    className="px-4 py-2 bg-sb-bg-secondary text-sb-text-secondary rounded-lg
                             hover:bg-sb-bg-secondary/80 transition-colors"
                  >
                    加载更多
                  </button>
                </div>
              )}
            </>
          )}

          {activeTab === 'installed' && (
            <>
              {installedTools.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-sb-text-secondary">
                  <Package className="w-16 h-16 mb-4 opacity-50" />
                  <p>还没有安装任何工具</p>
                  <button
                    onClick={() => setActiveTab('market')}
                    className="mt-4 px-4 py-2 bg-sb-cyan/20 text-sb-cyan rounded-lg hover:bg-sb-cyan/30"
                  >
                    去浏览市场
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  {installedTools.map(tool => {
                    const cloudTool = cloudTools.find(t => t.tool_id === tool.tool_id);
                    const hasUpdate = cloudTool && cloudTool.version !== tool.version;

                    return (
                      <div
                        key={tool.tool_id}
                        className="bg-sb-bg-secondary border border-white/10 rounded-xl p-4
                                 flex items-center justify-between hover:border-sb-cyan/30 transition-colors"
                      >
                        <div className="flex items-center gap-4">
                          <div className="w-12 h-12 bg-sb-cyan/10 rounded-xl flex items-center justify-center">
                            <Package className="w-6 h-6 text-sb-cyan" />
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <h3 className="font-medium text-white">{tool.name}</h3>
                              {hasUpdate && (
                                <span className="text-xs px-2 py-0.5 bg-yellow-500/20 text-yellow-400 rounded-full">
                                  有新版本
                                </span>
                              )}
                            </div>
                            <p className="text-sm text-sb-text-secondary">
                              v{tool.version} · {tool.category} · 安装于 {formatDate(tool.install_date)}
                            </p>
                          </div>
                        </div>

                        <div className="flex items-center gap-2">
                          {hasUpdate && cloudTool && (
                            <button
                              onClick={() => handleInstall(tool.tool_id)}
                              disabled={installing}
                              className="flex items-center gap-1 px-3 py-1.5 bg-yellow-500/20 text-yellow-400 
                                       rounded-lg hover:bg-yellow-500/30 transition-colors disabled:opacity-50"
                            >
                              <RefreshCw className={`w-4 h-4 ${installing ? 'animate-spin' : ''}`} />
                              更新到 v{cloudTool.version}
                            </button>
                          )}
                          <button
                            onClick={() => handleUninstall(tool.tool_id)}
                            className="p-2 text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}

          {activeTab === 'updates' && (
            <>
              {updates.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-sb-text-secondary">
                  <CheckCircle className="w-16 h-16 mb-4 text-green-400" />
                  <p>所有工具都是最新版本</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {updates.map(update => {
                    const installed = installedTools.find(t => t.tool_id === update.tool_id);

                    return (
                      <div
                        key={update.tool_id}
                        className="bg-sb-bg-secondary border border-white/10 rounded-xl p-4
                                 flex items-center justify-between"
                      >
                        <div className="flex items-center gap-4">
                          <div className="w-12 h-12 bg-yellow-500/10 rounded-xl flex items-center justify-center">
                            <RefreshCw className="w-6 h-6 text-yellow-400" />
                          </div>
                          <div>
                            <h3 className="font-medium text-white">
                              {installed?.name || update.tool_id}
                            </h3>
                            <p className="text-sm text-sb-text-secondary">
                              v{update.current} → v{update.latest}
                            </p>
                          </div>
                        </div>

                        <button
                          onClick={() => handleInstall(update.tool_id, update.latest)}
                          disabled={installing}
                          className="flex items-center gap-1 px-4 py-2 bg-sb-cyan text-sb-bg-primary 
                                   rounded-lg hover:bg-sb-cyan-hover transition-colors disabled:opacity-50"
                        >
                          <Download className="w-4 h-4" />
                          更新
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* 工具详情面板 */}
      <AnimatePresence>
        {selectedTool && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setSelectedTool(null)}
              className="fixed inset-0 bg-black/50 z-40"
            />
            <ToolDetailPanel
              tool={selectedTool}
              installed={getInstalledInfo(selectedTool.tool_id)}
              versions={toolVersions}
              onClose={() => setSelectedTool(null)}
              onInstall={(version) => handleInstall(selectedTool.tool_id, version)}
              onUninstall={() => handleUninstall(selectedTool.tool_id)}
              installing={installing}
            />
          </>
        )}
      </AnimatePresence>

      {/* 安装进度弹窗 */}
      <AnimatePresence>
        {installTask && (
          <InstallProgressModal
            task={installTask}
            onClose={() => {
              if (installTask.status === 'completed' || installTask.status === 'failed') {
                setInstallTask(null);
              }
            }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

export default ToolMarketPage;
