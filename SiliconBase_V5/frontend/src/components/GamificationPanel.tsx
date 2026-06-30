/**
 * GamificationPanel - 游戏化面板组件
 * 
 * 功能：
 * - 显示用户等级、经验值进度条
 * - 显示工具分类解锁进度
 * - 成就列表
 * - 新解锁动画
 */

import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Trophy, 
  Star, 
  Zap, 
  Target, 
  Lock, 
  Unlock,
  Award,
  TrendingUp,
  Wrench,
  Cpu,
  Globe,
  Image,
  Music
} from 'lucide-react';
import { useGamification } from '../hooks/useGamification';

// 工具分类配置
const TOOL_CATEGORIES = [
  { id: 'basic', name: '基础工具', icon: Wrench, color: '#3b82f6', description: '文件管理、系统信息等基础功能' },
  { id: 'automation', name: '自动化', icon: Zap, color: '#f59e0b', description: '鼠标、键盘、窗口控制等自动化工具' },
  { id: 'web', name: '网络工具', icon: Globe, color: '#10b981', description: '网页搜索、内容获取等网络功能' },
  { id: 'vision', name: '视觉工具', icon: Image, color: '#8b5cf6', description: '截图、OCR、图像识别等视觉功能' },
  { id: 'media', name: '媒体工具', icon: Music, color: '#ec4899', description: '语音、音频处理等媒体功能' },
  { id: 'advanced', name: '高级工具', icon: Cpu, color: '#06b6d4', description: '代码生成、高级自动化等专业功能' },
];

// 成就列表
const ACHIEVEMENTS = [
  { id: 'first_step', name: '初出茅庐', description: '首次使用系统', icon: Star, xp: 10 },
  { id: 'tool_master', name: '工具大师', description: '使用10种不同的工具', icon: Wrench, xp: 50 },
  { id: 'automation_pro', name: '自动化专家', description: '连续执行5个自动化任务', icon: Zap, xp: 100 },
  { id: 'web_explorer', name: '网络探索者', description: '成功获取10个网页内容', icon: Globe, xp: 75 },
  { id: 'vision_expert', name: '视觉专家', description: '使用视觉工具20次', icon: Image, xp: 100 },
  { id: 'task_champion', name: '任务冠军', description: '完成一个复杂多步骤任务', icon: Trophy, xp: 200 },
  { id: 'level_5', name: '进阶用户', description: '达到等级5', icon: TrendingUp, xp: 0 },
  { id: 'level_10', name: '资深用户', description: '达到等级10', icon: Award, xp: 0 },
];

interface GamificationPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export const GamificationPanel: React.FC<GamificationPanelProps> = ({ isOpen, onClose }) => {
  const { status, simpleLevel, refresh } = useGamification();
  const [activeTab, setActiveTab] = useState<'overview' | 'categories' | 'achievements'>('overview');
  const [newUnlocks, setNewUnlocks] = useState<string[]>([]);

  useEffect(() => {
    if (isOpen) {
      refresh();
    }
  }, [isOpen, refresh]);

  // 检查新解锁的分类
  useEffect(() => {
    if (status?.categories) {
      const newlyUnlocked = status.categories
        .filter(cat => cat.is_unlocked && cat.progress === 100)
        .map(cat => cat.name);
      if (newlyUnlocked.length > 0) {
        setNewUnlocks(newlyUnlocked);
        const timer = setTimeout(() => setNewUnlocks([]), 3000);
        return () => clearTimeout(timer);
      }
    }
  }, [status]);

  if (!isOpen) return null;

  const levelInfo = simpleLevel || {
    level: 1,
    level_name: '新手',
    xp: 0,
    xp_to_next: 100,
    progress_percent: 0,
    color: '#3b82f6'
  };

  const progressColor = levelInfo.color || '#3b82f6';

