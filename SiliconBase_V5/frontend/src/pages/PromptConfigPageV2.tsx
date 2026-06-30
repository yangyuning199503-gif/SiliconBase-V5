/**
 * 提示词配置页面 V2 - 集成版
 * SiliconBase V5 - Prompt Configuration Page V2
 * 
 * 功能：
 *   ✓ 集成 SmartTemplateEditor（变体选择 + Token计数）
 *   ✓ 新增 analytics 标签页（失败分析仪表盘）
 *   ✓ 集成 TokenBudgetPanel
 *   ✓ 使用 Zustand store 管理状态
 */

import React, { useEffect, useState } from 'react';
import { 
  FileText, 
  Loader2, 
  Edit3, 
  BarChart3,
  AlertTriangle,
  CheckCircle,
  Save,
  RotateCcw,
  RefreshCw
} from 'lucide-react';
import { SmartTemplateEditor } from '../components/SmartTemplateEditor';
import { FailureAnalyticsDashboard } from '../components/FailureAnalyticsDashboard';
import { usePromptStore } from '../stores/promptStore';


// 标签页类型
type TabId = 'templates' | 'analytics';

// 标签页配置
const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: 'templates', label: '模板编辑', icon: <Edit3 className="w-4 h-4" /> },
  { id: 'analytics', label: '失败分析', icon: <BarChart3 className="w-4 h-4" /> },
];

// 模块类型定义
interface ModuleType {
  key: string;
  name: string;
  vars: string[];
  description: string;
  category: string;
}

// 模板数据
const TEMPLATES: ModuleType[] = [
  { key: 'identity', name: 'AI身份定位', vars: [], description: 'AI的自我认知和核心能力定义', category: '基础设定' },
  { key: 'three_views', name: '三观系统', vars: [], description: '道德观价值观世界观指导', category: '基础设定' },
  { key: 'silicon_life', name: '硅基生命', vars: [], description: '硅基生命体自我认知', category: '基础设定' },
  { key: 'behavior', name: '行为规范', vars: [], description: 'AI行为准则和交互规范', category: '基础设定' },
  { key: 'work_mode', name: '工作模式', vars: [], description: '双模式系统定义', category: '基础设定' },
  { key: 'memory_system', name: '记忆系统', vars: [], description: 'L1-L5五层记忆体系架构', category: '记忆经验' },
  { key: 'memory_strategy', name: '记忆策略', vars: [], description: '记忆管理和检索策略', category: '记忆经验' },
  { key: 'layer_prompts', name: '层级提示词', vars: [], description: 'L1/L2/L3分层导航系统', category: '认知辅助' },
  { key: 'reasoning_framework', name: '推理框架', vars: [], description: '基础推理和决策框架', category: '认知辅助' },
  { key: 'advanced_reasoning', name: '高级推理', vars: [], description: '复杂任务的完整推理流程', category: '认知辅助' },
];

