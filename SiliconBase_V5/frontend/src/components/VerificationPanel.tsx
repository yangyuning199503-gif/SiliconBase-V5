/**
 * 验收决策面板组件
 * Phase 4.5: 前端槽位显示增强
 * 
 * 功能：
 * - 显示AI验证结果（置信度、关注点）
 * - 人工确认按钮（通过/拒绝）
 * - 降级选项显示
 */

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Bot,
  UserCheck,
  Loader2,
  RefreshCw,
  Shield,
  AlertCircle,
  ThumbsUp,
  ThumbsDown
} from 'lucide-react';
import type { EnhancedSlotTask, VerificationState } from '../types/slot';

// ========== 组件 Props ==========

interface VerificationPanelProps {
  task: EnhancedSlotTask;
  onApprove: () => void;
  onReject: (feedback: string) => void;
  onRequestAIReview?: () => void;
  className?: string;
}

// ========== 辅助函数 ==========

// 获取验收状态标签
const getVerificationLabel = (state?: VerificationState): string => {
  switch (state) {
    case 'pending':
      return '等待验收';
    case 'ai_passed':
      return 'AI已通过';
    case 'ai_failed':
      return 'AI未通过';
    case 'human_approved':
      return '人工已通过';
    case 'human_rejected':
      return '人工已拒绝';
    default:
      return '未知状态';
  }
};

// 获取验收状态颜色
const getVerificationColorClass = (state?: VerificationState): string => {
  switch (state) {
    case 'pending':
      return 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20';
    case 'ai_passed':
      return 'text-blue-400 bg-blue-400/10 border-blue-400/20';
    case 'ai_failed':
      return 'text-red-400 bg-red-400/10 border-red-400/20';
    case 'human_approved':
      return 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20';
    case 'human_rejected':
      return 'text-red-400 bg-red-400/10 border-red-400/20';
    default:
      return 'text-slate-400 bg-slate-400/10 border-slate-400/20';
  }
};

// 获取验收状态图标
const getVerificationIcon = (state?: VerificationState) => {
  switch (state) {
    case 'pending':
      return <AlertCircle className="w-4 h-4" />;
    case 'ai_passed':
      return <Bot className="w-4 h-4" />;
    case 'ai_failed':
      return <XCircle className="w-4 h-4" />;
    case 'human_approved':
      return <UserCheck className="w-4 h-4" />;
    case 'human_rejected':
      return <ThumbsDown className="w-4 h-4" />;
    default:
      return <AlertCircle className="w-4 h-4" />;
  }
};

// 获取置信度颜色
const getConfidenceColor = (confidence: number): string => {
  if (confidence >= 0.8) return 'text-emerald-400';
  if (confidence >= 0.6) return 'text-yellow-400';
  if (confidence >= 0.4) return 'text-orange-400';
  return 'text-red-400';
};

// 获取置信度标签
const getConfidenceLabel = (confidence: number): string => {
  if (confidence >= 0.8) return '高置信度';
  if (confidence >= 0.6) return '中等置信度';
  if (confidence >= 0.4) return '低置信度';
  return '置信度不足';
};

// ========== AI验证结果展示组件 ==========

interface AIVerificationResultProps {
  confidence: number;
  concerns: string[];
  passed: boolean;
}

