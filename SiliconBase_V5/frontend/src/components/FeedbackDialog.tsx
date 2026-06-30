import React, { useState } from 'react';
import { Star, Send, X, MessageSquare, ThumbsUp } from 'lucide-react';

/**
 * 任务完成反馈弹窗组件
 * 
 * 功能：
 * 1. 1-5星评分
 * 2. 简短文字反馈
 * 3. 快速标签选择
 * 4. 提交后自动关闭
 * 
 * 隐私合规：
 * - 匿名化收集
 * - 用户可选择跳过
 * - 数据本地存储
 */

interface FeedbackDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (feedback: TaskFeedback) => void;
  taskId: string;
  templateName?: string;
}

export interface TaskFeedback {
  taskId: string;
  templateName: string;
  rating: number;
  feedback: string;
  quickTags: string[];
  timestamp: number;
}

const QUICK_TAGS = [
  { id: 'accurate', label: '结果准确', icon: '✓' },
  { id: 'fast', label: '响应快速', icon: '⚡' },
  { id: 'helpful', label: '非常有用', icon: '👍' },
  { id: 'clear', label: '解释清晰', icon: '📝' },
  { id: 'creative', label: '有创意', icon: '💡' },
  { id: 'needs_improve', label: '需要改进', icon: '🔧' },
];

const STAR_LABELS = ['非常不满意', '不满意', '一般', '满意', '非常满意'];

export const FeedbackDialog: React.FC<FeedbackDialogProps> = ({
  isOpen,
  onClose,
  onSubmit,
  taskId,
  templateName = 'balanced',
}) => {
  const [rating, setRating] = useState<number>(0);
  const [hoverRating, setHoverRating] = useState<number>(0);
  const [feedback, setFeedback] = useState<string>('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  if (!isOpen) return null;

  const handleTagToggle = (tagId: string) => {
    setSelectedTags(prev =>
      prev.includes(tagId)
        ? prev.filter(t => t !== tagId)
        : [...prev, tagId]
    );
  };

  const handleSubmit = async () => {
    if (rating === 0) return;

    setIsSubmitting(true);

    const feedbackData: TaskFeedback = {
      taskId,
      templateName,
      rating,
      feedback: feedback.trim(),
      quickTags: selectedTags,
      timestamp: Date.now(),
    };

    try {
      await onSubmit(feedbackData);
      // 重置状态
      setRating(0);
      setFeedback('');
      setSelectedTags([]);
      onClose();
    } catch (error) {
      console.error('[FeedbackDialog] 提交失败:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSkip = () => {
    setRating(0);
    setFeedback('');
    setSelectedTags([]);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="relative w-full max-w-md mx-4 bg-white dark:bg-gray-800 rounded-2xl shadow-2xl overflow-hidden animate-in fade-in zoom-in duration-200">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 bg-gradient-to-r from-blue-500 to-purple-600">
          <div className="flex items-center gap-2">
            <ThumbsUp className="w-5 h-5 text-white" />
            <h3 className="text-lg font-semibold text-white">
              任务完成评价
            </h3>
          </div>
          <button
            onClick={handleSkip}
            className="p-1 text-white/80 hover:text-white hover:bg-white/20 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* Rating Stars */}
          <div className="text-center space-y-3">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              请为本次任务执行效果评分
            </p>
            <div className="flex justify-center gap-2">
              {[1, 2, 3, 4, 5].map((star) => (
                <button
                  key={star}
                  onClick={() => setRating(star)}
                  onMouseEnter={() => setHoverRating(star)}
                  onMouseLeave={() => setHoverRating(0)}
                  className="p-1 transition-transform hover:scale-110 focus:outline-none"
                >
                  <Star
                    className={`w-10 h-10 transition-colors ${
                      star <= (hoverRating || rating)
                        ? 'fill-yellow-400 text-yellow-400'
                        : 'fill-gray-200 text-gray-200 dark:fill-gray-600 dark:text-gray-600'
                    }`}
                  />
                </button>
              ))}
            </div>
            {rating > 0 && (
              <p className="text-sm font-medium text-blue-600 dark:text-blue-400">
                {STAR_LABELS[rating - 1]}
              </p>
            )}
          </div>

          {/* Quick Tags */}
          <div className="space-y-2">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              快速标签（可多选）
            </p>
            <div className="flex flex-wrap gap-2">
              {QUICK_TAGS.map((tag) => (
                <button
                  key={tag.id}
                  onClick={() => handleTagToggle(tag.id)}
                  className={`px-3 py-1.5 text-sm rounded-full border transition-all ${
                    selectedTags.includes(tag.id)
                      ? 'bg-blue-500 text-white border-blue-500'
                      : 'bg-gray-100 text-gray-600 border-gray-200 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-600'
                  }`}
                >
                  <span className="mr-1">{tag.icon}</span>
                  {tag.label}
                </button>
              ))}
            </div>
          </div>

          {/* Text Feedback */}
          <div className="space-y-2">
            <label className="text-sm text-gray-500 dark:text-gray-400 flex items-center gap-2">
              <MessageSquare className="w-4 h-4" />
              详细反馈（可选）
            </label>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="请分享您的使用体验，帮助我们改进..."
              maxLength={200}
              rows={3}
              className="w-full px-4 py-3 text-sm bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
            />
            <p className="text-xs text-gray-400 text-right">
              {feedback.length}/200
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex gap-3 px-6 py-4 bg-gray-50 dark:bg-gray-700/50">
          <button
            onClick={handleSkip}
            className="flex-1 px-4 py-2.5 text-sm font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-xl transition-colors"
          >
            跳过
          </button>
          <button
            onClick={handleSubmit}
            disabled={rating === 0 || isSubmitting}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium text-white bg-gradient-to-r from-blue-500 to-purple-600 rounded-xl hover:from-blue-600 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            {isSubmitting ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                提交中...
              </>
            ) : (
              <>
                <Send className="w-4 h-4" />
                提交评价
              </>
            )}
          </button>
        </div>

        {/* Privacy Note */}
        <div className="px-6 pb-4 text-center">
          <p className="text-xs text-gray-400">
            🔒 您的反馈将匿名化处理，仅用于改进服务质量
          </p>
        </div>
      </div>
    </div>
  );
};

export default FeedbackDialog;
