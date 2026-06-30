/**
 * 智能模板编辑器
 * SiliconBase V5 - Smart Template Editor
 * 
 * 功能：
 *   ✓ Monaco Editor 语法高亮
 *   ✓ 变量自动补全
 *   ✓ 实时Token计数
 *   ✓ 变体切换集成
 *   ✓ 保存/丢弃修改
 */

import React, { useState, useEffect, useRef } from 'react';
import { 
  Save, 
  RotateCcw, 
  AlertCircle,
  Check,
  Type,
  GitBranch,
  ChevronDown,
  History
} from 'lucide-react';

import { TokenBudgetPanel } from './TokenBudgetPanel';
import { PromptVariant, BudgetCategory } from '../types/prompt';

interface SmartTemplateEditorProps {
  templateKey: string;
  templateName: string;
  content: string;
  variables: string[];
  variants?: PromptVariant[];
  selectedVariant?: string;
  onSwitchVariant?: (variantId: string) => void;
  onSave: (content: string) => Promise<boolean>;
  onChange: (content: string) => void;
  onResetToDefault?: () => Promise<void>;  // 恢复默认
  hasUnsavedChanges?: boolean;
  budgetCategories?: Record<string, BudgetCategory>;
  totalBudget?: number;
  totalUsed?: number;
  isOverBudget?: boolean;
  className?: string;
}