export function PromptConfigPageV2() {
  const [activeTab, setActiveTab] = useState<TabId>('templates');
  const [selectedTemplate, setSelectedTemplate] = useState<string>(TEMPLATES[0].key);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Zustand store
  const store = usePromptStore();
  const {
    modules,
    budgetCategories,
    failureStats,
    loadModules,
    switchVariant,
    updateContent,
    saveModule,
    discardChanges,
    resetToDefault,
    loadFailureStats,
    hasUnsavedChanges,
    editingContent,
  } = store;

  // 初始化加载
  useEffect(() => {
    const init = async () => {
      try {
        setLoading(true);
        await loadModules();
        // 加载完模块后，更新templates的内容
        const moduleKeys = Object.keys(modules);
        if (moduleKeys.length > 0) {
          // 如果store中有模块，同步到本地显示
          console.log('[PromptConfig] 加载模块:', moduleKeys);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : '加载失败');
      } finally {
        setLoading(false);
      }
    };

    init();
  }, []);

  // 切换到analytics标签页时加载失败统计
  useEffect(() => {
    if (activeTab === 'analytics') {
      loadFailureStats();
    }
  }, [activeTab]);

  // 计算总预算使用
  const totalUsed = budgetCategories.reduce((sum, cat) => sum + cat.used, 0);
  const totalBudget = 5100;
  const isOverBudget = totalUsed > totalBudget;

  // 处理保存
  const handleSave = async (key: string, content: string): Promise<boolean> => {
    try {
      // 先更新store
      updateContent(key, content);
      await saveModule(key);
      return true;
    } catch (err) {
      console.error('保存失败:', err);
      return false;
    }
  };

  // 获取变体列表
  const getVariants = (key: string) => {
    const module = modules[key];
    if (module?.variants && module.variants.length > 0) {
      return module.variants;
    }
    
    // 默认变体
    const content = editingContent[key] || module?.content || '';
    const tokens = Math.ceil(content.length / 4);
    return [
      { id: 'default', name: '默认版', description: '标准提示词模板', tokenCount: tokens, failureRate: 0.05, isDefault: true },
      { id: 'concise', name: '精简版', description: '精简提示词，减少Token使用', tokenCount: Math.floor(tokens * 0.4), failureRate: 0.08, isDefault: false },
    ];
  };

  // 获取当前内容
  const getContent = (key: string): string => {
    return editingContent[key] || modules[key]?.content || '';
  };

  // 处理内容变化
  const handleContentChange = (key: string, content: string) => {
    updateContent(key, content);
  };

  // 处理变体切换
  const handleVariantSwitch = async (key: string, variantId: string) => {
    try {
      await switchVariant(key, variantId);
    } catch (err) {
      console.error('切换变体失败:', err);
      setError('切换变体失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  };

  // 手动刷新失败统计
  const handleRefreshStats = async () => {
    await loadFailureStats();
  };

  // 处理恢复默认
  const handleResetToDefault = async (key: string): Promise<void> => {
    try {
      await resetToDefault(key);
    } catch (err) {
      console.error('恢复默认失败:', err);
      setError('恢复默认失败: ' + (err instanceof Error ? err.message : String(err)));
      throw err;
    }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-sb-bg-primary text-sb-text-primary">
        <Loader2 className="w-8 h-8 text-sb-cyan animate-spin" />
        <p className="ml-4 text-sb-text-secondary">加载提示词模块配置...</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-sb-bg-primary text-sb-text-primary">
      {/* 页面头部 */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
        <div className="flex items-center gap-3">
          <FileText className="w-6 h-6 text-sb-cyan" />
          <div>
            <h1 className="text-xl font-bold">提示词配置 V2</h1>
            <p className="text-sm text-sb-text-secondary">
              智能模板编辑 · Token预算管理 · 失败分析
            </p>
          </div>
        </div>

        {/* 总预算指示器 */}
        <div className={`flex items-center gap-3 px-4 py-2 rounded-lg ${
          isOverBudget ? 'bg-red-500/10 border border-red-500/30' : 'bg-white/5'
        }`}>
          <div className="text-right">
            <p className="text-xs text-sb-text-secondary">总Token使用</p>
            <p className={`text-sm font-medium ${isOverBudget ? 'text-red-400' : 'text-sb-cyan'}`}>
              {totalUsed.toLocaleString()} / {totalBudget.toLocaleString()}
            </p>
          </div>
          {isOverBudget ? (
            <AlertTriangle className="w-5 h-5 text-red-400" />
          ) : (
            <CheckCircle className="w-5 h-5 text-green-400" />
          )}
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="mx-6 mt-4 p-3 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300">
            ✕
          </button>
        </div>
      )}

      {/* 标签页导航 */}
      <div className="px-6 border-b border-white/10">
        <div className="flex gap-1">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors border-b-2 ${
                activeTab === tab.id
                  ? 'text-sb-cyan border-sb-cyan'
                  : 'text-sb-text-secondary border-transparent hover:text-sb-text-primary'
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* 主要内容区 */}
      <div className="flex-1 overflow-auto p-6">
        {/* 模板编辑标签页 */}
        {activeTab === 'templates' && (
          <div className="flex gap-6 h-full">
            {/* 左侧模板列表 */}
            <div className="w-64 flex-shrink-0 bg-sb-bg-secondary border border-white/10 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-white/10 bg-white/5">
                <h2 className="font-medium text-sb-text-primary">模板列表</h2>
                <p className="text-xs text-sb-text-secondary mt-1">选择模块进行编辑</p>
              </div>
              <div className="overflow-y-auto max-h-[calc(100vh-300px)]">
                {TEMPLATES.map(template => {
                  const isEditing = editingContent[template.key] !== undefined && editingContent[template.key] !== modules[template.key]?.content;
                  const hasChanges = hasUnsavedChanges[template.key] || isEditing;
                  
                  return (
                    <button
                      key={template.key}
                      onClick={() => setSelectedTemplate(template.key)}
                      className={`w-full text-left px-4 py-3 border-b border-white/5 transition-colors ${
                        selectedTemplate === template.key
                          ? 'bg-sb-cyan/10 border-l-4 border-l-sb-cyan'
                          : 'hover:bg-white/5 border-l-4 border-l-transparent'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-sm">{template.name}</span>
                        {hasChanges && (
                          <span className="w-2 h-2 bg-amber-500 rounded-full" title="有未保存的更改" />
                        )}
                      </div>
                      <p className="text-xs text-sb-text-secondary mt-1 line-clamp-1">
                        {template.description}
                      </p>
                      <span className="text-[10px] text-sb-text-tertiary bg-white/5 px-2 py-0.5 rounded mt-2 inline-block">
                        {template.category}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* 右侧编辑区 */}
            <div className="flex-1 flex flex-col gap-4">
              {selectedTemplate && (
                <>
                  <SmartTemplateEditor
                    templateKey={selectedTemplate}
                    templateName={TEMPLATES.find(t => t.key === selectedTemplate)?.name || ''}
                    content={getContent(selectedTemplate)}
                    variables={TEMPLATES.find(t => t.key === selectedTemplate)?.vars || []}
                    variants={getVariants(selectedTemplate)}
                    selectedVariant={modules[selectedTemplate]?.currentVariant || 'default'}
                    onSwitchVariant={(v) => handleVariantSwitch(selectedTemplate, v)}
                    onSave={(content) => handleSave(selectedTemplate, content)}
                    onChange={(content) => handleContentChange(selectedTemplate, content)}
                    onResetToDefault={() => handleResetToDefault(selectedTemplate)}
                    hasUnsavedChanges={hasUnsavedChanges[selectedTemplate]}
                    budgetCategories={budgetCategories.reduce((acc, cat) => {
                      acc[cat.name] = cat;
                      return acc;
                    }, {} as Record<string, any>)}
                    totalBudget={totalBudget}
                    totalUsed={totalUsed}
                    isOverBudget={isOverBudget}
                  />
                  
                  {/* 快速操作栏 */}
                  <div className="flex items-center justify-between bg-sb-bg-secondary border border-white/10 rounded-lg px-4 py-3">
                    <div className="flex items-center gap-4 text-sm text-sb-text-secondary">
                      <span>
                        当前模块: <span className="text-sb-text-primary">{TEMPLATES.find(t => t.key === selectedTemplate)?.name}</span>
                      </span>
                      <span className="text-sb-text-tertiary">|</span>
                      <span>
                        Token: <span className="text-sb-cyan">{Math.ceil(getContent(selectedTemplate).length / 4)}</span>
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {hasUnsavedChanges[selectedTemplate] && (
                        <button
                          onClick={() => discardChanges(selectedTemplate)}
                          className="flex items-center gap-2 px-3 py-1.5 text-sm text-sb-text-secondary hover:text-sb-text-primary hover:bg-white/5 rounded-lg transition-colors"
                        >
                          <RotateCcw className="w-4 h-4" />
                          丢弃更改
                        </button>
                      )}
                      <button
                        onClick={() => handleSave(selectedTemplate, getContent(selectedTemplate))}
                        disabled={!hasUnsavedChanges[selectedTemplate]}
                        className="flex items-center gap-2 px-4 py-1.5 text-sm bg-sb-cyan/20 text-sb-cyan rounded-lg hover:bg-sb-cyan/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        <Save className="w-4 h-4" />
                        保存更改
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        {/* 失败分析标签页 */}
        {activeTab === 'analytics' && (
          <div className="space-y-4">
            {/* 统计刷新按钮 */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <BarChart3 className="w-5 h-5 text-sb-cyan" />
                <h2 className="text-lg font-medium">失败分析与优化建议</h2>
              </div>
              <button
                onClick={handleRefreshStats}
                className="flex items-center gap-2 px-3 py-1.5 text-sm text-sb-text-secondary hover:text-sb-text-primary hover:bg-white/5 rounded-lg transition-colors"
              >
                <RefreshCw className="w-4 h-4" />
                刷新统计
              </button>
            </div>
            
            <FailureAnalyticsDashboard />
            
            {/* 统计摘要 */}
            {failureStats && (
              <div className="grid grid-cols-4 gap-4 mt-6">
                <div className="bg-sb-bg-secondary border border-white/10 rounded-lg p-4">
                  <p className="text-xs text-sb-text-secondary">总失败次数</p>
                  <p className="text-2xl font-bold text-sb-text-primary">{failureStats.total}</p>
                </div>
                <div className="bg-sb-bg-secondary border border-white/10 rounded-lg p-4">
                  <p className="text-xs text-sb-text-secondary">近7天失败</p>
                  <p className="text-2xl font-bold text-sb-text-primary">{failureStats.recent7Days}</p>
                </div>
                <div className="bg-sb-bg-secondary border border-white/10 rounded-lg p-4">
                  <p className="text-xs text-sb-text-secondary">趋势</p>
                  <p className={`text-2xl font-bold ${
                    failureStats.trend === 'up' ? 'text-red-400' : 
                    failureStats.trend === 'down' ? 'text-green-400' : 'text-sb-text-secondary'
                  }`}>
                    {failureStats.trend === 'up' ? '上升 ↑' : 
                     failureStats.trend === 'down' ? '下降 ↓' : '稳定 —'}
                  </p>
                </div>
                <div className="bg-sb-bg-secondary border border-white/10 rounded-lg p-4">
                  <p className="text-xs text-sb-text-secondary">主要问题类型</p>
                  <p className="text-lg font-bold text-sb-text-primary truncate">
                    {failureStats.topIssues[0]?.cause || '无数据'}
                  </p>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default PromptConfigPageV2;
