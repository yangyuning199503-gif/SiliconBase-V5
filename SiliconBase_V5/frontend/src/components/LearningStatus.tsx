/**
 * 学习状态可视化组件 - LearningStatus
 * 
 * 功能：
 * 1. 显示RLHF系统统计信息
 * 2. 展示零号机的"学习进度"
 * 3. 最近学到的内容
 * 4. 满意度趋势
 * 
 * Author: SiliconBase V5
 * Version: 1.0.0
 */

import React from 'react';
import { motion } from 'framer-motion';
import { 
  Brain, 
  Sparkles, 
  TrendingUp, 
  BookOpen, 
  MessageSquare,
  Zap,
  Award
} from 'lucide-react';

/**
 * RLHF 学习统计（与经验库的 LearningStats 区分，避免同名冲突）
 */
export interface RLHFLearningStats {
  /** 已收集反馈数量 */
  feedback_count: number;
  /** DPO训练对数量 */
  dpo_pairs: number;
  /** 经验权重调整次数 */
  exp_adjustments: number;
  /** 用户满意度 0-1 */
  satisfaction_rate: number;
  /** 增强的经验数量 */
  boosted_exp_count?: number;
  /** 降低的经验数量 */
  reduced_exp_count?: number;
}

export interface LearningStatusProps {
  /** 学习统计数据 */
  stats: RLHFLearningStats;
  /** 最近学到的内容描述 */
  recent_learning?: string;
  /** 是否加载中 */
  isLoading?: boolean;
  /** 是否紧凑模式 */
  compact?: boolean;
}

