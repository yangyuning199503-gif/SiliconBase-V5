/**
 * GlobalView 页面 - 磁盘文件扫描可视化
 * 
 * 功能：
 * - 树状展示扫描的文件目录结构
 * - 实时显示扫描进度
 * - 支持搜索文件
 * - 支持手动清空和重新扫描
 * - 统计信息展示
 */
import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Folder, File, HardDrive, Search, RefreshCw, Trash2,
  Play, Square, ChevronRight, ChevronDown, Loader2,
  BarChart3, FileText, Image, Music, Video, Archive,
  Code, Settings, X, CheckCircle, AlertCircle
} from 'lucide-react';
import { useNotifications } from '../hooks/useNotifications';
import { useQuery } from '@tanstack/react-query';
import {
  globalViewAPI,
  FileNode,
  ScanStatus,
  FileStats
} from '../utils/api/globalView';

// 文件类型图标映射
const FILE_ICONS: Record<string, React.ReactNode> = {
  executable: <Settings className="w-4 h-4 text-purple-400" />,
  code: <Code className="w-4 h-4 text-blue-400" />,
  document: <FileText className="w-4 h-4 text-yellow-400" />,
  image: <Image className="w-4 h-4 text-green-400" />,
  media: <Music className="w-4 h-4 text-pink-400" />,
  video: <Video className="w-4 h-4 text-red-400" />,
  archive: <Archive className="w-4 h-4 text-orange-400" />,
  other: <File className="w-4 h-4 text-gray-400" />,
};

// 格式化文件大小
function formatSize(bytes?: number): string {
  if (!bytes) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex++;
  }
  return `${size.toFixed(1)} ${units[unitIndex]}`;
}



// 树节点组件
interface TreeNodeProps {
  node: FileNode;
  level: number;
  defaultExpanded?: boolean;
}

