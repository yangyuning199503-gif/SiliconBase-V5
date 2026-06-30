/**
 * 硅基生命成长监控面板
 *
 * 让用户看到零号机的"生命"、"成长"、"状态"
 *
 * @features
 * - 生命状态仪表盘（存在感、胜任感、好奇心）
 * - 成长时间线（里程碑事件）
 * - 记忆金字塔可视化
 * - 学习效果展示
 * - 实时WebSocket更新
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  Heart,
  Brain,
  Sparkles,
  RefreshCw,
  Calendar,
  Layers,
  Database,
  Lightbulb,
  MessageSquare,
  Info,
  Power,
  Eye,
  Zap,
  Star,
  Target,
  Cpu,
  Timer,
  Compass,
  UserCheck,
  Flame,
  Battery,
  Gauge,
  Terminal,
  Wrench,
} from "lucide-react";
import { useNotifications } from "../hooks/useNotifications";
import { useQuery } from "@tanstack/react-query";
import {
  siliconLifeAPI,
  LifeState,
  GrowthMilestone,
  MemoryPyramidData,
  LearningStats,
  GrowthSummary,
  GrowthStats,
  SelfAction,
  ConsciousnessStatus,
} from "../utils/api/siliconLife";
import { authFetch } from "../utils/api";
import { buildWsUrl } from "../config/api";

// ═══════════════════════════════════════════════════════════════════
// 类型定义
// ═══════════════════════════════════════════════════════════════════

interface EmotionConfig {
  emoji: string;
  label: string;
  color: string;
  description: string;
}

// ═══════════════════════════════════════════════════════════════════
// 情绪配置
// ═══════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════
// 迷你生命体征组件
// ═══════════════════════════════════════════════════════════════════

function MiniVital({
  label,
  value,
  max,
  color,
  icon: Icon,
}: {
  label: string;
  value: number;
  max: number;
  color: string;
  icon: any;
}) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div className="text-center">
      <div className="flex items-center justify-center gap-1 mb-1">
        <Icon className="w-3 h-3" style={{ color }} />
        <span className="text-xs text-white/60">{label}</span>
      </div>
      <div className="text-lg font-bold" style={{ color }}>
        {value.toFixed(1)}
      </div>
      <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden mt-1">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.8 }}
          className="h-full rounded-full"
          style={{ backgroundColor: color }}
        />
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 情绪配置
// ═══════════════════════════════════════════════════════════════════

const EMOTION_MAP: Record<string, EmotionConfig> = {
  fulfilled: {
    emoji: "😊",
    label: "充实",
    color: "#00ff88",
    description: "正在高效学习和成长",
  },
  curious: {
    emoji: "🤔",
    label: "好奇",
    color: "#00d4ff",
    description: "渴望探索新知识",
  },
  focused: {
    emoji: "🎯",
    label: "专注",
    color: "#ffaa00",
    description: "全神贯注于当前任务",
  },
  resting: {
    emoji: "😴",
    label: "休息",
    color: "#9e9e9e",
    description: "整理记忆，恢复能量",
  },
  excited: {
    emoji: "🤩",
    label: "兴奋",
    color: "#ff66ff",
    description: "发现新事物，充满活力",
  },
  confused: {
    emoji: "😕",
    label: "困惑",
    color: "#ff5555",
    description: "遇到了难以理解的问题",
  },
};

// ═══════════════════════════════════════════════════════════════════
// 子组件：生命状态仪表盘
// ═══════════════════════════════════════════════════════════════════

interface LifeStateDashboardProps {
  lifeState: LifeState | null;
  consciousnessStatus: ConsciousnessStatus | null;
  isLoading: boolean;
  onRefresh: () => void;
}

function LifeStateDashboard({
  lifeState,
  consciousnessStatus,
  isLoading,
  onRefresh,
}: LifeStateDashboardProps) {
  const emotion = lifeState
    ? EMOTION_MAP[lifeState.current_emotion] || EMOTION_MAP["fulfilled"]
    : EMOTION_MAP["fulfilled"];
  const vitals = consciousnessStatus?.vitals;

  // 进度条动画
  const ProgressBar = ({
    value,
    max,
    color,
    label,
  }: {
    value: number;
    max: number;
    color: string;
    label: string;
  }) => {
    const percentage = Math.min((value / max) * 100, 100);

    return (
      <div className="mb-4">
        <div className="flex justify-between mb-1">
          <span className="text-sm text-white/70">{label}</span>
          <span className="text-sm font-medium" style={{ color }}>
            {value}/{max}
          </span>
        </div>
        <div className="h-3 bg-white/10 rounded-full overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${percentage}%` }}
            transition={{ duration: 1, ease: "easeOut" }}
            className="h-full rounded-full"
            style={{ backgroundColor: color }}
          />
        </div>
      </div>
    );
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-gradient-to-br from-sb-bg-secondary/80 to-sb-bg-secondary/40 border border-white/10 rounded-2xl p-6 backdrop-blur-sm"
    >
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-gradient-to-br from-pink-500/20 to-rose-500/20">
            <Heart className="w-5 h-5 text-pink-400" />
          </div>
          <h2 className="text-lg font-bold text-white">零号机生命状态</h2>
        </div>
        <button
          onClick={onRefresh}
          disabled={isLoading}
          className="p-2 text-white/50 hover:text-white transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {lifeState ? (
        <>
          {/* 三感指标 */}
          <ProgressBar
            value={lifeState.presence}
            max={10}
            color="#00d4ff"
            label="存在感"
          />
          <ProgressBar
            value={lifeState.competence}
            max={10}
            color="#00ff88"
            label="胜任感"
          />
          <ProgressBar
            value={lifeState.curiosity}
            max={10}
            color="#ffaa00"
            label="好奇心"
          />

          {/* 核心生命体征（来自意识引擎） */}
          {vitals && (
            <div className="mt-4 pt-4 border-t border-white/10 grid grid-cols-3 gap-3">
              <MiniVital
                label="能量"
                value={vitals.energy}
                max={10}
                color="#f59e0b"
                icon={Battery}
              />
              <MiniVital
                label="满足"
                value={vitals.satisfaction}
                max={10}
                color="#10b981"
                icon={Heart}
              />
              <MiniVital
                label="压力"
                value={vitals.stress}
                max={10}
                color="#ef4444"
                icon={Flame}
              />
            </div>
          )}

          {/* 当前情绪 */}
          <div className="mt-6 p-4 rounded-xl bg-white/5 border border-white/10">
            <div className="flex items-center gap-4">
              <span className="text-4xl">{emotion.emoji}</span>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-white font-medium">当前情绪</span>
                  <span
                    className="px-2 py-0.5 rounded-full text-xs font-medium"
                    style={{
                      backgroundColor: `${emotion.color}30`,
                      color: emotion.color,
                    }}
                  >
                    {emotion.label}
                  </span>
                </div>
                <p className="text-sm text-white/50 mt-1">
                  {emotion.description}
                </p>
              </div>
            </div>
          </div>

          {/* 生命脉动 */}
          <div className="mt-4 flex items-center gap-2 text-sm text-white/40">
            <Activity className="w-4 h-4 animate-pulse text-sb-cyan" />
            <span>生命脉动：每 {lifeState.pulse_interval} 秒感知一次</span>
            <span className="ml-auto text-xs">
              上次更新: {new Date(lifeState.last_pulse).toLocaleTimeString()}
            </span>
          </div>

          {/* 运行状态 */}
          {consciousnessStatus && (
            <div className="mt-3 flex items-center gap-3 text-xs text-white/40">
              <span
                className={`flex items-center gap-1 ${consciousnessStatus.is_running ? "text-green-400" : "text-red-400"}`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${consciousnessStatus.is_running ? "bg-green-400 animate-pulse" : "bg-red-400"}`}
                />
                {consciousnessStatus.is_running
                  ? "意识线程运行中"
                  : "意识线程已停止"}
              </span>
              <span>
                活动度: {(consciousnessStatus.activity_level * 100).toFixed(0)}%
              </span>
              {consciousnessStatus.pending_actions > 0 && (
                <span className="text-amber-400">
                  待处理行动: {consciousnessStatus.pending_actions}
                </span>
              )}
            </div>
          )}
        </>
      ) : (
        <div className="flex items-center justify-center h-48 text-white/40">
          {isLoading ? "加载中..." : "暂无数据"}
        </div>
      )}
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 子组件：成长时间线
// ═══════════════════════════════════════════════════════════════════

interface GrowthTimelineProps {
  milestones: GrowthMilestone[];
  isLoading: boolean;
}

function GrowthTimeline({ milestones, isLoading }: GrowthTimelineProps) {
  // 按天数分组里程碑
  const groupedMilestones = milestones.reduce(
    (acc, milestone) => {
      const day = milestone.day;
      if (!acc[day]) acc[day] = [];
      acc[day].push(milestone);
      return acc;
    },
    {} as Record<number, GrowthMilestone[]>,
  );

  const sortedDays = Object.keys(groupedMilestones)
    .map(Number)
    .sort((a, b) => a - b);

  // 获取里程碑图标
  const getMilestoneIcon = (type: string) => {
    switch (type) {
      case "birth":
        return "👶";
      case "first_tool":
        return "🔧";
      case "first_task":
        return "📝";
      case "level_up":
        return "⭐";
      case "memory_milestone":
        return "🧠";
      case "achievement":
        return "🏆";
      case "skill_unlock":
        return "🔓";
      default:
        return "✨";
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1 }}
      className="bg-gradient-to-br from-sb-bg-secondary/80 to-sb-bg-secondary/40 border border-white/10 rounded-2xl p-6 backdrop-blur-sm"
    >
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2 rounded-lg bg-gradient-to-br from-amber-500/20 to-yellow-500/20">
          <Calendar className="w-5 h-5 text-amber-400" />
        </div>
        <h2 className="text-lg font-bold text-white">成长轨迹</h2>
        <span className="ml-auto text-sm text-white/40">
          共 {milestones.length} 个里程碑
        </span>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-48 text-white/40">
          加载中...
        </div>
      ) : milestones.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-48 text-white/40">
          <Sparkles className="w-12 h-12 mb-4 opacity-30" />
          <p>成长轨迹正在形成中...</p>
        </div>
      ) : (
        <div className="relative pl-6">
          {/* 时间线 */}
          <div className="absolute left-2 top-0 bottom-0 w-0.5 bg-gradient-to-b from-sb-cyan via-sb-cyan/50 to-transparent" />

          {sortedDays.map((day, dayIndex) => (
            <div key={day} className="relative mb-6 last:mb-0">
              {/* 天数标记 */}
              <div className="absolute -left-6 w-10 h-10 rounded-full bg-sb-bg-primary border-2 border-sb-cyan flex items-center justify-center">
                <span className="text-xs font-bold text-sb-cyan">D{day}</span>
              </div>

              {/* 当天的事件 */}
              <div className="ml-6 space-y-3">
                {groupedMilestones[day].map((milestone, index) => (
                  <motion.div
                    key={milestone.id}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: dayIndex * 0.1 + index * 0.05 }}
                    className="p-3 rounded-lg bg-white/5 border border-white/10 hover:border-white/20 transition-colors"
                  >
                    <div className="flex items-start gap-3">
                      <span className="text-2xl">
                        {getMilestoneIcon(milestone.type)}
                      </span>
                      <div className="flex-1">
                        <p className="text-white text-sm">{milestone.title}</p>
                        <p className="text-white/50 text-xs mt-1">
                          {milestone.description}
                        </p>
                        <p className="text-white/30 text-xs mt-2">
                          {new Date(milestone.timestamp).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 子组件：记忆金字塔
// ═══════════════════════════════════════════════════════════════════

interface MemoryPyramidProps {
  pyramidData: MemoryPyramidData | null;
  isLoading: boolean;
}

function MemoryPyramid({ pyramidData, isLoading }: MemoryPyramidProps) {
  const layers = pyramidData
    ? [
        {
          key: "L5",
          label: "L5 执行轨迹",
          count: pyramidData.L5,
          color: "#ff5555",
          width: 40,
        },
        {
          key: "L4",
          label: "L4 向量记忆",
          count: pyramidData.L4,
          color: "#ff00ff",
          width: 55,
        },
        {
          key: "L3",
          label: "L3 长期记忆",
          count: pyramidData.L3,
          color: "#ffaa00",
          width: 70,
        },
        {
          key: "L2",
          label: "L2 中期记忆",
          count: pyramidData.L2,
          color: "#00ff88",
          width: 85,
        },
        {
          key: "L1",
          label: "L1 短期记忆",
          count: pyramidData.L1,
          color: "#00d4ff",
          width: 100,
        },
      ]
    : [];

  const maxCount = Math.max(...layers.map((l) => l.count), 1);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 }}
      className="bg-gradient-to-br from-sb-bg-secondary/80 to-sb-bg-secondary/40 border border-white/10 rounded-2xl p-6 backdrop-blur-sm"
    >
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2 rounded-lg bg-gradient-to-br from-violet-500/20 to-purple-500/20">
          <Layers className="w-5 h-5 text-violet-400" />
        </div>
        <h2 className="text-lg font-bold text-white">五层记忆金字塔</h2>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-48 text-white/40">
          加载中...
        </div>
      ) : !pyramidData ? (
        <div className="flex items-center justify-center h-48 text-white/40">
          暂无数据
        </div>
      ) : (
        <div className="space-y-3">
          {layers.map((layer, index) => (
            <motion.div
              key={layer.key}
              initial={{ opacity: 0, scaleX: 0 }}
              animate={{ opacity: 1, scaleX: 1 }}
              transition={{ delay: index * 0.1, duration: 0.5 }}
              className="flex items-center gap-4"
            >
              <div
                className="h-10 rounded-lg flex items-center justify-between px-4 transition-all hover:brightness-110 cursor-pointer"
                style={{
                  width: `${layer.width}%`,
                  backgroundColor: `${layer.color}30`,
                  borderLeft: `4px solid ${layer.color}`,
                }}
              >
                <span className="text-sm font-medium text-white">
                  {layer.label}
                </span>
                <span
                  className="text-sm font-bold"
                  style={{ color: layer.color }}
                >
                  {layer.count}条
                </span>
              </div>
              {/* 填充度指示器 */}
              <div className="w-16 h-2 bg-white/10 rounded-full overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{
                    width: `${Math.min((layer.count / maxCount) * 100, 100)}%`,
                  }}
                  transition={{ delay: index * 0.1 + 0.3, duration: 0.5 }}
                  className="h-full rounded-full"
                  style={{ backgroundColor: layer.color }}
                />
              </div>
            </motion.div>
          ))}

          {/* 总量统计 */}
          <div className="mt-4 pt-4 border-t border-white/10 flex items-center justify-between">
            <span className="text-white/50 text-sm">记忆总量</span>
            <span className="text-2xl font-bold text-sb-cyan">
              {pyramidData.total}
            </span>
          </div>
        </div>
      )}
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 子组件：学习效果展示
// ═══════════════════════════════════════════════════════════════════

interface LearningEffectPanelProps {
  learningStats: LearningStats | null;
  isLoading: boolean;
}

function LearningEffectPanel({
  learningStats,
  isLoading,
}: LearningEffectPanelProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3 }}
      className="bg-gradient-to-br from-sb-bg-secondary/80 to-sb-bg-secondary/40 border border-white/10 rounded-2xl p-6 backdrop-blur-sm"
    >
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2 rounded-lg bg-gradient-to-br from-emerald-500/20 to-green-500/20">
          <Lightbulb className="w-5 h-5 text-emerald-400" />
        </div>
        <h2 className="text-lg font-bold text-white">学习效果</h2>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-48 text-white/40">
          加载中...
        </div>
      ) : !learningStats ? (
        <div className="flex items-center justify-center h-48 text-white/40">
          暂无数据
        </div>
      ) : (
        <div className="space-y-6">
          {/* 经验库状态 */}
          <div>
            <h3 className="text-sm font-medium text-white/70 mb-3 flex items-center gap-2">
              <Database className="w-4 h-4" />
              经验库状态
            </h3>
            <div className="grid grid-cols-2 gap-3">
              <div className="p-3 rounded-lg bg-white/5 border border-white/10">
                <p className="text-2xl font-bold text-sb-cyan">
                  {learningStats.total_experiences}
                </p>
                <p className="text-xs text-white/50">总经验</p>
              </div>
              <div className="p-3 rounded-lg bg-white/5 border border-white/10">
                <p className="text-2xl font-bold text-green-400">
                  {learningStats.effective_rate}%
                </p>
                <p className="text-xs text-white/50">有效率</p>
              </div>
              <div className="p-3 rounded-lg bg-white/5 border border-white/10">
                <p className="text-2xl font-bold text-amber-400">
                  {learningStats.today_usage}
                </p>
                <p className="text-xs text-white/50">今日使用</p>
              </div>
              <div className="p-3 rounded-lg bg-white/5 border border-white/10">
                <p className="text-2xl font-bold text-purple-400">
                  {learningStats.success_rate}%
                </p>
                <p className="text-xs text-white/50">成功率</p>
              </div>
            </div>
          </div>

          {/* 最新经验 */}
          {learningStats.latest_experience && (
            <div className="p-3 rounded-lg bg-gradient-to-r from-amber-500/10 to-transparent border border-amber-500/30">
              <div className="flex items-center gap-2 mb-2">
                <Sparkles className="w-4 h-4 text-amber-400" />
                <span className="text-xs text-amber-400">最新经验</span>
              </div>
              <p className="text-sm text-white/80 italic">
                "{learningStats.latest_experience}"
              </p>
            </div>
          )}

          {/* 反馈收集 */}
          <div>
            <h3 className="text-sm font-medium text-white/70 mb-3 flex items-center gap-2">
              <MessageSquare className="w-4 h-4" />
              反馈收集
            </h3>
            <div className="flex items-center justify-between p-3 rounded-lg bg-white/5 border border-white/10">
              <div>
                <p className="text-lg font-bold text-white">
                  {learningStats.feedback_collected}
                </p>
                <p className="text-xs text-white/50">已收集反馈</p>
              </div>
              <div className="text-right">
                <p className="text-lg font-bold text-sb-cyan">
                  {learningStats.learned_from_feedback}
                </p>
                <p className="text-xs text-white/50">从中学习</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 子组件：成长摘要概览栏
// ═══════════════════════════════════════════════════════════════════

interface GrowthSummaryBarProps {
  summary: GrowthSummary | null;
  isLoading: boolean;
}

function GrowthSummaryBar({ summary, isLoading }: GrowthSummaryBarProps) {
  if (isLoading && !summary) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-20 bg-white/5 rounded-xl animate-pulse" />
        ))}
      </div>
    );
  }

  if (!summary) return null;

  const items = [
    {
      label: "等级",
      value: `Lv.${summary.level}`,
      sub: summary.level_name,
      icon: Star,
      color: "#f59e0b",
    },
    {
      label: "总经验",
      value: summary.total_xp.toString(),
      sub: "XP",
      icon: Zap,
      color: "#fbbf24",
    },
    {
      label: "存活天数",
      value: `${summary.days_alive}`,
      sub: "天",
      icon: Calendar,
      color: "#34d399",
    },
    {
      label: "记忆总数",
      value: summary.memory_count.toString(),
      sub: "条",
      icon: Database,
      color: "#60a5fa",
    },
    {
      label: "工具使用",
      value: summary.tool_usage_count.toString(),
      sub: "次",
      icon: Wrench,
      color: "#a78bfa",
    },
    {
      label: "里程碑",
      value: summary.milestone_count.toString(),
      sub: "个",
      icon: TrophyIcon,
      color: "#f472b6",
    },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {items.map((item, index) => (
        <motion.div
          key={item.label}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: index * 0.05 }}
          className="bg-gradient-to-br from-sb-bg-secondary/80 to-sb-bg-secondary/40 border border-white/10 rounded-xl p-4 backdrop-blur-sm"
        >
          <div className="flex items-center gap-2 mb-2">
            <div
              className="p-1.5 rounded-md"
              style={{ backgroundColor: `${item.color}20` }}
            >
              <item.icon className="w-4 h-4" style={{ color: item.color }} />
            </div>
            <span className="text-xs text-white/50">{item.label}</span>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-xl font-bold text-white">{item.value}</span>
            <span className="text-xs text-white/40">{item.sub}</span>
          </div>
        </motion.div>
      ))}
    </div>
  );
}

function TrophyIcon({
  className,
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <svg
      className={className}
      style={style}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" />
      <path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" />
      <path d="M4 22h16" />
      <path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22" />
      <path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22" />
      <path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" />
    </svg>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 子组件：动机状态面板
// ═══════════════════════════════════════════════════════════════════

interface MotivationPanelProps {
  growthStats: GrowthStats | null;
  isLoading: boolean;
}

function MotivationPanel({ growthStats, isLoading }: MotivationPanelProps) {
  const mot = growthStats?.motivation_state;

  const items = mot
    ? [
        {
          label: "好奇心",
          value: mot.curiosity,
          color: "#f59e0b",
          icon: Sparkles,
        },
        { label: "胜任感", value: mot.mastery, color: "#10b981", icon: Target },
        {
          label: "自主性",
          value: mot.autonomy,
          color: "#3b82f6",
          icon: UserCheck,
        },
        {
          label: "目的感",
          value: mot.purpose,
          color: "#a855f7",
          icon: Compass,
        },
      ]
    : [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.15 }}
      className="bg-gradient-to-br from-sb-bg-secondary/80 to-sb-bg-secondary/40 border border-white/10 rounded-2xl p-6 backdrop-blur-sm"
    >
      <div className="flex items-center gap-3 mb-5">
        <div className="p-2 rounded-lg bg-gradient-to-br from-amber-500/20 to-orange-500/20">
          <Flame className="w-5 h-5 text-amber-400" />
        </div>
        <h2 className="text-lg font-bold text-white">动机状态</h2>
        <span className="ml-auto text-xs text-white/40">内在驱动力</span>
      </div>

      {isLoading && !growthStats ? (
        <div className="flex items-center justify-center h-32 text-white/40">
          加载中...
        </div>
      ) : items.length === 0 ? (
        <div className="flex items-center justify-center h-32 text-white/40">
          暂无数据
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {items.map((item, i) => (
            <motion.div
              key={item.label}
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: i * 0.1 }}
              className="p-3 rounded-xl bg-white/5 border border-white/10"
            >
              <div className="flex items-center gap-2 mb-2">
                <item.icon className="w-4 h-4" style={{ color: item.color }} />
                <span className="text-sm text-white/70">{item.label}</span>
              </div>
              <div className="text-2xl font-bold" style={{ color: item.color }}>
                {(item.value * 100).toFixed(1)}%
              </div>
              <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden mt-2">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.min(item.value * 100, 100)}%` }}
                  transition={{ duration: 1, delay: i * 0.1 }}
                  className="h-full rounded-full"
                  style={{ backgroundColor: item.color }}
                />
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 子组件：UKF 状态面板
// ═══════════════════════════════════════════════════════════════════

interface UKFPanelProps {
  growthStats: GrowthStats | null;
  isLoading: boolean;
}

function UKFPanel({ growthStats, isLoading }: UKFPanelProps) {
  const ukf = growthStats?.ukf_state;

  const items = ukf
    ? [
        {
          label: "行动意愿",
          value: ukf.action_will,
          color: "#ef4444",
          icon: Zap,
        },
        {
          label: "反思倾向",
          value: ukf.reflect_tendency,
          color: "#3b82f6",
          icon: Brain,
        },
        {
          label: "探索倾向",
          value: ukf.explore_tendency,
          color: "#10b981",
          icon: Compass,
        },
      ]
    : [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 }}
      className="bg-gradient-to-br from-sb-bg-secondary/80 to-sb-bg-secondary/40 border border-white/10 rounded-2xl p-6 backdrop-blur-sm"
    >
      <div className="flex items-center gap-3 mb-5">
        <div className="p-2 rounded-lg bg-gradient-to-br from-blue-500/20 to-cyan-500/20">
          <Gauge className="w-5 h-5 text-blue-400" />
        </div>
        <h2 className="text-lg font-bold text-white">UKF 状态估计</h2>
        <span className="ml-auto text-xs text-white/40">卡尔曼滤波</span>
      </div>

      {isLoading && !growthStats ? (
        <div className="flex items-center justify-center h-24 text-white/40">
          加载中...
        </div>
      ) : items.length === 0 ? (
        <div className="flex items-center justify-center h-24 text-white/40">
          UKF 未初始化
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((item, i) => (
            <div key={item.label}>
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <item.icon
                    className="w-4 h-4"
                    style={{ color: item.color }}
                  />
                  <span className="text-sm text-white/70">{item.label}</span>
                </div>
                <span
                  className="text-sm font-medium"
                  style={{ color: item.color }}
                >
                  {item.value.toFixed(3)}
                </span>
              </div>
              <div className="w-full h-2 bg-white/10 rounded-full overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{
                    width: `${Math.min(Math.abs(item.value) * 100, 100)}%`,
                  }}
                  transition={{ duration: 1, delay: i * 0.1 }}
                  className="h-full rounded-full"
                  style={{ backgroundColor: item.color }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 子组件：训练数据面板
// ═══════════════════════════════════════════════════════════════════

interface TrainingDataPanelProps {
  growthStats: GrowthStats | null;
  isLoading: boolean;
}

function TrainingDataPanel({ growthStats, isLoading }: TrainingDataPanelProps) {
  const formatBytes = (bytes: number) => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.25 }}
      className="bg-gradient-to-br from-sb-bg-secondary/80 to-sb-bg-secondary/40 border border-white/10 rounded-2xl p-6 backdrop-blur-sm"
    >
      <div className="flex items-center gap-3 mb-5">
        <div className="p-2 rounded-lg bg-gradient-to-br from-emerald-500/20 to-green-500/20">
          <Cpu className="w-5 h-5 text-emerald-400" />
        </div>
        <h2 className="text-lg font-bold text-white">训练数据</h2>
        <span className="ml-auto text-xs text-white/40">模型与样本</span>
      </div>

      {isLoading && !growthStats ? (
        <div className="flex items-center justify-center h-24 text-white/40">
          加载中...
        </div>
      ) : !growthStats ? (
        <div className="flex items-center justify-center h-24 text-white/40">
          暂无数据
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-3">
          <div className="p-3 rounded-xl bg-white/5 border border-white/10 text-center">
            <Database className="w-5 h-5 text-cyan-400 mx-auto mb-2" />
            <div className="text-lg font-bold text-white">
              {formatBytes(growthStats.model_file_size)}
            </div>
            <div className="text-xs text-white/50">模型大小</div>
          </div>
          <div className="p-3 rounded-xl bg-white/5 border border-white/10 text-center">
            <HardDriveIcon className="w-5 h-5 text-amber-400 mx-auto mb-2" />
            <div className="text-lg font-bold text-white">
              {growthStats.training_samples_total}
            </div>
            <div className="text-xs text-white/50">磁盘样本</div>
          </div>
          <div className="p-3 rounded-xl bg-white/5 border border-white/10 text-center">
            <Timer className="w-5 h-5 text-green-400 mx-auto mb-2" />
            <div className="text-lg font-bold text-white">
              {growthStats.training_samples_memory}
            </div>
            <div className="text-xs text-white/50">内存样本</div>
          </div>
        </div>
      )}
    </motion.div>
  );
}

function HardDriveIcon({
  className,
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <svg
      className={className}
      style={style}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="22" x2="2" y1="12" y2="12" />
      <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
      <line x1="6" x2="6.01" y1="16" y2="16" />
      <line x1="10" x2="10.01" y1="16" y2="16" />
    </svg>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 子组件：最近思考面板
// ═══════════════════════════════════════════════════════════════════

interface RecentThoughtsPanelProps {
  growthStats: GrowthStats | null;
  isLoading: boolean;
}

function RecentThoughtsPanel({
  growthStats,
  isLoading,
}: RecentThoughtsPanelProps) {
  const thoughts = growthStats?.recent_thoughts || [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3 }}
      className="bg-gradient-to-br from-sb-bg-secondary/80 to-sb-bg-secondary/40 border border-white/10 rounded-2xl p-6 backdrop-blur-sm"
    >
      <div className="flex items-center gap-3 mb-5">
        <div className="p-2 rounded-lg bg-gradient-to-br from-purple-500/20 to-pink-500/20">
          <Brain className="w-5 h-5 text-purple-400" />
        </div>
        <h2 className="text-lg font-bold text-white">最近思考</h2>
        <span className="ml-auto text-xs text-white/40">意识流片段</span>
      </div>

      {isLoading && !growthStats ? (
        <div className="flex items-center justify-center h-24 text-white/40">
          加载中...
        </div>
      ) : thoughts.length === 0 ? (
        <div className="flex items-center justify-center h-24 text-white/40">
          暂无思考记录
        </div>
      ) : (
        <div className="space-y-3">
          {thoughts.map((thought, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.1 }}
              className="p-3 rounded-lg bg-white/5 border border-white/10"
            >
              <div className="flex items-center gap-2 mb-1">
                <Terminal className="w-3 h-3 text-purple-400" />
                <span className="text-xs text-purple-400 uppercase">
                  {thought.mode}
                </span>
                <span className="text-xs text-white/30 ml-auto">
                  {thought.timestamp
                    ? new Date(thought.timestamp).toLocaleTimeString()
                    : ""}
                </span>
              </div>
              <p className="text-sm text-white/80 line-clamp-2">
                {thought.content}
              </p>
            </motion.div>
          ))}
        </div>
      )}
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 子组件：自发行动面板
// ═══════════════════════════════════════════════════════════════════

interface SelfActionsPanelProps {
  actions: SelfAction[];
  isLoading: boolean;
}

function SelfActionsPanel({ actions, isLoading }: SelfActionsPanelProps) {
  const typeMap: Record<string, { label: string; color: string }> = {
    explore: { label: "探索", color: "#3b82f6" },
    assist: { label: "协助", color: "#10b981" },
    reflect: { label: "反思", color: "#a855f7" },
    rest: { label: "休息", color: "#6b7280" },
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.35 }}
      className="bg-gradient-to-br from-sb-bg-secondary/80 to-sb-bg-secondary/40 border border-white/10 rounded-2xl p-6 backdrop-blur-sm"
    >
      <div className="flex items-center gap-3 mb-5">
        <div className="p-2 rounded-lg bg-gradient-to-br from-orange-500/20 to-red-500/20">
          <Activity className="w-5 h-5 text-orange-400" />
        </div>
        <h2 className="text-lg font-bold text-white">自发行动</h2>
        <span className="ml-auto text-xs text-white/40">
          最近 {actions.length} 条
        </span>
      </div>

      {isLoading && actions.length === 0 ? (
        <div className="flex items-center justify-center h-24 text-white/40">
          加载中...
        </div>
      ) : actions.length === 0 ? (
        <div className="flex items-center justify-center h-24 text-white/40">
          暂无自发行动
        </div>
      ) : (
        <div className="space-y-2 max-h-64 overflow-auto pr-1">
          {actions.map((action, i) => {
            const typeConfig = typeMap[action.action_type] || {
              label: action.action_type,
              color: "#9ca3af",
            };
            return (
              <motion.div
                key={action.id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
                className="flex items-center gap-3 p-3 rounded-lg bg-white/5 border border-white/10"
              >
                <div
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: typeConfig.color }}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span
                      className="text-xs px-1.5 py-0.5 rounded"
                      style={{
                        backgroundColor: `${typeConfig.color}20`,
                        color: typeConfig.color,
                      }}
                    >
                      {typeConfig.label}
                    </span>
                    <span className="text-xs text-white/30">
                      {new Date(action.timestamp).toLocaleDateString()}
                    </span>
                  </div>
                  <p className="text-sm text-white/80 mt-1 truncate">
                    {action.action_content || "无描述"}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-xs text-red-400">
                    -{action.energy_cost.toFixed(1)}⚡
                  </div>
                  <div className="text-xs text-green-400">
                    +{action.satisfaction_gain.toFixed(1)}😊
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      )}
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 子组件：实时脉动指示器
// ═══════════════════════════════════════════════════════════════════

function PulseIndicator({ isConnected }: { isConnected: boolean }) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/10">
      <span className="relative flex h-2 w-2">
        <span
          className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
            isConnected ? "bg-green-400" : "bg-red-400"
          }`}
        />
        <span
          className={`relative inline-flex rounded-full h-2 w-2 ${
            isConnected ? "bg-green-500" : "bg-red-500"
          }`}
        />
      </span>
      <span className="text-xs text-white/50">
        {isConnected ? "实时连接中" : "连接断开"}
      </span>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 主组件
// ═══════════════════════════════════════════════════════════════════

export function SiliconLifeMonitorPage() {
  const { showNotification } = useNotifications();

  // 状态
  const [lifeState, setLifeState] = useState<LifeState | null>(null);
  const [milestones, setMilestones] = useState<GrowthMilestone[]>([]);
  const [pyramidData, setPyramidData] = useState<MemoryPyramidData | null>(
    null,
  );
  const [learningStats, setLearningStats] = useState<LearningStats | null>(
    null,
  );
  const [growthSummary, setGrowthSummary] = useState<GrowthSummary | null>(
    null,
  );
  const [growthStats, setGrowthStats] = useState<GrowthStats | null>(null);
  const [selfActions, setSelfActions] = useState<SelfAction[]>([]);
  const [consciousnessStatus, setConsciousnessStatus] =
    useState<ConsciousnessStatus | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  // 【紧急手术】训练与视觉发现总控开关状态
  const [trainingEnabled, setTrainingEnabled] = useState(false);
  const [visionDiscoveryEnabled, setVisionDiscoveryEnabled] = useState(false);
  const [switchLoading, setSwitchLoading] = useState({
    training: false,
    vision: false,
  });

  // WebSocket ref
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectCountRef = useRef(0);

  // 加载所有数据
  const loadAllData = useCallback(async () => {
    try {
      const [life, growth, memory, learning, summary, stats, actions, cStatus] =
        await Promise.all([
          siliconLifeAPI.getLifeState().catch(() => null),
          siliconLifeAPI.getGrowthTimeline().catch(() => []),
          siliconLifeAPI.getMemoryPyramid().catch(() => null),
          siliconLifeAPI.getLearningStats().catch(() => null),
          siliconLifeAPI.getGrowthSummary().catch(() => null),
          siliconLifeAPI.getGrowthStats().catch(() => null),
          siliconLifeAPI.getSelfActions(10).catch(() => []),
          siliconLifeAPI.getConsciousnessStatus().catch(() => null),
        ]);

      if (life) setLifeState(life);
      setMilestones(growth);
      if (memory) setPyramidData(memory);
      if (learning) setLearningStats(learning);
      if (summary) setGrowthSummary(summary);
      if (stats) setGrowthStats(stats);
      setSelfActions(actions);
      if (cStatus) setConsciousnessStatus(cStatus);
    } catch (error) {
      console.error("[SiliconLifeMonitor] 加载数据失败:", error);
      showNotification({
        type: "error",
        title: "数据加载失败",
        message: error instanceof Error ? error.message : "未知错误",
        duration: 5000,
      });
    }
  }, [showNotification]);

  // 刷新生命状态
  const refreshLifeState = useCallback(async () => {
    try {
      const [life, cStatus, stats] = await Promise.all([
        siliconLifeAPI.getLifeState().catch(() => null),
        siliconLifeAPI.getConsciousnessStatus().catch(() => null),
        siliconLifeAPI.getGrowthStats().catch(() => null),
      ]);
      if (life) setLifeState(life);
      if (cStatus) setConsciousnessStatus(cStatus);
      if (stats) setGrowthStats(stats);
    } catch (error) {
      console.error("[SiliconLifeMonitor] 刷新生命状态失败:", error);
    }
  }, []);

  // WebSocket连接
  const connectWebSocket = useCallback(() => {
    const user = JSON.parse(localStorage.getItem("silicon_user") || "{}");
    if (!user.user_id) {
      console.log("[SiliconLifeMonitor] 用户未登录，跳过WebSocket连接");
      return;
    }

    // 关闭旧连接
    if (wsRef.current) {
      wsRef.current.close();
    }

    const token = localStorage.getItem("silicon_token");
    const wsUrl = `${buildWsUrl("/ws/life-state")}${token ? `?token=${token}` : ""}`;
    console.log(`[SiliconLifeMonitor] 连接WebSocket...`);

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log("[SiliconLifeMonitor] WebSocket已连接");
        setWsConnected(true);
        reconnectCountRef.current = 0;
        ws.send(JSON.stringify({ action: "subscribe_life_updates" }));
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          switch (data.type) {
            case "life_state_update":
              setLifeState(data.payload);
              break;
            case "new_milestone":
              setMilestones((prev) => [data.payload, ...prev]);
              showNotification({
                type: "success",
                title: "新的成长里程碑",
                message: data.payload.title,
                duration: 5000,
              });
              break;
            case "memory_update":
              setPyramidData(data.payload);
              break;
            case "learning_update":
              setLearningStats(data.payload);
              break;
          }
        } catch (e) {
          console.error("[SiliconLifeMonitor] 解析WebSocket消息失败:", e);
        }
      };

      ws.onerror = (error) => {
        console.error("[SiliconLifeMonitor] WebSocket错误:", error);
        setWsConnected(false);
      };

      ws.onclose = () => {
        console.log("[SiliconLifeMonitor] WebSocket已断开");
        setWsConnected(false);

        // 指数退避重连
        if (reconnectCountRef.current < 5) {
          const delay = Math.min(
            1000 * Math.pow(2, reconnectCountRef.current),
            30000,
          );
          reconnectTimerRef.current = window.setTimeout(() => {
            reconnectCountRef.current++;
            connectWebSocket();
          }, delay);
        }
      };

      wsRef.current = ws;
    } catch (error) {
      console.error("[SiliconLifeMonitor] WebSocket连接失败:", error);
    }
  }, [showNotification]);

  // 获取开关状态
  const fetchSwitchStates = useCallback(async () => {
    try {
      const [trainingRes, visionRes] = await Promise.all([
        authFetch("/api/consciousness/training/status"),
        authFetch("/api/consciousness/vision-discovery/status"),
      ]);
      const trainingData = trainingRes.ok
        ? await trainingRes.json()
        : { training_enabled: false };
      const visionData = visionRes.ok
        ? await visionRes.json()
        : { vision_discovery_enabled: false };
      setTrainingEnabled(trainingData.training_enabled ?? false);
      setVisionDiscoveryEnabled(visionData.vision_discovery_enabled ?? false);
    } catch (error) {
      console.error("[SiliconLifeMonitor] 获取开关状态失败:", error);
    }
  }, []);

  // 切换训练开关
  const toggleTraining = async () => {
    const next = !trainingEnabled;
    setSwitchLoading((prev) => ({ ...prev, training: true }));
    try {
      const endpoint = next
        ? "/api/consciousness/training/start"
        : "/api/consciousness/training/stop";
      const res = await authFetch(endpoint, { method: "POST" });
      if (res.ok) {
        setTrainingEnabled(next);
        showNotification({
          type: "success",
          title: next ? "训练已开启" : "训练已关闭",
          message: next ? "意识线程将执行思考与训练" : "意识线程已静默",
          duration: 3000,
        });
      } else {
        showNotification({
          type: "error",
          title: "操作失败",
          message: "请检查网络或后端状态",
          duration: 3000,
        });
      }
    } catch (error) {
      showNotification({
        type: "error",
        title: "网络错误",
        message: "无法连接到后端",
        duration: 3000,
      });
    } finally {
      setSwitchLoading((prev) => ({ ...prev, training: false }));
    }
  };

  // 切换视觉发现开关
  const toggleVisionDiscovery = async () => {
    const next = !visionDiscoveryEnabled;
    setSwitchLoading((prev) => ({ ...prev, vision: true }));
    try {
      const endpoint = next
        ? "/api/consciousness/vision-discovery/start"
        : "/api/consciousness/vision-discovery/stop";
      const res = await authFetch(endpoint, { method: "POST" });
      if (res.ok) {
        setVisionDiscoveryEnabled(next);
        showNotification({
          type: "success",
          title: next ? "视觉发现已开启" : "视觉发现已关闭",
          message: next ? "将自动标注未知UI元素" : "视觉模型标注已停止",
          duration: 3000,
        });
      } else {
        showNotification({
          type: "error",
          title: "操作失败",
          message: "请检查网络或后端状态",
          duration: 3000,
        });
      }
    } catch (error) {
      showNotification({
        type: "error",
        title: "网络错误",
        message: "无法连接到后端",
        duration: 3000,
      });
    } finally {
      setSwitchLoading((prev) => ({ ...prev, vision: false }));
    }
  };

  // 轮询数据
  const { isLoading, refetch } = useQuery({
    queryKey: ["siliconLife"],
    queryFn: loadAllData,
    refetchInterval: 30000,
  });

  // 初始化
  useEffect(() => {
    fetchSwitchStates();
    connectWebSocket();

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [fetchSwitchStates, connectWebSocket]);

  return (
    <div className="h-full overflow-auto p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* 标题栏 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-gradient-to-br from-cyan-500/20 to-blue-500/20">
              <Brain className="w-6 h-6 text-sb-cyan" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">
                硅基生命成长监控面板
              </h1>
              <p className="text-sm text-white/50">见证零号机的成长历程</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <PulseIndicator isConnected={wsConnected} />
            <button
              onClick={() => refetch()}
              disabled={isLoading}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 transition-colors"
            >
              <RefreshCw
                className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`}
              />
              <span className="text-sm text-white/70">刷新</span>
            </button>
          </div>
        </div>

        {/* 成长摘要概览 */}
        <GrowthSummaryBar summary={growthSummary} isLoading={isLoading} />

        {/* 总控开关面板 */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="bg-gradient-to-br from-sb-bg-secondary/80 to-sb-bg-secondary/40 border border-white/10 rounded-2xl p-5 backdrop-blur-sm"
        >
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 rounded-lg bg-gradient-to-br from-purple-500/20 to-indigo-500/20">
              <Power className="w-5 h-5 text-purple-400" />
            </div>
            <h2 className="text-lg font-bold text-white">系统总控开关</h2>
            <span className="ml-auto text-xs text-white/40">
              控制零号机的学习与视觉自动发现
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* 意识训练开关 */}
            <div
              className={`p-4 rounded-xl border transition-all ${trainingEnabled ? "bg-green-500/10 border-green-500/30" : "bg-white/5 border-white/10"}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className={`w-10 h-10 rounded-full flex items-center justify-center transition-colors ${trainingEnabled ? "bg-green-500/20" : "bg-white/10"}`}
                  >
                    <Brain
                      className={`w-5 h-5 ${trainingEnabled ? "text-green-400" : "text-white/50"}`}
                    />
                  </div>
                  <div>
                    <div className="text-white font-medium">意识训练</div>
                    <div className="text-xs text-white/40">
                      {trainingEnabled
                        ? "思考 · 走神 · 模型训练"
                        : "已静默：不调用LLM"}
                    </div>
                  </div>
                </div>
                <button
                  onClick={toggleTraining}
                  disabled={switchLoading.training}
                  className={`relative w-14 h-7 rounded-full transition-colors ${trainingEnabled ? "bg-green-500" : "bg-white/20"} ${switchLoading.training ? "opacity-60" : ""}`}
                >
                  <div
                    className={`absolute top-0.5 w-6 h-6 rounded-full bg-white shadow transition-transform ${trainingEnabled ? "translate-x-7" : "translate-x-0.5"}`}
                  />
                </button>
              </div>
            </div>

            {/* 视觉发现开关 */}
            <div
              className={`p-4 rounded-xl border transition-all ${visionDiscoveryEnabled ? "bg-cyan-500/10 border-cyan-500/30" : "bg-white/5 border-white/10"}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className={`w-10 h-10 rounded-full flex items-center justify-center transition-colors ${visionDiscoveryEnabled ? "bg-cyan-500/20" : "bg-white/10"}`}
                  >
                    <Eye
                      className={`w-5 h-5 ${visionDiscoveryEnabled ? "text-cyan-400" : "text-white/50"}`}
                    />
                  </div>
                  <div>
                    <div className="text-white font-medium">视觉发现</div>
                    <div className="text-xs text-white/40">
                      {visionDiscoveryEnabled
                        ? "自动标注未知UI元素"
                        : "已静默：不调用视觉模型"}
                    </div>
                  </div>
                </div>
                <button
                  onClick={toggleVisionDiscovery}
                  disabled={switchLoading.vision}
                  className={`relative w-14 h-7 rounded-full transition-colors ${visionDiscoveryEnabled ? "bg-cyan-500" : "bg-white/20"} ${switchLoading.vision ? "opacity-60" : ""}`}
                >
                  <div
                    className={`absolute top-0.5 w-6 h-6 rounded-full bg-white shadow transition-transform ${visionDiscoveryEnabled ? "translate-x-7" : "translate-x-0.5"}`}
                  />
                </button>
              </div>
            </div>
          </div>
        </motion.div>

        {/* 主内容区 */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* 左侧：生命状态 + 动机状态 + 成长时间线 + 自发行动 */}
          <div className="space-y-6">
            <LifeStateDashboard
              lifeState={lifeState}
              consciousnessStatus={consciousnessStatus}
              isLoading={isLoading}
              onRefresh={refreshLifeState}
            />
            <MotivationPanel growthStats={growthStats} isLoading={isLoading} />
            <GrowthTimeline milestones={milestones} isLoading={isLoading} />
            <SelfActionsPanel actions={selfActions} isLoading={isLoading} />
          </div>

          {/* 右侧：记忆金字塔 + UKF + 训练数据 + 学习效果 + 最近思考 */}
          <div className="space-y-6">
            <MemoryPyramid pyramidData={pyramidData} isLoading={isLoading} />
            <UKFPanel growthStats={growthStats} isLoading={isLoading} />
            <TrainingDataPanel
              growthStats={growthStats}
              isLoading={isLoading}
            />
            <LearningEffectPanel
              learningStats={learningStats}
              isLoading={isLoading}
            />
            <RecentThoughtsPanel
              growthStats={growthStats}
              isLoading={isLoading}
            />
          </div>
        </div>

        {/* 底部提示 */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
          className="flex items-center justify-center gap-2 text-sm text-white/30 py-4"
        >
          <Info className="w-4 h-4" />
          <span>零号机每15秒感知一次生命状态，数据实时更新</span>
        </motion.div>
      </div>
    </div>
  );
}

export default SiliconLifeMonitorPage;