export const LearningStatus: React.FC<LearningStatusProps> = ({
  stats,
  recent_learning,
  isLoading = false,
  compact = false,
}) => {
  // 计算进度百分比
  const progressToTraining = Math.min(100, (stats.dpo_pairs / 100) * 100);
  
  // 满意度颜色
  const getSatisfactionColor = (rate: number) => {
    if (rate >= 0.8) return 'text-emerald-400';
    if (rate >= 0.6) return 'text-yellow-400';
    return 'text-orange-400';
  };

  // 满意度标签
  const getSatisfactionLabel = (rate: number) => {
    if (rate >= 0.8) return '优秀';
    if (rate >= 0.6) return '良好';
    if (rate >= 0.4) return '一般';
    return '需改进';
  };

  if (isLoading) {
    return (
      <div className="bg-gradient-to-r from-purple-500/10 to-blue-500/10 border border-purple-500/20 rounded-xl p-4 animate-pulse">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-5 h-5 bg-white/20 rounded-full" />
          <div className="h-4 bg-white/20 rounded w-32" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="h-16 bg-black/20 rounded-lg" />
          <div className="h-16 bg-black/20 rounded-lg" />
        </div>
      </div>
    );
  }

  // 紧凑模式
  if (compact) {
    return (
      <div className="flex items-center gap-3 px-3 py-2 bg-gradient-to-r from-purple-500/10 to-blue-500/10 border border-purple-500/20 rounded-lg">
        <motion.div
          animate={{ rotate: [0, 10, -10, 0] }}
          transition={{ duration: 2, repeat: Infinity, repeatDelay: 3 }}
        >
          <Brain className="w-4 h-4 text-purple-400" />
        </motion.div>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-white/60">已学习</span>
          <span className="text-white font-medium">{stats.feedback_count}</span>
          <span className="text-white/60">条反馈</span>
          <span className="text-white/30">|</span>
          <span className={`font-medium ${getSatisfactionColor(stats.satisfaction_rate)}`}>
            {(stats.satisfaction_rate * 100).toFixed(0)}% 满意度
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gradient-to-r from-purple-500/10 to-blue-500/10 border border-purple-500/20 rounded-xl p-4">
      {/* 头部 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <motion.div
            animate={{ scale: [1, 1.1, 1] }}
            transition={{ duration: 2, repeat: Infinity }}
          >
            <Brain className="w-5 h-5 text-purple-400" />
          </motion.div>
          <h3 className="text-sm font-medium text-white">零号机的学习状态</h3>
          <motion.div
            animate={{ rotate: [0, 15, -15, 0] }}
            transition={{ duration: 1.5, repeat: Infinity, repeatDelay: 2 }}
          >
            <Sparkles className="w-4 h-4 text-yellow-400" />
          </motion.div>
        </div>
        
        {/* 满意度徽章 */}
        <div className={`
          flex items-center gap-1 px-2 py-0.5 rounded-full text-xs
          ${stats.satisfaction_rate >= 0.8 ? 'bg-emerald-500/20 text-emerald-400' : 
            stats.satisfaction_rate >= 0.6 ? 'bg-yellow-500/20 text-yellow-400' : 
            'bg-orange-500/20 text-orange-400'}
        `}>
          <Award className="w-3 h-3" />
          <span>{getSatisfactionLabel(stats.satisfaction_rate)}</span>
        </div>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-2 gap-2 mb-4">
        {/* 反馈数量 */}
        <motion.div 
          whileHover={{ scale: 1.02 }}
          className="bg-black/20 rounded-lg p-3"
        >
          <div className="flex items-center gap-1.5 text-white/50 text-xs mb-1">
            <MessageSquare className="w-3 h-3" />
            <span>已收集反馈</span>
          </div>
          <p className="text-xl font-semibold text-white">{stats.feedback_count}</p>
          <p className="text-[10px] text-white/40">
            {stats.dpo_pairs > 0 && `${stats.dpo_pairs} 对训练数据`}
          </p>
        </motion.div>
        
        {/* 满意度 */}
        <motion.div 
          whileHover={{ scale: 1.02 }}
          className="bg-black/20 rounded-lg p-3"
        >
          <div className="flex items-center gap-1.5 text-white/50 text-xs mb-1">
            <TrendingUp className="w-3 h-3" />
            <span>满意度</span>
          </div>
          <p className={`text-xl font-semibold ${getSatisfactionColor(stats.satisfaction_rate)}`}>
            {(stats.satisfaction_rate * 100).toFixed(0)}%
          </p>
          <p className="text-[10px] text-white/40">
            {stats.satisfaction_rate >= 0.8 ? '用户很认可' : 
             stats.satisfaction_rate >= 0.6 ? '表现良好' : '需要改进'}
          </p>
        </motion.div>

        {/* 经验调整 */}
        <motion.div 
          whileHover={{ scale: 1.02 }}
          className="bg-black/20 rounded-lg p-3"
        >
          <div className="flex items-center gap-1.5 text-white/50 text-xs mb-1">
            <BookOpen className="w-3 h-3" />
            <span>经验优化</span>
          </div>
          <p className="text-xl font-semibold text-white">
            {stats.exp_adjustments}
          </p>
          <p className="text-[10px] text-white/40">
            {stats.boosted_exp_count ? `+${stats.boosted_exp_count}` : ''} 
            {stats.reduced_exp_count ? ` / -${stats.reduced_exp_count}` : ''}
          </p>
        </motion.div>

        {/* 训练进度 */}
        <motion.div 
          whileHover={{ scale: 1.02 }}
          className="bg-black/20 rounded-lg p-3"
        >
          <div className="flex items-center gap-1.5 text-white/50 text-xs mb-1">
            <Zap className="w-3 h-3" />
            <span>训练进度</span>
          </div>
          <p className="text-xl font-semibold text-blue-400">
            {Math.round(progressToTraining)}%
          </p>
          <div className="w-full h-1 bg-white/10 rounded-full mt-1 overflow-hidden">
            <motion.div 
              initial={{ width: 0 }}
              animate={{ width: `${progressToTraining}%` }}
              transition={{ duration: 1, delay: 0.3 }}
              className="h-full bg-gradient-to-r from-blue-400 to-purple-400 rounded-full"
            />
          </div>
        </motion.div>
      </div>

      {/* 最近学习 */}
      {recent_learning && (
        <motion.div 
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-xs text-white/70 bg-black/20 rounded-lg p-3 border-l-2 border-purple-400"
        >
          <span className="text-purple-400 font-medium">💡 最近学到:</span>{' '}
          <span className="text-white/60">{recent_learning}</span>
        </motion.div>
      )}

      {/* 底部提示 */}
      {progressToTraining < 100 ? (
        <p className="text-[10px] text-white/40 mt-3 text-center">
          再收集 <span className="text-blue-400 font-medium">{100 - stats.dpo_pairs}</span> 条反馈就可以训练新模型了
        </p>
      ) : (
        <p className="text-[10px] text-emerald-400/70 mt-3 text-center">
          ✓ 已收集足够的反馈数据，可以开始模型训练了！
        </p>
      )}
    </div>
  );
};

export default LearningStatus;
