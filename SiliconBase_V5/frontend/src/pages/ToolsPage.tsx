/**
 * 工具管理页面 - 支持热插拔
 * 新增：使用手册功能（从PromptConfigPage移入的层级导航）
 * 修改：显示所有工具（包括废弃的），但有视觉标记和确认提示
 * 新增：本地/云端双版本UI差异化支持
 */
import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Wrench, Search, Play, ChevronRight, Folder,
  AlertCircle, CheckCircle, XCircle, Plus,
  Code, Trash2, RefreshCw, BookOpen, AlertTriangle,
  Monitor, Cloud
} from 'lucide-react';
import { toolsAPI, Tool, ToolTestResult } from '../utils/api/tools';
import { useNotifications } from '../hooks/useNotifications';
import { PromptLayerNavigator } from '../components/PromptLayerNavigator';

// 部署模式（从后端获取或环境变量）
const DEPLOY_MODE = import.meta.env.VITE_DEPLOY_MODE || 'local';

// 扩展 Tool 类型以包含废弃相关字段和双模式字段
interface ToolWithStatus extends Tool {
  deprecated?: boolean;
  deprecated_reason?: string;
  is_duplicate?: boolean;
  duplicate_of?: string;
  owner?: 'system' | 'user' | 'custom';
  executable?: boolean;
  exec_restriction?: string;
  warning?: string;
}

// 简单 Modal 组件
interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  type?: 'confirm' | 'warning' | 'info';
}

