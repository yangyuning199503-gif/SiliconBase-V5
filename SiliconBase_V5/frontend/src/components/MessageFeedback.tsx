/**
 * 消息反馈组件 - MessageFeedback
 * 
 * 功能：
 * 1. 为每条AI回复提供点赞/点踩按钮
 * 2. 点踩时显示评论输入框
 * 3. 提交反馈后显示确认动画
 * 4. 与后端RLHF API交互
 * 
 * Author: SiliconBase V5
 * Version: 1.0.0
 */

import React, { useState, useCallback } from 'react';
import { ThumbsUp, ThumbsDown, Check, Loader2, MessageSquare } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

export interface MessageFeedbackProps {
  /** 消息唯一ID */
  messageId: string;
  /** 对话ID（可选） */
  conversationId?: string;
  /** 原始提示词（用于DPO训练） */
  promptText?: string;
  /** AI回复内容（用于DPO训练） */
  responseText?: string;
  /** 提交反馈的回调 */
  onFeedback: (type: 'thumbs_up' | 'thumbs_down', comment?: string) => Promise<void>;
  /** 反馈提交成功后的回调 */
  onFeedbackSubmitted?: (message: string) => void;
}

type FeedbackState = 'idle' | 'submitting' | 'submitted';
type FeedbackType = 'thumbs_up' | 'thumbs_down' | null;

export const MessageFeedback: React.FC<MessageFeedbackProps> = ({
  messageId: _messageId,
  onFeedback,
  onFeedbackSubmitted,
}) => {
  const [feedbackState, setFeedbackState] = useState<FeedbackState>('idle');
  const [feedbackType, setFeedbackType] = useState<FeedbackType>(null);
  const [showComment, setShowComment] = useState(false);
  const [comment, setComment] = useState('');
  const [resultMessage, setResultMessage] = useState('');

  const submitFeedback = useCallback(async (type: 'thumbs_up' | 'thumbs_down', userComment?: string) => {
    if (feedbackState === 'submitted') return;
    
    setFeedbackState('submitting');
    
    try {
      await onFeedback(type, userComment);
      
      // 根据反馈类型生成消息
      const msg = type === 'thumbs_up' 
        ? '✓ 已记录你的认可！我会记住这些成功经验。'
        : '✓ 已记录你的反馈。我会从中学习并改进。';
      
      setResultMessage(msg);
      setFeedbackState('submitted');
      setShowComment(false);
      
      // 通知父组件
      onFeedbackSubmitted?.(msg);
      
      // 3秒后重置状态（可选）
      setTimeout(() => {
        setFeedbackState('idle');
        setFeedbackType(null);
        setResultMessage('');
        setComment('');
      }, 5000);
      
    } catch (error) {
      console.error('[MessageFeedback] 提交反馈失败:', error);
      setFeedbackState('idle');
    }
  }, [feedbackState, onFeedback, onFeedbackSubmitted]);

  const handleThumbsUp = useCallback(() => {
    if (feedbackState === 'submitted') return;
    setFeedbackType('thumbs_up');
    submitFeedback('thumbs_up');
  }, [submitFeedback, feedbackState]);

  const handleThumbsDown = useCallback(() => {
    if (feedbackState === 'submitted') return;
    setFeedbackType('thumbs_down');
    setShowComment(true);
  }, [feedbackState]);

  const handleCommentSubmit = useCallback(() => {
    submitFeedback('thumbs_down', comment.trim() || undefined);
  }, [submitFeedback, comment]);

  const handleCancel = useCallback(() => {
    setShowComment(false);
    setFeedbackType(null);
    setComment('');
  }, []);

  // 已提交状态
  if (feedbackState === 'submitted') {
    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0 }}
        className="flex items-center gap-1.5 text-xs"
      >
        <motion.div
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ type: "spring", stiffness: 500, damping: 15 }}
        >
          <Check className="w-3.5 h-3.5 text-emerald-400" />
        </motion.div>
        <span className="text-emerald-400">已记录反馈</span>
      </motion.div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1">
        {/* 点赞按钮 */}
        <motion.button
          onClick={handleThumbsUp}
          disabled={feedbackState === 'submitting'}
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.95 }}
          className={`
            p-1.5 rounded-md transition-all duration-200
            ${feedbackType === 'thumbs_up'
              ? 'bg-emerald-500/20 text-emerald-400'
              : 'text-white/30 hover:text-emerald-400 hover:bg-emerald-500/10'
            }
            ${feedbackState === 'submitting' ? 'opacity-50 cursor-not-allowed' : ''}
          `}
          title="有帮助"
        >
          {feedbackState === 'submitting' && feedbackType === 'thumbs_up' ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <ThumbsUp className="w-3.5 h-3.5" />
          )}
        </motion.button>

        {/* 点踩按钮 */}
        <motion.button
          onClick={handleThumbsDown}
          disabled={feedbackState === 'submitting'}
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.95 }}
          className={`
            p-1.5 rounded-md transition-all duration-200
            ${feedbackType === 'thumbs_down'
              ? 'bg-red-500/20 text-red-400'
              : 'text-white/30 hover:text-red-400 hover:bg-red-500/10'
            }
            ${feedbackState === 'submitting' ? 'opacity-50 cursor-not-allowed' : ''}
          `}
          title="没帮助"
        >
          {feedbackState === 'submitting' && feedbackType === 'thumbs_down' ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <ThumbsDown className="w-3.5 h-3.5" />
          )}
        </motion.button>

        {/* 反馈提示文字 */}
        <AnimatePresence>
          {resultMessage && (
            <motion.span
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0 }}
              className="text-xs text-emerald-400 ml-2"
            >
              {resultMessage}
            </motion.span>
          )}
        </AnimatePresence>
      </div>

      {/* 评论输入框（点踩时显示） */}
      <AnimatePresence>
        {showComment && (
          <motion.div
            initial={{ opacity: 0, height: 0, y: -10 }}
            animate={{ opacity: 1, height: 'auto', y: 0 }}
            exit={{ opacity: 0, height: 0, y: -10 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="flex items-start gap-2 p-2 bg-white/5 rounded-lg border border-white/10">
              <MessageSquare className="w-4 h-4 text-white/40 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="请告诉我们问题在哪，帮助我们改进..."
                  className="w-full px-2 py-1 text-xs bg-transparent border-none resize-none focus:outline-none text-white/80 placeholder:text-white/30"
                  rows={2}
                  maxLength={150}
                  autoFocus
                />
                <div className="flex items-center justify-between mt-1">
                  <span className="text-[10px] text-white/30">
                    {comment.length}/150
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleCancel}
                      className="px-2 py-0.5 text-[10px] text-white/50 hover:text-white transition-colors"
                    >
                      取消
                    </button>
                    <button
                      onClick={handleCommentSubmit}
                      disabled={feedbackState === 'submitting'}
                      className="px-3 py-0.5 text-[10px] bg-red-500/20 text-red-400 rounded hover:bg-red-500/30 transition-colors disabled:opacity-50"
                    >
                      {feedbackState === 'submitting' ? '提交中...' : '提交'}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default MessageFeedback;