function TreeNode({ node, level, defaultExpanded = false }: TreeNodeProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded && level < 2);
  const hasChildren = node.children && node.children.length > 0;
  const isFolder = node.type === 'folder';

  return (
    <div className="select-none">
      <motion.div
        initial={{ opacity: 0, x: -10 }}
        animate={{ opacity: 1, x: 0 }}
        className={`
          flex items-center gap-2 py-1.5 px-2 rounded-lg cursor-pointer
          hover:bg-white/5 transition-colors group
          ${isFolder ? 'font-medium' : ''}
        `}
        style={{ paddingLeft: `${level * 20 + 8}px` }}
        onClick={() => hasChildren && setIsExpanded(!isExpanded)}
      >
        {/* 展开/折叠指示器 */}
        <span className="w-4 h-4 flex items-center justify-center">
          {hasChildren ? (
            isExpanded ? (
              <ChevronDown className="w-4 h-4 text-gray-500" />
            ) : (
              <ChevronRight className="w-4 h-4 text-gray-500" />
            )
          ) : (
            <span className="w-4" />
          )}
        </span>

        {/* 图标 */}
        <span className="flex-shrink-0">
          {isFolder ? (
            <Folder className="w-5 h-5 text-yellow-500" />
          ) : (
            FILE_ICONS[node.file_type || 'other'] || FILE_ICONS.other
          )}
        </span>

        {/* 名称 */}
        <span className="flex-1 truncate text-sm text-gray-200" title={node.path}>
          {node.name}
        </span>

        {/* 大小（仅文件） */}
        {!isFolder && node.size !== undefined && (
          <span className="text-xs text-gray-500 w-20 text-right">
            {formatSize(node.size)}
          </span>
        )}

        {/* 可执行标记 */}
        {node.is_executable && (
          <span className="text-xs px-1.5 py-0.5 bg-purple-500/20 text-purple-400 rounded">
            EXE
          </span>
        )}
      </motion.div>

      {/* 子节点 */}
      <AnimatePresence>
        {isExpanded && hasChildren && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            {node.children!.map((child) => (
              <TreeNode
                key={child.id}
                node={child}
                level={level + 1}
                defaultExpanded={defaultExpanded}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// 主页面组件
export function GlobalViewPage() {
  const { showNotification } = useNotifications();
  const [isLoading, setIsLoading] = useState(true);
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [stats, setStats] = useState<FileStats | null>(null);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [searchResults, setSearchResults] = useState<FileNode[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showConfirmClear, setShowConfirmClear] = useState(false);
  const [selectedDrive, setSelectedDrive] = useState<string>('');
  const [apiError, setApiError] = useState<string | null>(null);

  // 获取扫描状态
  const fetchStatus = useCallback(async () => {
    try {
      const status = await globalViewAPI.getScanStatus();
      setScanStatus(status);
      setApiError(null); // 清除错误状态
      return status;
    } catch (error) {
      console.error('获取扫描状态失败:', error);
      setApiError('无法连接到扫描服务');
      // 设置默认状态，避免界面显示异常
      setScanStatus({
        is_scanning: false,
        progress: 0,
        scanned_files: 0,
        total_files: 0,
        message: '服务未就绪'
      });
      return null;
    }
  }, []);

  // 获取文件树
  const fetchFileTree = useCallback(async () => {
    try {
      setIsLoading(true);
      const tree = await globalViewAPI.getFileTree(
        selectedDrive || undefined,
        3
      );
      setFileTree(tree.drives || []);
      return tree;
    } catch (error) {
      console.error('获取文件树失败:', error);
      // 静默失败，不显示错误通知（避免频繁弹出）
      setFileTree([]);
      return null;
    } finally {
      setIsLoading(false);
    }
  }, [selectedDrive]);

  // 获取统计
  const fetchStats = useCallback(async () => {
    try {
      const s = await globalViewAPI.getStats();
      setStats(s);
      return s;
    } catch (error) {
      console.error('获取统计失败:', error);
      // 设置默认空统计
      setStats({
        total_files: 0,
        total_folders: 0,
        total_size: 0,
        by_type: {},
        by_drive: {}
      });
      return null;
    }
  }, []);

  // 轮询扫描状态
  useQuery({
    queryKey: ['globalViewStatus'],
    queryFn: fetchStatus,
    refetchInterval: 2000,
  });

  // 初始加载
  useEffect(() => {
    fetchFileTree();
    fetchStats();
  }, [fetchFileTree, fetchStats]);

  // 开始扫描
  const handleStartScan = async () => {
    try {
      const result = await globalViewAPI.startScan(
        selectedDrive ? [selectedDrive] : undefined
      );
      if (result.success) {
        showNotification({ title: '扫描任务已启动', type: 'success', message: '' });
        fetchStatus();
      } else {
        showNotification({ title: result.message, type: 'warning', message: '' });
      }
    } catch (error) {
      showNotification({ title: '启动扫描失败', type: 'error', message: '' });
    }
  };

  // 停止扫描
  const handleStopScan = async () => {
    try {
      await globalViewAPI.stopScan();
      showNotification({ title: '扫描停止信号已发送', type: 'info', message: '' });
    } catch (error) {
      showNotification({ title: '停止扫描失败', type: 'error', message: '' });
    }
  };

  // 清空数据
  const handleClearData = async () => {
    try {
      const result = await globalViewAPI.clearAllData();
      if (result.success) {
        showNotification({ title: result.message, type: 'success', message: '' });
        setShowConfirmClear(false);
        fetchFileTree();
        fetchStats();
      }
    } catch (error) {
      showNotification({ title: '清空数据失败', type: 'error', message: '' });
    }
  };

  // 搜索
  const handleSearch = async () => {
    if (!searchKeyword.trim()) return;
    
    try {
      setIsSearching(true);
      const result = await globalViewAPI.searchFiles(searchKeyword);
      setSearchResults(result.results);
    } catch (error) {
      showNotification({ title: '搜索失败', type: 'error', message: '' });
    } finally {
      setIsSearching(false);
    }
  };

  // 刷新
  const handleRefresh = () => {
    fetchStatus();
    fetchFileTree();
    fetchStats();
    showNotification({ title: '数据已刷新', type: 'success', message: '' });
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-white p-4 md:p-6">
      {/* 头部 */}
      <div className="max-w-7xl mx-auto mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-3">
          <HardDrive className="w-7 h-7 text-cyan-400" />
          磁盘文件扫描
        </h1>
        <p className="text-gray-400 mt-1">
          可视化展示本地文件扫描结果，支持智能搜索
        </p>
      </div>

      {/* API 错误提示 */}
      {apiError && (
        <div className="max-w-7xl mx-auto mb-6 p-4 bg-red-500/10 border border-red-500/20 rounded-xl">
          <div className="flex items-center gap-3 text-red-400">
            <AlertCircle className="w-5 h-5" />
            <span>{apiError}</span>
            <button 
              onClick={handleRefresh}
              className="ml-auto text-sm px-3 py-1 bg-red-500/20 hover:bg-red-500/30 rounded-lg transition-colors"
            >
              重试
            </button>
          </div>
        </div>
      )}

      {/* 扫描状态栏 */}
      <div className="max-w-7xl mx-auto bg-white/5 rounded-xl p-4 mb-6 border border-white/10">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div className="flex items-center gap-4">
            {/* 状态指示 */}
            <div className={`flex items-center gap-2 ${
              scanStatus?.is_scanning ? 'text-yellow-400' : 'text-green-400'
            }`}>
              {scanStatus?.is_scanning ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <CheckCircle className="w-5 h-5" />
              )}
              <span className="font-medium">
                {scanStatus?.is_scanning ? '扫描中...' : '就绪'}
              </span>
            </div>

            {/* 进度 */}
            {scanStatus?.is_scanning && (
              <div className="flex items-center gap-3">
                <div className="w-32 h-2 bg-gray-700 rounded-full overflow-hidden">
                  <motion.div
                    className="h-full bg-cyan-500"
                    initial={{ width: 0 }}
                    animate={{ width: `${scanStatus.progress}%` }}
                    transition={{ duration: 0.5 }}
                  />
                </div>
                <span className="text-sm text-gray-400">
                  {scanStatus.progress}%
                </span>
              </div>
            )}

            {/* 文件计数 */}
            <span className="text-sm text-gray-400">
              已扫描: {scanStatus?.scanned_files?.toLocaleString() ?? 0} 文件
              {(scanStatus?.total_files || 0) > 0 && ` / ${scanStatus!.total_files.toLocaleString()}`}
            </span>
          </div>

          {/* 操作按钮 */}
          <div className="flex items-center gap-2">
            {/* 磁盘选择 */}
            <select
              value={selectedDrive}
              onChange={(e) => setSelectedDrive(e.target.value)}
              className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-cyan-500"
            >
              <option value="">所有磁盘</option>
              {stats?.by_drive && Object.keys(stats.by_drive).map(drive => (
                <option key={drive} value={drive}>{drive}盘</option>
              ))}
            </select>

            {/* 开始/停止扫描 */}
            {scanStatus?.is_scanning ? (
              <button
                onClick={handleStopScan}
                className="flex items-center gap-2 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg transition-colors"
              >
                <Square className="w-4 h-4" />
                停止
              </button>
            ) : (
              <button
                onClick={handleStartScan}
                className="flex items-center gap-2 px-4 py-2 bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-400 rounded-lg transition-colors"
              >
                <Play className="w-4 h-4" />
                开始扫描
              </button>
            )}

            {/* 刷新 */}
            <button
              onClick={handleRefresh}
              className="flex items-center gap-2 px-4 py-2 bg-gray-700/50 hover:bg-gray-700 text-gray-300 rounded-lg transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              刷新
            </button>

            {/* 清空数据 */}
            <button
              onClick={() => setShowConfirmClear(true)}
              className="flex items-center gap-2 px-4 py-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-lg transition-colors"
            >
              <Trash2 className="w-4 h-4" />
              清空
            </button>
          </div>
        </div>
      </div>

      {/* 统计卡片 */}
      {stats && (
        <div className="max-w-7xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="bg-white/5 rounded-xl p-4 border border-white/10">
            <div className="text-gray-400 text-sm mb-1">总文件数</div>
            <div className="text-2xl font-bold text-cyan-400">
              {stats.total_files.toLocaleString()}
            </div>
          </div>
          <div className="bg-white/5 rounded-xl p-4 border border-white/10">
            <div className="text-gray-400 text-sm mb-1">总大小</div>
            <div className="text-2xl font-bold text-green-400">
              {formatSize(stats.total_size)}
            </div>
          </div>
          <div className="bg-white/5 rounded-xl p-4 border border-white/10">
            <div className="text-gray-400 text-sm mb-1">文件类型</div>
            <div className="text-2xl font-bold text-purple-400">
              {Object.keys(stats.by_type).length}
            </div>
          </div>
          <div className="bg-white/5 rounded-xl p-4 border border-white/10">
            <div className="text-gray-400 text-sm mb-1">磁盘数量</div>
            <div className="text-2xl font-bold text-yellow-400">
              {Object.keys(stats.by_drive).length}
            </div>
          </div>
        </div>
      )}

      {/* 搜索栏 */}
      <div className="max-w-7xl mx-auto flex gap-3 mb-6">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500" />
          <input
            type="text"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="搜索文件名..."
            className="w-full pl-10 pr-4 py-2.5 bg-gray-800/50 border border-gray-700 rounded-lg focus:outline-none focus:border-cyan-500 text-white placeholder-gray-500"
          />
        </div>
        <button
          onClick={handleSearch}
          disabled={isSearching || !searchKeyword.trim()}
          className="px-6 py-2.5 bg-cyan-500 hover:bg-cyan-600 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg transition-colors flex items-center gap-2"
        >
          {isSearching ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Search className="w-4 h-4" />
          )}
          搜索
        </button>
      </div>

      {/* 主内容区 */}
      <div className="max-w-7xl mx-auto grid lg:grid-cols-3 gap-6">
        {/* 文件树 */}
        <div className="lg:col-span-2 bg-white/5 rounded-xl border border-white/10 overflow-hidden">
          <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
            <h2 className="font-medium flex items-center gap-2">
              <Folder className="w-5 h-5 text-yellow-500" />
              文件目录
              {selectedDrive && (
                <span className="text-sm text-gray-400">({selectedDrive}盘)</span>
              )}
            </h2>
            <span className="text-sm text-gray-500">
              {fileTree.length} 个磁盘
            </span>
          </div>
          
          <div className="p-2 max-h-[600px] overflow-y-auto">
            {isLoading ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="w-8 h-8 animate-spin text-cyan-400" />
              </div>
            ) : fileTree.length > 0 ? (
              fileTree.map((drive) => (
                <TreeNode
                  key={drive.id}
                  node={drive}
                  level={0}
                  defaultExpanded={fileTree.length <= 3}
                />
              ))
            ) : (
              <div className="flex flex-col items-center justify-center py-16 text-gray-500">
                <div className="w-20 h-20 rounded-full bg-gray-800/50 flex items-center justify-center mb-4">
                  <HardDrive className="w-10 h-10 text-gray-600" />
                </div>
                <p className="text-lg font-medium text-gray-400">暂无扫描数据</p>
                <p className="text-sm mt-2 text-gray-500 max-w-md text-center">
                  点击上方"开始扫描"按钮，系统将自动扫描所有磁盘文件
                </p>
                <div className="mt-4 text-xs text-gray-600">
                  <p>✓ 扫描过程在后台运行，不影响使用</p>
                  <p>✓ 只记录程序文件位置，保护隐私</p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 右侧：搜索结果 + 类型分布 */}
        <div className="space-y-6">
          {/* 搜索结果 */}
          {searchResults.length > 0 && (
            <div className="bg-white/5 rounded-xl border border-white/10 overflow-hidden">
              <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
                <h2 className="font-medium flex items-center gap-2">
                  <Search className="w-5 h-5 text-cyan-400" />
                  搜索结果
                </h2>
                <button
                  onClick={() => setSearchResults([])}
                  className="text-gray-500 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="p-2 max-h-[300px] overflow-y-auto">
                {searchResults.map((file) => (
                  <div
                    key={file.id}
                    className="flex items-center gap-2 py-2 px-3 rounded-lg hover:bg-white/5 transition-colors"
                  >
                    {FILE_ICONS[file.file_type || 'other'] || FILE_ICONS.other}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm truncate" title={file.name}>
                        {file.name}
                      </div>
                      <div className="text-xs text-gray-500 truncate" title={file.path}>
                        {file.path}
                      </div>
                    </div>
                    <span className="text-xs text-gray-500">
                      {formatSize(file.size)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 文件类型分布 */}
          {stats && Object.keys(stats.by_type).length > 0 && (
            <div className="bg-white/5 rounded-xl border border-white/10 p-4">
              <h2 className="font-medium mb-4 flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-purple-400" />
                文件类型分布
              </h2>
              <div className="space-y-2">
                {Object.entries(stats.by_type)
                  .sort(([, a], [, b]) => b - a)
                  .slice(0, 8)
                  .map(([type, count]) => (
                    <div key={type} className="flex items-center justify-between">
                      <span className="text-sm text-gray-300 capitalize">{type}</span>
                      <span className="text-sm text-gray-500">{count.toLocaleString()}</span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* 磁盘分布 */}
          {stats && Object.keys(stats.by_drive).length > 0 && (
            <div className="bg-white/5 rounded-xl border border-white/10 p-4">
              <h2 className="font-medium mb-4 flex items-center gap-2">
                <HardDrive className="w-5 h-5 text-cyan-400" />
                磁盘分布
              </h2>
              <div className="space-y-2">
                {Object.entries(stats.by_drive).map(([drive, count]) => (
                  <div key={drive} className="flex items-center justify-between">
                    <span className="text-sm text-gray-300">{drive}盘</span>
                    <span className="text-sm text-gray-500">{count.toLocaleString()} 文件</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 清空确认对话框 */}
      <AnimatePresence>
        {showConfirmClear && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
            onClick={() => setShowConfirmClear(false)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="bg-gray-800 rounded-xl p-6 max-w-md w-full border border-gray-700"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center gap-3 mb-4">
                <AlertCircle className="w-8 h-8 text-red-400" />
                <h3 className="text-lg font-bold">确认清空数据?</h3>
              </div>
              <p className="text-gray-400 mb-6">
                此操作将删除所有已扫描的文件记录，无法恢复。
                {stats && `当前共有 ${stats.total_files.toLocaleString()} 条记录。`}
              </p>
              <div className="flex gap-3 justify-end">
                <button
                  onClick={() => setShowConfirmClear(false)}
                  className="px-4 py-2 text-gray-400 hover:text-white transition-colors"
                >
                  取消
                </button>
                <button
                  onClick={handleClearData}
                  className="px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg transition-colors"
                >
                  确认清空
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default GlobalViewPage;