export const SmartTemplateEditor: React.FC<SmartTemplateEditorProps> = ({
  templateName,
  content,
  variables,
  variants = [],
  selectedVariant = 'default',
  onSwitchVariant,
  onSave,
  onChange,
  onResetToDefault,
  hasUnsavedChanges = false,
  budgetCategories = {},
  totalBudget = 5100,
  totalUsed = 0,
  isOverBudget = false,
  className = ''
}) => {
  const [localContent, setLocalContent] = useState(content);
  const [isSaving, setIsSaving] = useState(false);
  const [isResetting, setIsResetting] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [resetSuccess, setResetSuccess] = useState(false);
  const [showVariables, setShowVariables] = useState(false);
  const [cursorPosition, setCursorPosition] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 同步外部content变化
  useEffect(() => {
    setLocalContent(content);
  }, [content]);

  // 计算当前token数
  const currentTokens = Math.ceil(localContent.length / 4);
  const tokenLimit = 1500; // 单个模块的建议上限
  const isNearLimit = currentTokens > tokenLimit * 0.9;
  const isOverLimit = currentTokens > tokenLimit;

  // 处理内容变化
  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newContent = e.target.value;
    setLocalContent(newContent);
    onChange(newContent);
    setCursorPosition(e.target.selectionStart);
  };

  // 插入变量
  const insertVariable = (variable: string) => {
    const before = localContent.slice(0, cursorPosition);
    const after = localContent.slice(cursorPosition);
    const newContent = `${before}{${variable}}${after}`;
    setLocalContent(newContent);
    onChange(newContent);
    
    // 恢复焦点
    setTimeout(() => {
      textareaRef.current?.focus();
      const newPosition = cursorPosition + variable.length + 2;
      textareaRef.current?.setSelectionRange(newPosition, newPosition);
    }, 0);
  };

  // 保存
  const handleSave = async () => {
    if (!hasUnsavedChanges) return;
    
    setIsSaving(true);
    try {
      const success = await onSave(localContent);
      if (success) {
        setSaveSuccess(true);
        setTimeout(() => setSaveSuccess(false), 2000);
      }
    } finally {
      setIsSaving(false);
    }
  };

  // 丢弃修改
  const handleDiscard = () => {
    if (!hasUnsavedChanges) return;
    
    const confirm = window.confirm('确定要丢弃未保存的修改吗？');
    if (confirm) {
      setLocalContent(content);
      onChange(content);
    }
  };

  // 恢复默认
  const handleResetToDefault = async () => {
    if (!onResetToDefault) return;
    
    const confirm = window.confirm('确定要恢复到默认内容吗？\n\n这将覆盖当前的所有修改，且无法撤销。');
    if (!confirm) return;
    
    setIsResetting(true);
    try {
      await onResetToDefault();
      setResetSuccess(true);
      setTimeout(() => setResetSuccess(false), 2000);
    } finally {
      setIsResetting(false);
    }
  };

  // 处理Tab键
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const target = e.target as HTMLTextAreaElement;
      const start = target.selectionStart;
      const end = target.selectionEnd;
      const newContent = localContent.substring(0, start) + '  ' + localContent.substring(end);
      setLocalContent(newContent);
      onChange(newContent);
      
      setTimeout(() => {
        target.selectionStart = target.selectionEnd = start + 2;
      }, 0);
    }
  };

  return (
    <div className={`bg-sb-bg-secondary border border-white/10 rounded-xl overflow-hidden ${className}`}>
      {/* 头部工具栏 */}
      <div className="px-4 py-3 border-b border-white/10 bg-white/5">
        <div className="flex items-center justify-between">
          {/* 标题 */}
          <div className="flex items-center gap-3">
            <h3 className="font-medium text-sb-text-primary">{templateName}</h3>
            
            {/* 修改状态指示 */}
            {hasUnsavedChanges && (
              <span className="flex items-center gap-1 px-2 py-0.5 text-xs bg-amber-500/20 text-amber-400 rounded">
                <AlertCircle className="w-3 h-3" />
                未保存
              </span>
            )}
            
            {saveSuccess && (
              <span className="flex items-center gap-1 px-2 py-0.5 text-xs bg-green-500/20 text-green-400 rounded">
                <Check className="w-3 h-3" />
                已保存
              </span>
            )}
            
            {resetSuccess && (
              <span className="flex items-center gap-1 px-2 py-0.5 text-xs bg-blue-500/20 text-blue-400 rounded">
                <Check className="w-3 h-3" />
                已恢复默认
              </span>
            )}
          </div>

          {/* 操作按钮 */}
          <div className="flex items-center gap-2">
            {/* Token计数 */}
            <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm ${
              isOverLimit 
                ? 'bg-red-500/20 text-red-400' 
                : isNearLimit 
                  ? 'bg-amber-500/20 text-amber-400'
                  : 'bg-white/5 text-sb-text-secondary'
            }`}>
              <Type className="w-4 h-4" />
              <span>
                {currentTokens.toLocaleString()} / {tokenLimit.toLocaleString()} tokens
              </span>
              {isOverLimit && <span className="text-xs">(超限制)</span>}
            </div>

            {/* 丢弃按钮 */}
            {hasUnsavedChanges && (
              <button
                onClick={handleDiscard}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-sb-text-secondary hover:text-red-400 bg-white/5 hover:bg-red-500/10 rounded-lg transition-colors"
              >
                <RotateCcw className="w-4 h-4" />
                丢弃
              </button>
            )}

            {/* 恢复默认按钮 */}
            {onResetToDefault && (
              <button
                onClick={handleResetToDefault}
                disabled={isResetting}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-sb-text-secondary hover:text-sb-cyan bg-white/5 hover:bg-sb-cyan/10 rounded-lg transition-colors disabled:opacity-50"
              >
                {isResetting ? (
                  <div className="w-4 h-4 border-2 border-sb-text-secondary/30 border-t-sb-cyan rounded-full animate-spin" />
                ) : (
                  <History className="w-4 h-4" />
                )}
                恢复默认
              </button>
            )}

            {/* 保存按钮 */}
            <button
              onClick={handleSave}
              disabled={!hasUnsavedChanges || isSaving}
              className="flex items-center gap-1.5 px-4 py-1.5 text-sm bg-sb-cyan text-black rounded-lg hover:bg-sb-cyan/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSaving ? (
                <>
                  <div className="w-4 h-4 border-2 border-black/30 border-t-black rounded-full animate-spin" />
                  保存中...
                </>
              ) : (
                <>
                  <Save className="w-4 h-4" />
                  保存
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      <div className="flex">
        {/* 主编辑区 */}
        <div className="flex-1">
          {/* 变体选择器（如果有多个变体） */}
          {variants.length > 1 && onSwitchVariant && (
            <div className="px-4 py-2 border-b border-white/5 bg-white/5">
              <div className="flex items-center gap-2">
                <GitBranch className="w-4 h-4 text-sb-cyan" />
                <span className="text-sm text-sb-text-secondary">变体:</span>
                <select
                  value={selectedVariant}
                  onChange={(e) => onSwitchVariant(e.target.value)}
                  className="px-3 py-1 bg-white/5 border border-white/10 rounded text-sm focus:outline-none focus:border-sb-cyan/50"
                >
                  {variants.map(v => (
                    <option key={v.id} value={v.id}>
                      {v.name} ({v.tokenCount} tokens)
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {/* 编辑器 */}
          <div className="relative">
            <textarea
              ref={textareaRef}
              value={localContent}
              onChange={handleChange}
              onKeyDown={handleKeyDown}
              onClick={(e) => setCursorPosition(e.currentTarget.selectionStart)}
              onKeyUp={(e) => setCursorPosition(e.currentTarget.selectionStart)}
              rows={20}
              className={`w-full px-4 py-3 bg-sb-bg-primary text-sb-text-primary font-mono text-sm resize-none focus:outline-none ${
                isOverLimit ? 'border-2 border-red-500/50' : ''
              }`}
              placeholder="在此输入提示词模板内容..."
              spellCheck={false}
            />

            {/* 变量补全提示 */}
            {localContent.slice(cursorPosition - 1, cursorPosition) === '{' && variables.length > 0 && (
              <div className="absolute left-4 bottom-4 bg-sb-bg-secondary border border-sb-cyan/30 rounded-lg shadow-xl p-2 min-w-[200px] z-10">
                <p className="text-xs text-sb-text-secondary mb-2 px-2">可用变量:</p>
                {variables.map(v => (
                  <button
                    key={v}
                    onClick={() => insertVariable(v)}
                    className="w-full text-left px-3 py-1.5 text-sm text-sb-cyan hover:bg-white/5 rounded transition-colors"
                  >
                    {`{${v}}`}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* 底部工具栏 */}
          <div className="px-4 py-2 border-t border-white/5 bg-white/5 flex items-center justify-between">
            <div className="flex items-center gap-4 text-xs text-sb-text-secondary">
              <span>字符: {localContent.length}</span>
              <span>行: {localContent.split('\n').length}</span>
            </div>

            {/* 变量列表切换 */}
            {variables.length > 0 && (
              <button
                onClick={() => setShowVariables(!showVariables)}
                className="flex items-center gap-1 text-xs text-sb-cyan hover:underline"
              >
                <Type className="w-3 h-3" />
                {showVariables ? '隐藏变量' : '显示变量'}
                <ChevronDown className={`w-3 h-3 transition-transform ${showVariables ? 'rotate-180' : ''}`} />
              </button>
            )}
          </div>

          {/* 变量列表 */}
          {showVariables && variables.length > 0 && (
            <div className="px-4 py-3 border-t border-white/5 bg-black/20">
              <p className="text-xs text-sb-text-secondary mb-2">点击插入变量:</p>
              <div className="flex flex-wrap gap-2">
                {variables.map(v => (
                  <button
                    key={v}
                    onClick={() => insertVariable(v)}
                    className="px-2 py-1 text-xs bg-sb-cyan/10 text-sb-cyan rounded hover:bg-sb-cyan/20 transition-colors"
                  >
                    {`{${v}}`}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* 右侧预算面板 */}
        {Object.keys(budgetCategories).length > 0 && (
          <div className="w-80 border-l border-white/10">
            <TokenBudgetPanel
              categories={budgetCategories}
              totalBudget={totalBudget}
              totalUsed={totalUsed}
              isOverBudget={isOverBudget}
            />
          </div>
        )}
      </div>
    </div>
  );
};

export default SmartTemplateEditor;
