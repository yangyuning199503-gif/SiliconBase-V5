/**
 * AlignmentDialog - 目标对齐对话框组件
 * 
 * 功能：
 * 1. 澄清对话框（Clarification）- 提供选项让用户选择意图
 * 2. 确认对话框（Confirmation）- 确认用户意图"你的意思是...吗？"
 * 
 * 设计原则：
 * - 模态阻塞式：用户必须做出选择才能继续
 * - 视觉层次突出：确保用户注意到需要做出选择
 * - 深色/浅色主题适配
 */

import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  HelpCircle,
  CheckCircle2,
  XCircle,
  MessageSquare,
  AlertTriangle,
  Send,
  ChevronRight
} from 'lucide-react';

/** 对齐对话框类型 */
export type AlignmentType = 'clarification' | 'confirmation';

/** 对齐对话框属性 */
export interface AlignmentDialogProps {
  /** 对话框类型 */
  type: AlignmentType;
  /** 问题文本 */
  question: string;
  /** 选项列表（仅clarification类型使用） */
  options?: string[];
  /** 确认消息（仅confirmation类型使用） */
  confirmMessage?: string;
  /** 是否显示 */
  isOpen: boolean;
  /** 确认回调 */
  onConfirm: () => void;
  /** 澄清回调，返回用户选择的选项或输入 */
  onClarify: (response: string) => void;
  /** 取消回调 */
  onCancel: () => void;
  /** 超时时间（秒），0表示无超时 */
  timeout?: number;
  /** 自定义类名 */
  className?: string;
}

/** 对话框状态 */
type DialogState = 'idle' | 'selecting' | 'submitting' | 'timeout';

/**
 * 倒计时组件
 */