const Modal = ({ isOpen, title, children, footer, type = 'info' }: ModalProps) => {
  if (!isOpen) return null;

  const getTitleColor = () => {
    switch (type) {
      case 'warning': return 'text-yellow-400';
      case 'confirm': return 'text-sb-cyan';
      default: return 'text-white';
    }
  };

  const getIcon = () => {
    switch (type) {
      case 'warning': return <AlertTriangle className="w-6 h-6 text-yellow-400" />;
      case 'confirm': return <AlertCircle className="w-6 h-6 text-sb-cyan" />;
      default: return null;
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="bg-sb-bg-secondary border border-white/10 rounded-xl w-full max-w-md m-4 shadow-2xl"
      >
        <div className="p-6">
          <div className="flex items-center gap-3 mb-4">
            {getIcon()}
            <h3 className={`text-lg font-semibold ${getTitleColor()}`}>{title}</h3>
          </div>
          <div className="text-sb-text-secondary">
            {children}
          </div>
        </div>
        {footer && (
          <div className="px-6 py-4 border-t border-white/10 flex justify-end gap-3">
            {footer}
          </div>
        )}
      </motion.div>
    </div>
  );
};

// 工具状态标签组件
const ToolStatusTags = ({ tool }: { tool: ToolWithStatus }) => (
  <div className="flex gap-1 flex-wrap">
    {tool.owner === 'custom' && (
      <span className="text-xs bg-blue-500 text-white px-2 py-0.5 rounded">
        自定义
      </span>
    )}
    {tool.deprecated && (
      <span className="text-xs bg-red-500 text-white px-2 py-0.5 rounded">
        已废弃
      </span>
    )}
    {tool.duplicate_of && (
      <span className="text-xs bg-orange-500 text-white px-2 py-0.5 rounded">
        重复
      </span>
    )}
    {!tool.executable && (
      <span className="text-xs bg-gray-500 text-white px-2 py-0.5 rounded">
        不可执行
      </span>
    )}
  </div>
);

// 部署模式指示器
const DeployModeIndicator = () => (
  <div className="fixed top-4 right-4 z-50">
    {DEPLOY_MODE === 'local' ? (
      <span className="px-3 py-1.5 bg-green-500/20 text-green-400 rounded-full text-sm flex items-center gap-2 border border-green-500/30">
        <Monitor className="w-4 h-4" />
        本地模式
      </span>
    ) : (
      <span className="px-3 py-1.5 bg-blue-500/20 text-blue-400 rounded-full text-sm flex items-center gap-2 border border-blue-500/30">
        <Cloud className="w-4 h-4" />
        云端模式
      </span>
    )}
  </div>
);

// 工具详情面板
function ToolDetailPanel({
  tool,
  onClose,
  onTest,
  onDelete
}: {
  tool: ToolWithStatus;
  onClose: () => void;
  onTest: (params: Record<string, any>) => Promise<ToolTestResult>;
  onDelete: () => void;
}) {
  const [testParams, setTestParams] = useState('{}');
  const [testResult, setTestResult] = useState<ToolTestResult | null>(null);
  const [testing, setTesting] = useState(false);

  const handleTest = async () => {
    try {
      setTesting(true);
      const params = JSON.parse(testParams);
      const result = await onTest(params);
      if (result) {
        setTestResult(result);
      }
    } catch (e: any) {
      setTestResult({
        success: false,
        tool_id: tool.id,
        result: null,
        error: e.message || '测试失败',
        timestamp: Date.now()
      });
    } finally {
      setTesting(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: 300 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 300 }}
      className="fixed right-0 top-0 h-full w-96 bg-sb-bg-secondary border-l border-white/10 shadow-2xl z-50 overflow-auto"
    >
      <div className="p-6 space-y-6">
        {/* 头部 */}
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-xl font-bold text-white">{tool.name}</h2>
              <ToolStatusTags tool={tool} />
            </div>
            <p className="text-sm text-sb-text-secondary mt-1">{tool.category}</p>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/10 rounded-lg transition-colors"
          >
            <XCircle className="w-5 h-5 text-sb-text-secondary" />
          </button>
        </div>

        {/* 不可执行警告（云端模式） */}
        {!tool.executable && DEPLOY_MODE === 'cloud' && (
          <div className="bg-gray-500/10 border border-gray-500/30 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <AlertCircle className="w-5 h-5 text-gray-400" />
              <span className="text-gray-400 font-medium">此工具在当前环境下不可执行</span>
            </div>
            {tool.exec_restriction && (
              <p className="text-sm text-gray-400">{tool.exec_restriction}</p>
            )}
          </div>
        )}

        {/* 废弃警告 */}
        {tool.deprecated && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <AlertCircle className="w-5 h-5 text-red-400" />
              <span className="text-red-400 font-medium">此工具已废弃</span>
            </div>
            {tool.deprecated_reason && (
              <p className="text-sm text-red-400">{tool.deprecated_reason}</p>
            )}
            {DEPLOY_MODE === 'local' && (
              <p className="text-xs text-yellow-400 mt-2">
                本地模式下仍可执行，但可能存在风险
              </p>
            )}
          </div>
        )}

        {/* 功能重复警告 */}
        {tool.duplicate_of && (
          <div className="bg-orange-500/10 border border-orange-500/30 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle className="w-5 h-5 text-orange-400" />
              <span className="text-orange-400 font-medium">功能重复</span>
            </div>
            {tool.duplicate_of && (
              <p className="text-sm text-orange-400">
                建议使用替代工具: {tool.duplicate_of}
              </p>
            )}
          </div>
        )}

        {/* 自定义工具标记 */}
        {tool.owner === 'custom' && (
          <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
            <div className="flex items-center gap-2">
              <Code className="w-5 h-5 text-blue-400" />
              <span className="text-blue-400 font-medium">自定义工具</span>
            </div>
          </div>
        )}

        {/* 描述 */}
        <p className="text-white/80">{tool.description}</p>

        {/* 参数 */}
        {tool.parameters && Object.keys(tool.parameters).length > 0 && (
          <div>
            <h3 className="text-sm font-medium text-sb-text-secondary mb-3">参数</h3>
            <div className="space-y-2">
              {Object.entries(tool.parameters).map(([key, value]: [string, any]) => (
                <div key={key} className="bg-sb-bg-primary rounded-lg p-3">
                  <div className="flex items-center justify-between">
                    <code className="text-sb-cyan text-sm">{key}</code>
                    <span className="text-xs text-sb-text-secondary">{value.type}</span>
                  </div>
                  {value.description && (
                    <p className="text-xs text-sb-text-secondary mt-1">{value.description}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 测试区域 - 根据可执行状态显示 */}
        <div className="border-t border-white/10 pt-4">
          <h3 className="text-sm font-medium text-sb-text-secondary mb-3">测试工具</h3>
          <textarea
            value={testParams}
            onChange={(e) => setTestParams(e.target.value)}
            placeholder='{"param": "value"}'
            rows={4}
            disabled={DEPLOY_MODE === 'cloud' && !tool.executable}
            className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-4 py-2 text-white text-sm focus:border-sb-cyan outline-none resize-none font-mono disabled:opacity-50 disabled:cursor-not-allowed"
          />
          <button
            onClick={handleTest}
            disabled={testing || (DEPLOY_MODE === 'cloud' && !tool.executable)}
            className="w-full mt-3 flex items-center justify-center gap-2 px-4 py-2 bg-sb-cyan text-sb-bg-primary rounded-lg hover:bg-sb-cyan-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Play className="w-4 h-4" />
            {testing ? '测试中...' : DEPLOY_MODE === 'cloud' && !tool.executable ? '不可执行' : '运行测试'}
          </button>
        </div>

        {/* 测试结果 */}
        {testResult && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className={`p-4 rounded-lg ${
              testResult.success ? 'bg-green-500/10 border border-green-500/30' : 'bg-red-500/10 border border-red-500/30'
            }`}
          >
            <div className="flex items-center gap-2 mb-2">
              {testResult.success ? (
                <CheckCircle className="w-5 h-5 text-green-400" />
              ) : (
                <AlertCircle className="w-5 h-5 text-red-400" />
              )}
              <span className={testResult.success ? 'text-green-400' : 'text-red-400'}>
                {testResult.success ? '测试成功' : '测试失败'}
              </span>
            </div>
            <pre className="text-xs text-sb-text-secondary overflow-auto max-h-40">
              {JSON.stringify(testResult.result || testResult.error, null, 2)}
            </pre>
          </motion.div>
        )}

        {/* 删除按钮 - 仅自定义工具可删除 */}
        {tool.owner === 'custom' && (
          <div className="border-t border-white/10 pt-4">
            <button
              onClick={onDelete}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors"
            >
              <Trash2 className="w-4 h-4" />
              删除工具
            </button>
          </div>
        )}
      </div>
    </motion.div>
  );
}

// 添加工具对话框
function AddToolDialog({
  isOpen,
  onClose,
  onAdd
}: {
  isOpen: boolean;
  onClose: () => void;
  onAdd: (name: string, description: string, code: string, skipSandbox: boolean) => Promise<void>;
}) {
  const [code, setCode] = useState(`# 示例：创建一个简单的工具
from core.base_tool import BaseTool
from typing import Dict, Any

class MyCustomTool(BaseTool):
    tool_id = "my_custom_tool"
    name = "我的自定义工具"
    description = "这是一个示例工具"
    
    input_schema = {
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "输入参数"}
        },
        "required": ["input"]
    }
    
    def run(self, input: str) -> Dict[str, Any]:
        return {
            "success": True,
            "error_code": "",
            "user_message": f"处理结果: {input}",
            "data": {"result": input.upper()}
        }
`);
  const [adding, setAdding] = useState(false);
  const [skipSandbox, setSkipSandbox] = useState(false);
  const [toolName, setToolName] = useState('');
  const [toolDescription, setToolDescription] = useState('');

  const handleSubmit = async () => {
    try {
      setAdding(true);
      await onAdd(toolName, toolDescription, code, skipSandbox);
      onClose();
    } finally {
      setAdding(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="bg-sb-bg-secondary border border-white/10 rounded-xl w-full max-w-2xl m-4 max-h-[80vh] flex flex-col"
      >
        <div className="p-4 border-b border-white/10 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Code className="w-5 h-5 text-sb-cyan" />
            <h3 className="text-lg font-medium text-white">添加自定义工具</h3>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-white/10 rounded">
            <XCircle className="w-5 h-5 text-sb-text-secondary" />
          </button>
        </div>
        
        <div className="p-4 flex-1 overflow-auto space-y-4">
          <div>
            <label className="block text-sm text-sb-text-secondary mb-1">工具名称</label>
            <input
              type="text"
              value={toolName}
              onChange={(e) => setToolName(e.target.value)}
              placeholder="输入工具名称"
              className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-4 py-2 text-white text-sm focus:border-sb-cyan outline-none"
            />
          </div>
          <div>
            <label className="block text-sm text-sb-text-secondary mb-1">工具描述</label>
            <input
              type="text"
              value={toolDescription}
              onChange={(e) => setToolDescription(e.target.value)}
              placeholder="输入工具描述"
              className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-4 py-2 text-white text-sm focus:border-sb-cyan outline-none"
            />
          </div>
          <div>
            <p className="text-sm text-sb-text-secondary mb-2">
              编写 Python 代码定义工具类，必须继承 BaseTool
            </p>
            <textarea
              value={code}
              onChange={(e) => setCode(e.target.value)}
              rows={12}
              className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-4 py-2 text-white text-sm focus:border-sb-cyan outline-none resize-none font-mono"
            />
          </div>
        </div>
        
        <div className="p-4 border-t border-white/10">
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-2 text-sm text-sb-text-secondary cursor-pointer">
              <input
                type="checkbox"
                checked={skipSandbox}
                onChange={(e) => setSkipSandbox(e.target.checked)}
                className="w-4 h-4 rounded border-white/20 bg-sb-bg-primary text-sb-cyan focus:ring-sb-cyan"
              />
              跳过沙箱测试（仅用于测试）
            </label>
            <div className="flex items-center gap-3">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sb-text-secondary hover:text-white transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleSubmit}
                disabled={adding}
                className="flex items-center gap-2 px-4 py-2 bg-sb-cyan text-sb-bg-primary rounded-lg hover:bg-sb-cyan-hover transition-colors disabled:opacity-50"
              >
                <Plus className="w-4 h-4" />
                {adding ? '添加中...' : '添加工具'}
              </button>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

export function ToolsPage() {
  const [categories, setCategories] = useState<{ name: string; count: number }[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [tools, setTools] = useState<ToolWithStatus[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<ToolWithStatus[]>([]);
  const [selectedTool, setSelectedTool] = useState<ToolWithStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [showManual, setShowManual] = useState(false);
  const { showNotification } = useNotifications();

  // Modal 状态
  const [modalConfig, setModalConfig] = useState<{
    isOpen: boolean;
    type: 'confirm' | 'warning' | 'info';
    title: string;
    content: React.ReactNode;
    onOk?: () => void;
    onCancel?: () => void;
  }>({
    isOpen: false,
    type: 'info',
    title: '',
    content: null
  });

  const loadCategories = useCallback(async () => {
    try {
      setError(null);
      const data = await toolsAPI.getCategories();
      console.log('[ToolsPage] 加载分类:', data);
      const validCategories = (data.categories || []).filter((c: {name: string, count: number}) => c && c.name);
      setCategories(validCategories);
      if (validCategories.length > 0 && !selectedCategory) {
        setSelectedCategory(validCategories[0].name);
      }
    } catch (err) {
      console.error('[ToolsPage] 加载分类失败:', err);
      setError(err instanceof Error ? err.message : '加载分类失败');
      setCategories([]);
    }
  }, [selectedCategory]);

  const loadToolsByCategory = useCallback(async (category: string) => {
    try {
      setLoading(true);
      setError(null);
      const data = await toolsAPI.getToolsByCategory(category);
      console.log('[ToolsPage] 加载工具:', category, data);
      // 显示所有工具，不再过滤废弃工具
      const validTools = (data.tools || []).filter((t: ToolWithStatus) => 
        t && t.id && t.name
      );
      setTools(validTools);
    } catch (err) {
      console.error('[ToolsPage] 加载工具失败:', err);
      setError(err instanceof Error ? err.message : '加载工具失败');
      setTools([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }
    try {
      const data = await toolsAPI.searchTools(searchQuery);
      // 搜索结果也不过滤废弃工具
      setSearchResults(data.results as ToolWithStatus[]);
    } catch (err) {
      console.error('搜索失败:', err);
    }
  }, [searchQuery]);

  // 工具卡片样式（根据状态）
  const getToolCardClass = (tool: ToolWithStatus) => {
    let base = "tool-card p-4 rounded-lg border cursor-pointer transition-all group";
    
    if (tool.deprecated) {
      base += " bg-gray-500/10 border-gray-500/30 opacity-60"; // 灰色半透明
    } else if (tool.duplicate_of) {
      base += " bg-orange-500/10 border-orange-500/30"; // 橙色边框（重复）
    } else if (tool.owner === 'custom') {
      base += " bg-blue-500/10 border-blue-500/30"; // 蓝色标记（自定义）
    } else {
      base += " bg-white/5 border-white/10 hover:bg-white/10 hover:border-sb-cyan/30"; // 正常
    }
    
    if (!tool.executable) {
      base += " cursor-not-allowed";
    }
    
    return base;
  };

  // 点击处理（差异化）
  const handleToolClick = useCallback((tool: ToolWithStatus) => {
    // 云端模式 + 不可执行：弹提示，无法执行
    if (DEPLOY_MODE === 'cloud' && !tool.executable) {
      setModalConfig({
        isOpen: true,
        type: 'warning',
        title: '无法执行',
        content: (
          <div>
            <p>{tool.exec_restriction || '此工具在当前环境下不可执行'}</p>
          </div>
        ),
        onOk: () => setModalConfig(prev => ({ ...prev, isOpen: false }))
      });
      return;
    }
    
    // 本地模式 + 废弃工具：弹确认框，确认后可查看/执行
    if (DEPLOY_MODE === 'local' && tool.deprecated) {
      setModalConfig({
        isOpen: true,
        type: 'confirm',
        title: '⚠️ 警告：此工具已废弃',
        content: (
          <div className="space-y-2">
            <p>原因：{tool.deprecated_reason || '无'}</p>
            {tool.duplicate_of && (
              <p>推荐使用：{tool.duplicate_of}</p>
            )}
            <p className="mt-2 text-yellow-400">
              本地模式下仍可执行，但可能存在风险，是否继续？
            </p>
          </div>
        ),
        onOk: () => {
          setModalConfig(prev => ({ ...prev, isOpen: false }));
          setSelectedTool(tool);
        },
        onCancel: () => {
          setModalConfig(prev => ({ ...prev, isOpen: false }));
        }
      });
      return;
    }
    
    // 云端模式 + 废弃工具：显示警告但不阻止查看
    if (DEPLOY_MODE === 'cloud' && tool.deprecated) {
      console.log(`[ToolsPage] 废弃工具查看: ${tool.name}, 原因: ${tool.deprecated_reason}`);
    }
    
    // 功能重复工具显示提示但不阻止
    if (tool.duplicate_of) {
      console.log(`[ToolsPage] 功能重复工具: ${tool.name}, 建议使用: ${tool.duplicate_of}`);
    }
    
    // 正常打开详情
    setSelectedTool(tool);
  }, []);

  const handleTestTool = async (toolId: string, params: Record<string, any>) => {
    return toolsAPI.testTool(toolId, params);
  };

  const handleDeleteTool = async (toolId: string) => {
    try {
      await toolsAPI.deleteTool(toolId);
      setTools(prev => prev.filter(t => t.id !== toolId));
      setSelectedTool(null);
      showNotification({
        type: 'success',
        title: '删除成功',
        message: '工具已删除'
      });
    } catch (err: any) {
      showNotification({
        type: 'error',
        title: '删除失败',
        message: err.message
      });
    }
  };

  const handleAddTool = async (name: string, description: string, code: string, skipSandbox: boolean = false) => {
    try {
      const result = await toolsAPI.registerTool(name, description, code, skipSandbox);
      if (result.success) {
        showNotification({
          type: 'success',
          title: '添加成功',
          message: `工具 ${result.tool_id} 已注册`
        });
        loadCategories();
      } else {
        throw new Error(result.error || '注册失败');
      }
    } catch (err: any) {
      showNotification({
        type: 'error',
        title: '添加失败',
        message: err.message
      });
      throw err;
    }
  };

  useEffect(() => {
    loadCategories();
  }, [loadCategories]);

  useEffect(() => {
    if (selectedCategory) {
      loadToolsByCategory(selectedCategory);
    }
  }, [selectedCategory, loadToolsByCategory]);

  useEffect(() => {
    const timer = setTimeout(handleSearch, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, handleSearch]);

  const displayTools = searchQuery ? searchResults : tools;

  return (
    <div className="h-full flex overflow-hidden">
      {/* 部署模式指示器 */}
      <DeployModeIndicator />

      {/* 左侧分类栏 */}
      <div className="w-64 bg-sb-bg-secondary/30 border-r border-white/5 flex flex-col">
        <div className="p-4 border-b border-white/5 flex items-center justify-between">
          <div className="flex items-center gap-2 text-white font-medium">
            <Folder className="w-5 h-5 text-sb-cyan" />
            分类
          </div>
          <button
            onClick={() => setShowAddDialog(true)}
            className="p-1.5 bg-sb-cyan/20 text-sb-cyan rounded hover:bg-sb-cyan/30 transition-colors"
            title="添加自定义工具"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-2 space-y-1">
          {categories.map((category) => (
            <button
              key={category.name}
              onClick={() => {
                setSelectedCategory(category.name);
                setSearchQuery('');
                setShowManual(false);
              }}
              className={`w-full flex items-center justify-between px-4 py-3 rounded-lg text-left transition-colors ${
                selectedCategory === category.name && !showManual
                  ? 'bg-sb-cyan/20 text-sb-cyan'
                  : 'text-sb-text-secondary hover:bg-white/5 hover:text-white'
              }`}
            >
              <span>{category.name}</span>
              <span className="text-xs bg-white/10 px-2 py-0.5 rounded">
                {category.count}
              </span>
            </button>
          ))}
          
          {/* 使用手册按钮 */}
          <button
            onClick={() => setShowManual(true)}
            className={`w-full flex items-center justify-between px-4 py-3 rounded-lg text-left transition-colors ${
              showManual
                ? 'bg-sb-cyan/20 text-sb-cyan'
                : 'text-sb-text-secondary hover:bg-white/5 hover:text-white'
            }`}
          >
            <span className="flex items-center gap-2">
              <BookOpen className="w-4 h-4" />
              使用手册
            </span>
            <span className="text-xs bg-white/10 px-2 py-0.5 rounded">
              L1/L2/L3
            </span>
          </button>
        </div>
      </div>

      {/* 右侧内容区 */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* 搜索栏 */}
        <div className="p-4 border-b border-white/5 flex items-center gap-4">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-sb-text-secondary" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索工具..."
              className="w-full bg-sb-bg-secondary border border-white/10 rounded-lg pl-10 pr-4 py-2 text-white focus:border-sb-cyan outline-none"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-sb-text-secondary hover:text-white"
              >
                <XCircle className="w-4 h-4" />
              </button>
            )}
          </div>
          <button
            onClick={loadCategories}
            className="p-2 text-sb-text-secondary hover:text-white transition-colors"
          >
            <RefreshCw className="w-5 h-5" />
          </button>
        </div>

        {/* 工具列表或使用手册 */}
        <div className="flex-1 overflow-auto p-4">
          {showManual ? (
            // 使用手册模式
            <div className="h-full">
              <PromptLayerNavigator 
                onLayerChange={(layer, data) => {
                  console.log('[使用手册] 层级切换:', layer, data);
                }}
              />
            </div>
          ) : loading ? (
            <div className="flex items-center justify-center h-full">
              <motion.div
                animate={{ rotate: 360 }}
                transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                className="w-8 h-8 border-2 border-sb-cyan border-t-transparent rounded-full"
              />
            </div>
          ) : error ? (
            <div className="flex items-center justify-center h-full text-red-400">
              <AlertCircle className="w-5 h-5 mr-2" />
              {error}
            </div>
          ) : displayTools.length === 0 ? (
            <div className="flex items-center justify-center h-full text-sb-text-secondary">
              暂无工具
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {displayTools.map((tool, index) => (
                <motion.div
                  key={tool.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                  onClick={() => handleToolClick(tool)}
                  className={getToolCardClass(tool)}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`p-2 rounded-lg ${
                        tool.deprecated 
                          ? 'bg-gray-500/20' 
                          : tool.duplicate_of 
                            ? 'bg-orange-500/20' 
                            : tool.owner === 'custom'
                              ? 'bg-blue-500/20'
                              : tool.enabled 
                                ? 'bg-sb-cyan/20' 
                                : 'bg-white/5'
                      }`}>
                        <Wrench className={`w-5 h-5 ${
                          tool.deprecated 
                            ? 'text-gray-400' 
                            : tool.duplicate_of 
                              ? 'text-orange-400' 
                              : tool.owner === 'custom'
                                ? 'text-blue-400'
                                : tool.enabled 
                                  ? 'text-sb-cyan' 
                                  : 'text-sb-text-secondary'
                        }`} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <h3 className={`font-medium transition-colors truncate ${
                            tool.deprecated 
                              ? 'text-gray-400 group-hover:text-gray-300' 
                              : 'text-white group-hover:text-sb-cyan'
                          }`}>
                            {tool.name}
                          </h3>
                        </div>
                        <p className="text-xs text-sb-text-secondary">{tool.category}</p>
                        {/* 状态标签 */}
                        <div className="mt-1">
                          <ToolStatusTags tool={tool} />
                        </div>
                      </div>
                    </div>
                    <ChevronRight className={`w-4 h-4 ${
                      tool.deprecated 
                        ? 'text-gray-500' 
                        : 'text-sb-text-secondary'
                    }`} />
                  </div>
                  <p className="mt-3 text-sm text-sb-text-secondary line-clamp-2">
                    {tool.description}
                  </p>
                  {tool.warning && (
                    <p className="mt-2 text-xs text-yellow-400">
                      ⚠️ {tool.warning}
                    </p>
                  )}
                </motion.div>
              ))}
            </div>
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
              onClose={() => setSelectedTool(null)}
              onTest={(params) => handleTestTool(selectedTool.id, params)}
              onDelete={() => handleDeleteTool(selectedTool.id)}
            />
          </>
        )}
      </AnimatePresence>

      {/* 添加工具对话框 */}
      <AddToolDialog
        isOpen={showAddDialog}
        onClose={() => setShowAddDialog(false)}
        onAdd={handleAddTool}
      />

      {/* 通用 Modal */}
      <Modal
        isOpen={modalConfig.isOpen}
        type={modalConfig.type}
        title={modalConfig.title}
        onClose={() => setModalConfig(prev => ({ ...prev, isOpen: false }))}
        footer={
          modalConfig.type === 'confirm' ? (
            <>
              <button
                onClick={modalConfig.onCancel}
                className="px-4 py-2 text-sb-text-secondary hover:text-white transition-colors rounded-lg"
              >
                取消
              </button>
              <button
                onClick={modalConfig.onOk}
                className="px-4 py-2 bg-sb-cyan text-sb-bg-primary rounded-lg hover:bg-sb-cyan-hover transition-colors"
              >
                仍要执行
              </button>
            </>
          ) : (
            <button
              onClick={modalConfig.onOk}
              className="px-4 py-2 bg-sb-cyan text-sb-bg-primary rounded-lg hover:bg-sb-cyan-hover transition-colors"
            >
              确定
            </button>
          )
        }
      >
        {modalConfig.content}
      </Modal>
    </div>
  );
}
