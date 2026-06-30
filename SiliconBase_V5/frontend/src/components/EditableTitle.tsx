/**
 * EditableTitle - 可编辑会话标题组件
 * Phase 5 Week 9 - 用户体验优化
 * 
 * 功能：
 * - 显示当前会话标题
 * - 点击编辑标题
 * - 自动生成标题提示
 * - 保存/取消编辑
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Edit2, Check, X, Loader2, 
  Type, Wand2 
} from 'lucide-react';
import { sessionAPI } from '../utils/api/session';

interface EditableTitleProps {
  sessionId: string;
  title: string;
  messageCount: number;
  onTitleUpdate: (newTitle: string) => void;
  className?: string;
  autoGenerateThreshold?: number; // 自动生成的消息数阈值，默认3
}

export default function EditableTitle({
  sessionId,
  title,
  messageCount,
  onTitleUpdate,
  className = '',
  autoGenerateThreshold = 3
}: EditableTitleProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(title);
  const [isSaving, setIsSaving] = useState(false);
  const [showAutoGenerate, setShowAutoGenerate] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // 检查是否是默认标题（需要自动生成）
  const isDefaultTitle = useCallback((): boolean => {
    return title.includes('日常会话') || 
           title.includes('专注会话') || 
           title.includes('新对话') ||
           !!title.match(/^\d{1,2}月\d{1,2}日/);
  }, [title]);

  // 检查是否应该显示自动生成提示
  useEffect(() => {
    const shouldShow = isDefaultTitle() && 
                      messageCount >= autoGenerateThreshold * 2 && // 用户+AI消息
                      !isEditing;
    setShowAutoGenerate(shouldShow);
  }, [messageCount, title, isEditing, autoGenerateThreshold, isDefaultTitle]);

  // 进入编辑模式时聚焦输入框
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

  // 点击外部取消编辑
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        if (isEditing) {
          handleCancel();
        }
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isEditing]);

  // 开始编辑
  const handleStartEdit = () => {
    setEditValue(title);
    setIsEditing(true);
    setShowAutoGenerate(false);
  };

  // 保存编辑
  const handleSave = async () => {
    const trimmedValue = editValue.trim();
    if (!trimmedValue || trimmedValue === title) {
      setIsEditing(false);
      return;
    }

    setIsSaving(true);
    try {
      await sessionAPI.updateSession(sessionId, { title: trimmedValue });
      onTitleUpdate(trimmedValue);
      setIsEditing(false);
    } catch (error) {
      console.error('[EditableTitle] 保存标题失败:', error);
      // 恢复原值
      setEditValue(title);
    } finally {
      setIsSaving(false);
    }
  };

  // 取消编辑
  const handleCancel = () => {
    setEditValue(title);
    setIsEditing(false);
  };

  // 处理键盘事件
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSave();
    } else if (e.key === 'Escape') {
      handleCancel();
    }
  };

  // 自动生成标题
  const handleAutoGenerate = async () => {
    setIsGenerating(true);
    setShowAutoGenerate(false);
    
    try {
      // 调用后端API生成标题
      const generatedTitle = await sessionAPI.generateTitle(sessionId);
      if (generatedTitle) {
        setEditValue(generatedTitle);
        setIsEditing(true);
      } else {
        // 如果API不可用，使用简单的启发式生成
        const fallbackTitle = generateFallbackTitle();
        setEditValue(fallbackTitle);
        setIsEditing(true);
      }
    } catch (error) {
      console.error('[EditableTitle] 自动生成标题失败:', error);
      // 使用回退方案
      const fallbackTitle = generateFallbackTitle();
      setEditValue(fallbackTitle);
      setIsEditing(true);
    } finally {
      setIsGenerating(false);
    }
  };

  // 回退标题生成（基于简单规则）
  const generateFallbackTitle = (): string => {
    const hour = new Date().getHours();
    let timePrefix = '';
    if (hour < 12) timePrefix = '上午';
    else if (hour < 18) timePrefix = '下午';
    else timePrefix = '晚上';
    
    return `${timePrefix}的对话`;
  };

  // 标题截断显示
  const displayTitle = title.length > 30 ? title.slice(0, 27) + '...' : title;

  return (
    <div 
      ref={containerRef}
      className={`relative flex items-center gap-2 ${className}`}
    >
      <AnimatePresence mode="wait">
        {isEditing ? (
          <motion.div
            key="editing"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="flex items-center gap-2"
          >
            <div className="relative">
              <Type className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                ref={inputRef}
                type="text"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isSaving}
                className="
                  pl-10 pr-4 py-2 
                  bg-sb-bg-primary border border-sb-cyan/30 rounded-lg
                  text-white text-sm
                  focus:outline-none focus:border-sb-cyan focus:ring-1 focus:ring-sb-cyan/30
                  min-w-[200px] max-w-[400px]
                  disabled:opacity-50
                "
                placeholder="输入会话标题..."
                maxLength={100}
              />
            </div>
            
            <div className="flex items-center gap-1">
              <button
                onClick={handleSave}
                disabled={isSaving || !editValue.trim()}
                className="
                  p-2 rounded-lg
                  bg-emerald-500/20 text-emerald-400
                  hover:bg-emerald-500/30
                  disabled:opacity-50 disabled:cursor-not-allowed
                  transition-colors
                "
                title="保存"
              >
                {isSaving ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Check className="w-4 h-4" />
                )}
              </button>
              <button
                onClick={handleCancel}
                disabled={isSaving}
                className="
                  p-2 rounded-lg
                  bg-white/5 text-slate-400
                  hover:bg-white/10 hover:text-white
                  disabled:opacity-50
                  transition-colors
                "
                title="取消"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="display"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex items-center gap-2 group"
          >
            <h1 
              className="text-lg font-semibold text-white truncate max-w-[300px]"
              title={title}
            >
              {displayTitle}
            </h1>
            
            <button
              onClick={handleStartEdit}
              className="
                p-1.5 rounded-lg
                text-slate-400 opacity-0 group-hover:opacity-100
                hover:bg-white/10 hover:text-white
                transition-all
              "
              title="编辑标题"
            >
              <Edit2 className="w-4 h-4" />
            </button>

            {/* 自动生成提示 */}
            <AnimatePresence>
              {showAutoGenerate && (
                <motion.button
                  initial={{ opacity: 0, x: -10, scale: 0.9 }}
                  animate={{ opacity: 1, x: 0, scale: 1 }}
                  exit={{ opacity: 0, x: -10, scale: 0.9 }}
                  onClick={handleAutoGenerate}
                  disabled={isGenerating}
                  className="
                    flex items-center gap-1.5 px-3 py-1.5 rounded-full
                    bg-gradient-to-r from-purple-500/20 to-pink-500/20
                    border border-purple-500/30
                    text-purple-300 text-xs
                    hover:from-purple-500/30 hover:to-pink-500/30
                    disabled:opacity-50
                    transition-all
                  "
                >
                  {isGenerating ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Wand2 className="w-3.5 h-3.5" />
                  )}
                  AI生成标题
                </motion.button>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 编辑提示 */}
      <AnimatePresence>
        {isEditing && (
          <motion.span
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="text-xs text-slate-500"
          >
            按 Enter 保存，Esc 取消
          </motion.span>
        )}
      </AnimatePresence>
    </div>
  );
}