const Countdown: React.FC<{
  seconds: number;
  onTimeout: () => void;
  className?: string;
}> = ({ seconds, onTimeout, className = '' }) => {
  const [remaining, setRemaining] = useState(seconds);

  useEffect(() => {
    if (remaining <= 0) {
      onTimeout();
      return;
    }

    const timer = setInterval(() => {
      setRemaining(prev => {
        if (prev <= 1) {
          clearInterval(timer);
          onTimeout();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [remaining, onTimeout]);

  const percentage = (remaining / seconds) * 100;
  const isUrgent = remaining < 10;

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <div className="w-24 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
        <motion.div
          initial={{ width: '100%' }}
          animate={{ width: `${percentage}%` }}
          transition={{ duration: 1, ease: 'linear' }}
          className={`h-full rounded-full transition-colors ${
            isUrgent ? 'bg-red-500' : 'bg-sb-cyan'
          }`}
        />
      </div>
      <span className={`text-xs font-mono ${isUrgent ? 'text-red-500' : 'text-gray-500 dark:text-gray-400'}`}>
        {remaining}s
      </span>
    </div>
  );
};

/**
 * 目标对齐对话框组件
 */
export const AlignmentDialog: React.FC<AlignmentDialogProps> = ({
  type,
  question,
  options = [],
  confirmMessage,
  isOpen,
  onConfirm,
  onClarify,
  onCancel,
  timeout = 0,
  className = ''
}) => {
  const [customInput, setCustomInput] = useState('');
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [dialogState, setDialogState] = useState<DialogState>('idle');
  const [showCustomInput, setShowCustomInput] = useState(false);

  // 重置状态当对话框打开时
  useEffect(() => {
    if (isOpen) {
      setCustomInput('');
      setSelectedOption(null);
      setDialogState('idle');
      setShowCustomInput(false);
    }
  }, [isOpen]);

  // 处理选项选择
  const handleOptionSelect = useCallback((option: string) => {
    setSelectedOption(option);
    setDialogState('selecting');
    
    // 延迟提交，让用户看到选择效果
    setTimeout(() => {
      setDialogState('submitting');
      onClarify(option);
    }, 200);
  }, [onClarify]);

  // 处理自定义输入提交
  const handleCustomSubmit = useCallback(() => {
    if (!customInput.trim()) return;
    
    setDialogState('submitting');
    onClarify(customInput.trim());
  }, [customInput, onClarify]);

  // 处理确认
  const handleConfirm = useCallback(() => {
    setDialogState('submitting');
    onConfirm();
  }, [onConfirm]);

  // 处理拒绝（确认类型）
  const handleReject = useCallback(() => {
    setDialogState('submitting');
    onClarify('no');
  }, [onClarify]);

  // 处理超时
  const handleTimeout = useCallback(() => {
    setDialogState('timeout');
    onCancel();
  }, [onCancel]);

  // 如果没有打开，不渲染
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      {/* 背景遮罩 - 模态阻塞 */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={(e) => e.stopPropagation()} // 阻止点击穿透
      />

      {/* 对话框内容 */}
      <motion.div
        initial={{ opacity: 0, scale: 0.9, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.9, y: 20 }}
        transition={{ type: 'spring', damping: 25, stiffness: 300 }}
        className={`relative w-full max-w-lg mx-4 bg-white dark:bg-gray-800 
                    rounded-2xl shadow-2xl overflow-hidden border border-gray-200 
                    dark:border-gray-700 ${className}`}
      >
        {/* 顶部装饰条 */}
        <div className={`h-1.5 w-full ${
          type === 'clarification' 
            ? 'bg-gradient-to-r from-amber-500 to-orange-500' 
            : 'bg-gradient-to-r from-blue-500 to-cyan-500'
        }`} />

        {/* Header */}
        <div className="px-6 pt-6 pb-4">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className={`p-2.5 rounded-xl ${
                type === 'clarification'
                  ? 'bg-amber-100 dark:bg-amber-500/20'
                  : 'bg-blue-100 dark:bg-blue-500/20'
              }`}>
                {type === 'clarification' ? (
                  <HelpCircle className={`w-6 h-6 ${
                    type === 'clarification' ? 'text-amber-600 dark:text-amber-400' : ''
                  }`} />
                ) : (
                  <MessageSquare className="w-6 h-6 text-blue-600 dark:text-blue-400" />
                )}
              </div>
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  {type === 'clarification' ? '需要澄清' : '请确认'}
                </h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  {type === 'clarification' 
                    ? '请选择一个选项以帮助理解您的意图' 
                    : '请确认我理解正确'}
                </p>
              </div>
            </div>

            {/* 倒计时 */}
            {timeout > 0 && (
              <Countdown
                seconds={timeout}
                onTimeout={handleTimeout}
              />
            )}
          </div>
        </div>

        {/* 问题内容 */}
        <div className="px-6 py-4 bg-gray-50 dark:bg-gray-900/50 border-y border-gray-100 dark:border-gray-700">
          <p className="text-gray-800 dark:text-gray-200 leading-relaxed">
            {question}
          </p>
          
          {/* 确认消息（仅confirmation类型） */}
          {type === 'confirmation' && confirmMessage && (
            <div className="mt-3 p-3 bg-blue-50 dark:bg-blue-500/10 rounded-lg border border-blue-100 dark:border-blue-500/20">
              <p className="text-sm text-blue-800 dark:text-blue-300">
                <span className="font-medium">您的意思是：</span>
                {confirmMessage}
              </p>
            </div>
          )}
        </div>

        {/* 选项区域 */}
        <div className="p-6 space-y-4">
          {type === 'clarification' && (
            <>
              {/* 选项按钮 */}
              <div className="space-y-2">
                {options.map((option, index) => (
                  <motion.button
                    key={index}
                    onClick={() => handleOptionSelect(option)}
                    disabled={dialogState !== 'idle'}
                    whileHover={{ scale: dialogState === 'idle' ? 1.01 : 1 }}
                    whileTap={{ scale: dialogState === 'idle' ? 0.99 : 1 }}
                    className={`w-full flex items-center justify-between p-4 rounded-xl border-2 
                              transition-all duration-200 text-left
                              ${selectedOption === option
                                ? 'border-amber-500 bg-amber-50 dark:bg-amber-500/10'
                                : 'border-gray-200 dark:border-gray-700 hover:border-amber-300 dark:hover:border-amber-500/50 bg-white dark:bg-gray-800'
                              }
                              ${dialogState !== 'idle' && selectedOption !== option ? 'opacity-50' : ''}
                              disabled:cursor-not-allowed
                            `}
                  >
                    <span className={`font-medium ${
                      selectedOption === option
                        ? 'text-amber-700 dark:text-amber-400'
                        : 'text-gray-700 dark:text-gray-300'
                    }`}>
                      {option}
                    </span>
                    {selectedOption === option && (
                      <motion.div
                        initial={{ scale: 0 }}
                        animate={{ scale: 1 }}
                        className="w-5 h-5 rounded-full bg-amber-500 flex items-center justify-center"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5 text-white" />
                      </motion.div>
                    )}
                  </motion.button>
                ))}
              </div>

              {/* 自定义输入 */}
              <div className="pt-2">
                {!showCustomInput ? (
                  <button
                    onClick={() => setShowCustomInput(true)}
                    disabled={dialogState !== 'idle'}
                    className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 
                             dark:hover:text-gray-300 transition-colors flex items-center gap-1
                             disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <span>以上都不是？</span>
                    <span className="text-amber-600 dark:text-amber-400 hover:underline">
                      输入自定义意图
                    </span>
                    <ChevronRight className="w-4 h-4" />
                  </button>
                ) : (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    className="space-y-3"
                  >
                    <textarea
                      value={customInput}
                      onChange={(e) => setCustomInput(e.target.value)}
                      placeholder="请描述您的意图..."
                      rows={2}
                      disabled={dialogState !== 'idle'}
                      className="w-full px-4 py-3 text-sm bg-white dark:bg-gray-800 
                               border border-gray-300 dark:border-gray-600 rounded-xl
                               focus:outline-none focus:ring-2 focus:ring-amber-500 
                               focus:border-transparent transition-all resize-none
                               text-gray-800 dark:text-gray-200
                               placeholder:text-gray-400 dark:placeholder:text-gray-500
                               disabled:opacity-50"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault();
                          handleCustomSubmit();
                        }
                      }}
                    />
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          setShowCustomInput(false);
                          setCustomInput('');
                        }}
                        disabled={dialogState !== 'idle'}
                        className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 
                                 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors
                                 disabled:opacity-50"
                      >
                        取消
                      </button>
                      <button
                        onClick={handleCustomSubmit}
                        disabled={!customInput.trim() || dialogState !== 'idle'}
                        className="flex items-center gap-2 px-4 py-2 text-sm font-medium
                                 text-white bg-gradient-to-r from-amber-500 to-orange-500
                                 hover:from-amber-600 hover:to-orange-600
                                 rounded-lg transition-all
                                 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <Send className="w-4 h-4" />
                        提交
                      </button>
                    </div>
                  </motion.div>
                )}
              </div>
            </>
          )}

          {type === 'confirmation' && (
            <div className="flex gap-3">
              <button
                onClick={handleReject}
                disabled={dialogState !== 'idle'}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-3
                         text-gray-700 dark:text-gray-300 font-medium
                         bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600
                         border border-gray-300 dark:border-gray-600
                         rounded-xl transition-all
                         disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <XCircle className="w-5 h-5" />
                不是
              </button>
              <button
                onClick={handleConfirm}
                disabled={dialogState !== 'idle'}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-3
                         text-white font-medium
                         bg-gradient-to-r from-blue-500 to-cyan-500
                         hover:from-blue-600 hover:to-cyan-600
                         rounded-xl transition-all
                         disabled:opacity-50 disabled:cursor-not-allowed
                         shadow-lg shadow-blue-500/25"
              >
                <CheckCircle2 className="w-5 h-5" />
                是的
              </button>
            </div>
          )}
        </div>

        {/* 底部状态 */}
        {dialogState === 'submitting' && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="px-6 py-3 bg-gray-50 dark:bg-gray-900/50 border-t border-gray-100 
                     dark:border-gray-700 flex items-center justify-center gap-2"
          >
            <div className="w-4 h-4 border-2 border-gray-300 dark:border-gray-600 
                          border-t-sb-cyan rounded-full animate-spin" />
            <span className="text-sm text-gray-500 dark:text-gray-400">处理中...</span>
          </motion.div>
        )}

        {dialogState === 'timeout' && (
          <div className="px-6 py-3 bg-red-50 dark:bg-red-500/10 border-t border-red-100 
                        dark:border-red-500/20 flex items-center justify-center gap-2">
            <AlertTriangle className="w-4 h-4 text-red-500" />
            <span className="text-sm text-red-600 dark:text-red-400">已超时，请重试</span>
          </div>
        )}
      </motion.div>
    </div>
  );
};

/**
 * 对齐对话框容器 - 用于管理多个对齐请求队列
 */
export interface AlignmentQueueItem extends Omit<AlignmentDialogProps, 'isOpen' | 'onConfirm' | 'onClarify' | 'onCancel'> {
  id: string;
  resolve: (value: string | boolean) => void;
}

interface AlignmentQueueProps {
  items: AlignmentQueueItem[];
  onConfirm: (id: string) => void;
  onClarify: (id: string, response: string) => void;
  onCancel: (id: string) => void;
}

export const AlignmentDialogQueue: React.FC<AlignmentQueueProps> = ({
  items,
  onConfirm,
  onClarify,
  onCancel
}) => {
  if (items.length === 0) return null;

  const current = items[0];

  return (
    <AlignmentDialog
      {...current}
      isOpen={true}
      onConfirm={() => onConfirm(current.id)}
      onClarify={(response) => onClarify(current.id, response)}
      onCancel={() => onCancel(current.id)}
    />
  );
};

export default AlignmentDialog;