const AIVerificationResult: React.FC<AIVerificationResultProps> = ({
  confidence,
  concerns,
  passed
}) => {
  return (
    <div className="bg-slate-900/50 rounded-lg p-4 border border-white/5">
      {/* AI判断结果 */}
      <div className="flex items-center gap-3 mb-4">
        <div className={`
          w-10 h-10 rounded-full flex items-center justify-center
          ${passed ? 'bg-emerald-500/20' : 'bg-red-500/20'}
        `}>
          {passed ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          ) : (
            <XCircle className="w-5 h-5 text-red-400" />
          )}
        </div>
        <div>
          <p className="text-white font-medium">
            AI验证{passed ? '通过' : '未通过'}
          </p>
          <p className="text-slate-400 text-xs">
            基于结果质量自动判断
          </p>
        </div>
      </div>

      {/* 置信度显示 */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-slate-400 text-sm">置信度</span>
          <span className={`text-sm font-medium ${getConfidenceColor(confidence)}`}>
            {Math.round(confidence * 100)}% - {getConfidenceLabel(confidence)}
          </span>
        </div>
        <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${confidence * 100}%` }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className={`
              h-full rounded-full
              ${confidence >= 0.8 ? 'bg-emerald-400' : 
                confidence >= 0.6 ? 'bg-yellow-400' : 
                confidence >= 0.4 ? 'bg-orange-400' : 'bg-red-400'}
            `}
          />
        </div>
      </div>

      {/* 关注点列表 */}
      {concerns.length > 0 && (
        <div>
          <p className="text-slate-400 text-sm mb-2 flex items-center gap-1">
            <AlertTriangle className="w-4 h-4" />
            AI关注点 ({concerns.length})
          </p>
          <ul className="space-y-1.5">
            {concerns.map((concern, index) => (
              <motion.li
                key={index}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.3 + index * 0.1 }}
                className="flex items-start gap-2 text-sm text-slate-300"
              >
                <span className="text-yellow-500 mt-0.5">•</span>
                <span>{concern}</span>
              </motion.li>
            ))}
          </ul>
        </div>
      )}

      {concerns.length === 0 && passed && (
        <div className="flex items-center gap-2 text-emerald-400 text-sm">
          <Shield className="w-4 h-4" />
          <span>未发现明显问题</span>
        </div>
      )}
    </div>
  );
};

// ========== 人工确认对话框组件 ==========

interface HumanConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (feedback: string) => void;
  type: 'approve' | 'reject';
}

const HumanConfirmDialog: React.FC<HumanConfirmDialogProps> = ({
  isOpen,
  onClose,
  onConfirm,
  type
}) => {
  const [feedback, setFeedback] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleConfirm = async () => {
    setIsSubmitting(true);
    try {
      await onConfirm(feedback);
      setFeedback('');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.9, opacity: 0 }}
            className={`
              bg-slate-800 rounded-xl border p-6 w-full max-w-lg shadow-2xl
              ${type === 'approve' 
                ? 'border-emerald-500/30' 
                : 'border-red-500/30'}
            `}
            onClick={(e) => e.stopPropagation()}
          >
            {/* 标题 */}
            <div className="flex items-center gap-3 mb-4">
              <div className={`
                w-10 h-10 rounded-full flex items-center justify-center
                ${type === 'approve' 
                  ? 'bg-emerald-500/20' 
                  : 'bg-red-500/20'}
              `}>
                {type === 'approve' ? (
                  <ThumbsUp className="w-5 h-5 text-emerald-400" />
                ) : (
                  <ThumbsDown className="w-5 h-5 text-red-400" />
                )}
              </div>
              <div>
                <h4 className="text-white font-semibold">
                  {type === 'approve' ? '确认通过' : '确认拒绝'}
                </h4>
                <p className="text-slate-400 text-sm">
                  {type === 'approve' 
                    ? '确认验收通过，继续执行后续步骤' 
                    : '拒绝当前结果，提供反馈信息'}
                </p>
              </div>
            </div>

            {/* 反馈输入 */}
            <div className="mb-4">
              <label className="block text-slate-300 text-sm mb-2">
                {type === 'reject' ? (
                  <>
                    拒绝原因 <span className="text-red-400">*</span>
                  </>
                ) : (
                  '备注（可选）'
                )}
              </label>
              <textarea
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder={
                  type === 'reject'
                    ? '请详细说明拒绝原因，帮助AI改进...'
                    : '可选：添加备注信息...'
                }
                className="w-full h-24 bg-slate-900 border border-white/10 rounded-lg px-3 py-2 text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-cyan-500/50 resize-none"
              />
              {type === 'reject' && (
                <p className="text-slate-500 text-xs mt-1">
                  拒绝原因将用于指导AI改进
                </p>
              )}
            </div>

            {/* 按钮 */}
            <div className="flex justify-end gap-3">
              <button
                onClick={onClose}
                className="px-4 py-2 text-slate-400 hover:text-white text-sm transition-all"
              >
                取消
              </button>
              <button
                onClick={handleConfirm}
                disabled={isSubmitting || (type === 'reject' && !feedback.trim())}
                className={`
                  flex items-center gap-1.5 px-4 py-2 font-medium rounded-lg text-sm transition-all
                  ${type === 'approve'
                    ? 'bg-emerald-500 hover:bg-emerald-600 disabled:bg-slate-600 text-slate-900'
                    : 'bg-red-500 hover:bg-red-600 disabled:bg-slate-600 text-white'}
                  disabled:cursor-not-allowed
                `}
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    处理中...
                  </>
                ) : type === 'approve' ? (
                  <>
                    <CheckCircle2 className="w-4 h-4" />
                    确认通过
                  </>
                ) : (
                  <>
                    <XCircle className="w-4 h-4" />
                    确认拒绝
                  </>
                )}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

// ========== 主组件 ==========

export const VerificationPanel: React.FC<VerificationPanelProps> = ({
  task,
  onApprove,
  onReject,
  onRequestAIReview,
  className = ''
}) => {
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);
  const [confirmType, setConfirmType] = useState<'approve' | 'reject'>('approve');
  const [isProcessing, setIsProcessing] = useState(false);

  const verification = task.verification_status;
  const needsHuman = verification?.requires_human ?? false;
  const isPending = verification?.state === 'pending';
  const isAIProcessed = verification?.state === 'ai_passed' || verification?.state === 'ai_failed';

  const handleApproveClick = () => {
    setConfirmType('approve');
    setShowConfirmDialog(true);
  };

  const handleRejectClick = () => {
    setConfirmType('reject');
    setShowConfirmDialog(true);
  };

  const handleConfirm = async (feedback: string) => {
    setIsProcessing(true);
    try {
      if (confirmType === 'approve') {
        await onApprove();
      } else {
        await onReject(feedback);
      }
      setShowConfirmDialog(false);
    } finally {
      setIsProcessing(false);
    }
  };

  // 如果没有验收状态，不显示面板
  if (!verification) {
    return null;
  }

  return (
    <div className={`verification-panel ${className}`}>
      {/* 验收状态头部 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-cyan-400" />
          <h4 className="text-white font-medium">验收状态</h4>
        </div>
        <div className={`
          inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs
          ${getVerificationColorClass(verification.state)}
        `}>
          {getVerificationIcon(verification.state)}
          <span>{getVerificationLabel(verification.state)}</span>
        </div>
      </div>

      {/* AI验证结果 */}
      {(isAIProcessed || isPending) && (
        <div className="mb-4">
          <AIVerificationResult
            confidence={verification.confidence}
            concerns={verification.concerns}
            passed={verification.state === 'ai_passed'}
          />
        </div>
      )}

      {/* 需要人工确认提示 */}
      {needsHuman && isAIProcessed && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-4 p-3 bg-yellow-500/10 border border-yellow-500/20 rounded-lg"
        >
          <p className="text-yellow-400 text-sm flex items-start gap-2">
            <UserCheck className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span>
              <strong>需要人工确认：</strong>
              AI置信度较低或发现潜在问题，请人工审核后决定是否通过。
            </span>
          </p>
        </motion.div>
      )}

      {/* 操作按钮 */}
      {task.controls.can_approve && task.controls.can_reject && (
        <div className="flex items-center gap-3">
          <button
            onClick={handleApproveClick}
            disabled={isProcessing}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-emerald-500/20 hover:bg-emerald-500/30 disabled:bg-slate-700/50 text-emerald-400 rounded-lg text-sm transition-all disabled:cursor-not-allowed"
          >
            {isProcessing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <ThumbsUp className="w-4 h-4" />
            )}
            通过
          </button>
          <button
            onClick={handleRejectClick}
            disabled={isProcessing}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 disabled:bg-slate-700/50 text-red-400 rounded-lg text-sm transition-all disabled:cursor-not-allowed"
          >
            {isProcessing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <ThumbsDown className="w-4 h-4" />
            )}
            拒绝
          </button>
        </div>
      )}

      {/* 请求AI复核按钮 */}
      {onRequestAIReview && isAIProcessed && needsHuman && (
        <button
          onClick={onRequestAIReview}
          disabled={isProcessing}
          className="w-full mt-3 flex items-center justify-center gap-2 px-4 py-2 bg-cyan-500/20 hover:bg-cyan-500/30 disabled:bg-slate-700/50 text-cyan-400 rounded-lg text-sm transition-all disabled:cursor-not-allowed"
        >
          <RefreshCw className="w-4 h-4" />
          请求AI复核
        </button>
      )}

      {/* 确认对话框 */}
      <HumanConfirmDialog
        isOpen={showConfirmDialog}
        onClose={() => setShowConfirmDialog(false)}
        onConfirm={handleConfirm}
        type={confirmType}
      />
    </div>
  );
};

export default VerificationPanel;