  return (
    <>
      {/* 遮罩层 */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
      />

      {/* 面板 */}
      <motion.div
        initial={{ x: '100%' }}
        animate={{ x: 0 }}
        exit={{ x: '100%' }}
        transition={{ type: 'spring', damping: 25, stiffness: 200 }}
        className="fixed right-0 top-0 h-full w-96 bg-sb-bg-secondary border-l border-white/10 shadow-2xl z-50 flex flex-col"
      >
        {/* 头部 */}
        <div className="p-6 border-b border-white/10">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <Trophy className="w-6 h-6 text-yellow-400" />
              成长系统
            </h2>
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-white transition-colors"
            >
              ✕
            </button>
          </div>

          {/* 等级和进度 */}
          <div className="bg-gradient-to-br from-sb-cyan/20 to-purple-500/20 rounded-xl p-4 border border-white/10">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="text-sm text-slate-400">当前等级</p>
                <p className="text-2xl font-bold text-white flex items-center gap-2">
                  Lv.{levelInfo.level}
                  <span style={{ color: progressColor }}>{levelInfo.level_name}</span>
                </p>
              </div>
              <div className="w-16 h-16 rounded-full bg-white/10 flex items-center justify-center">
                <span className="text-3xl">{levelInfo.level >= 10 ? '👑' : levelInfo.level >= 5 ? '⭐' : '🌱'}</span>
              </div>
            </div>

            {/* 进度条 */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs text-slate-400">
                <span>经验值</span>
                <span>{levelInfo.xp} / {levelInfo.xp + levelInfo.xp_to_next} XP</span>
              </div>
              <div className="h-3 bg-slate-700 rounded-full overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${levelInfo.progress_percent}%` }}
                  transition={{ duration: 1, ease: 'easeOut' }}
                  className="h-full rounded-full"
                  style={{ backgroundColor: progressColor }}
                />
              </div>
              <p className="text-xs text-slate-500">
                还需 {levelInfo.xp_to_next} XP 升级
              </p>
            </div>
          </div>

          {/* 标签页切换 */}
          <div className="flex gap-2 mt-4">
            {[
              { id: 'overview', label: '概览', icon: Target },
              { id: 'categories', label: '工具分类', icon: Wrench },
              { id: 'achievements', label: '成就', icon: Award },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`flex-1 flex items-center justify-center gap-1 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
                  activeTab === tab.id
                    ? 'bg-sb-cyan/20 text-sb-cyan border border-sb-cyan/30'
                    : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                }`}
              >
                <tab.icon className="w-4 h-4" />
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* 内容区域 */}
        <div className="flex-1 overflow-y-auto p-6">
          <AnimatePresence mode="wait">
            {/* 概览标签 */}
            {activeTab === 'overview' && (
              <motion.div
                key="overview"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="space-y-4"
              >
                {/* 统计卡片 */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-slate-800/50 rounded-lg p-4 border border-white/5">
                    <p className="text-xs text-slate-400 mb-1">总使用次数</p>
                    <p className="text-2xl font-bold text-white">
                      {status?.stats?.total_tools_used || 0}
                    </p>
                  </div>
                  <div className="bg-slate-800/50 rounded-lg p-4 border border-white/5">
                    <p className="text-xs text-slate-400 mb-1">解锁工具</p>
                    <p className="text-2xl font-bold text-white">
                      {status?.stats?.unique_tools_used || 0}
                    </p>
                  </div>
                  <div className="bg-slate-800/50 rounded-lg p-4 border border-white/5">
                    <p className="text-xs text-slate-400 mb-1">解锁分类</p>
                    <p className="text-2xl font-bold text-white">
                      {status?.stats?.categories_unlocked || 0} / {status?.stats?.total_categories || 6}
                    </p>
                  </div>
                  <div className="bg-slate-800/50 rounded-lg p-4 border border-white/5">
                    <p className="text-xs text-slate-400 mb-1">获得成就</p>
                    <p className="text-2xl font-bold text-white">
                      {status?.stats?.achievements_count || 0}
                    </p>
                  </div>
                </div>

                {/* 最近活动 */}
                {status?.recent_activity && (
                  <div className="bg-slate-800/30 rounded-lg p-4 border border-white/5">
                    <p className="text-sm font-medium text-white mb-3">最近活动</p>
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between text-slate-400">
                        <span>最后活跃</span>
                        <span className="text-slate-300">
                          {new Date(status.recent_activity.last_active * 1000).toLocaleDateString('zh-CN')}
                        </span>
                      </div>
                      <div className="flex justify-between text-slate-400">
                        <span>加入时间</span>
                        <span className="text-slate-300">
                          {new Date(status.recent_activity.account_created * 1000).toLocaleDateString('zh-CN')}
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </motion.div>
            )}

            {/* 工具分类标签 */}
            {activeTab === 'categories' && (
              <motion.div
                key="categories"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="space-y-3"
              >
                {TOOL_CATEGORIES.map((category, index) => {
                  const catStatus = status?.categories?.find(c => c.name === category.name);
                  const isUnlocked = catStatus?.is_unlocked ?? levelInfo.level >= (catStatus?.unlock_level || 1);
                  const progress = catStatus?.progress || 0;

                  return (
                    <motion.div
                      key={category.id}
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: index * 0.05 }}
                      className={`relative bg-slate-800/30 rounded-lg p-4 border transition-all ${
                        isUnlocked 
                          ? 'border-white/10 hover:border-white/20' 
                          : 'border-white/5 opacity-60'
                      }`}
                    >
                      {/* 新解锁动画 */}
                      {newUnlocks.includes(category.name) && (
                        <motion.div
                          initial={{ scale: 1.2, opacity: 0 }}
                          animate={{ scale: 1, opacity: 1 }}
                          className="absolute -top-1 -right-1 w-3 h-3 bg-green-400 rounded-full animate-pulse"
                        />
                      )}

                      <div className="flex items-start gap-3">
                        <div 
                          className="w-10 h-10 rounded-lg flex items-center justify-center"
                          style={{ backgroundColor: `${category.color}20` }}
                        >
                          <category.icon 
                            className="w-5 h-5" 
                            style={{ color: isUnlocked ? category.color : '#64748b' }}
                          />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between mb-1">
                            <h3 className="font-medium text-white truncate">{category.name}</h3>
                            {isUnlocked ? (
                              <Unlock className="w-4 h-4 text-green-400" />
                            ) : (
                              <Lock className="w-4 h-4 text-slate-500" />
                            )}
                          </div>
                          <p className="text-xs text-slate-400 mb-2">{category.description}</p>
                          
                          {/* 进度条 */}
                          <div className="flex items-center gap-2">
                            <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                              <motion.div
                                initial={{ width: 0 }}
                                animate={{ width: `${progress}%` }}
                                transition={{ duration: 0.5, delay: index * 0.05 }}
                                className="h-full rounded-full"
                                style={{ backgroundColor: category.color }}
                              />
                            </div>
                            <span className="text-xs text-slate-500 w-10 text-right">{progress}%</span>
                          </div>

                          {!isUnlocked && catStatus?.unlock_level && (
                            <p className="text-xs text-slate-500 mt-2">
                              Lv.{catStatus.unlock_level} 解锁
                            </p>
                          )}
                        </div>
                      </div>
                    </motion.div>
                  );
                })}
              </motion.div>
            )}

            {/* 成就标签 */}
            {activeTab === 'achievements' && (
              <motion.div
                key="achievements"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="space-y-3"
              >
                {ACHIEVEMENTS.map((achievement, index) => {
                  const isUnlocked = (status?.stats?.achievements_count || 0) > index;

                  return (
                    <motion.div
                      key={achievement.id}
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: index * 0.05 }}
                      className={`flex items-center gap-3 p-3 rounded-lg border transition-all ${
                        isUnlocked
                          ? 'bg-gradient-to-r from-yellow-500/10 to-transparent border-yellow-500/20'
                          : 'bg-slate-800/30 border-white/5 opacity-60'
                      }`}
                    >
                      <div className={`w-12 h-12 rounded-full flex items-center justify-center ${
                        isUnlocked ? 'bg-yellow-500/20' : 'bg-slate-700'
                      }`}>
                        <achievement.icon className={`w-6 h-6 ${isUnlocked ? 'text-yellow-400' : 'text-slate-500'}`} />
                      </div>
                      <div className="flex-1">
                        <h3 className="font-medium text-white">{achievement.name}</h3>
                        <p className="text-xs text-slate-400">{achievement.description}</p>
                      </div>
                      {isUnlocked ? (
                        <span className="text-xs text-yellow-400 font-medium">已解锁</span>
                      ) : (
                        <span className="text-xs text-slate-500">+{achievement.xp} XP</span>
                      )}
                    </motion.div>
                  );
                })}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* 底部 */}
        <div className="p-4 border-t border-white/10 bg-slate-900/50">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Zap className="w-4 h-4 text-sb-cyan" />
            <span>每使用一个工具可获得经验值</span>
          </div>
        </div>
      </motion.div>
    </>
  );
};

export default GamificationPanel;
