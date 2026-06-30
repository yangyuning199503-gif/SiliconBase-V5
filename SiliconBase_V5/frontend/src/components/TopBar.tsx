import { useState } from 'react'
import { Settings, Activity, Cpu, User, LogOut, Sun, Target, Star, Zap, AlertCircle, X } from 'lucide-react'
import { Agent } from '../types'
import { useModeStore } from '../stores/modeStore'
import { useLevelInfo } from '../hooks/useGamification'
import { motion } from 'framer-motion'
import type { TaskStatus } from '../types'

interface UserInfo {
  username: string
  [key: string]: any
}

interface TopBarProps {
  currentAgent: Agent
  agents?: Agent[]
  onAgentSwitch?: (agent: Agent) => void
  activeTaskCount: number
  activeTasks?: TaskStatus[]
  user?: UserInfo | null
  onLogout?: () => void
  onNavigate?: (page: any) => void
  agentStatus?: string
}

// 等级进度组件
function LevelProgressBar() {
  const levelInfo = useLevelInfo()
  
  if (!levelInfo) return null
  
  return (
    <motion.div 
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="flex items-center gap-2 px-3 py-1.5 bg-[#232330] rounded-lg border border-white/15 cursor-pointer hover:border-amber-500/40 transition-all group"
      title={`等级 ${levelInfo.level} - ${levelInfo.level_name}\n经验值: ${levelInfo.xp} / ${levelInfo.xp + levelInfo.xp_to_next}\n距离下一级还需: ${levelInfo.xp_to_next} XP`}
    >
      {/* 等级图标 */}
      <div 
        className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
        style={{ 
          backgroundColor: `${levelInfo.color}30`,
          color: levelInfo.color,
          border: `1px solid ${levelInfo.color}50`
        }}
      >
        <Star className="w-3 h-3" />
      </div>
      
      {/* 等级信息 */}
      <div className="flex flex-col min-w-[60px]">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-medium text-white/90">
            Lv.{levelInfo.level}
          </span>
        </div>
        
        {/* 进度条 */}
        <div className="w-full h-1 bg-white/10 rounded-full mt-1 overflow-hidden">
          <motion.div 
            className="h-full rounded-full"
            style={{ backgroundColor: levelInfo.color }}
            initial={{ width: 0 }}
            animate={{ width: `${levelInfo.progress_percent}%` }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          />
        </div>
      </div>
      
      {/* 闪电图标 */}
      {levelInfo.progress_percent >= 80 && (
        <motion.div
          animate={{ scale: [1, 1.2, 1] }}
          transition={{ duration: 1, repeat: Infinity }}
        >
          <Zap className="w-3 h-3 text-amber-400" />
        </motion.div>
      )}
    </motion.div>
  )
}

export default function TopBar({ currentAgent, agents: _agents, onAgentSwitch: _onAgentSwitch, activeTaskCount, activeTasks: _activeTasks = [], user, onLogout, onNavigate, agentStatus: _agentStatus = 'idle' }: TopBarProps) {
  const { mode, switchMode, isLoading, error, clearError } = useModeStore()
  const [showError, setShowError] = useState(false)

  const handleModeSwitch = async (newMode: 'daily' | 'focus') => {
    clearError()
    setShowError(false)
    const success = await switchMode(newMode)
    if (!success) {
      setShowError(true)
      setTimeout(() => setShowError(false), 5000)
    }
  }

  return (
    <div className="h-16 bg-[#1e1e2a] border-b border-white/15 flex items-center justify-between px-4 shrink-0 relative z-40">
      {/* 左侧：Logo + 助手信息 */}
      <div className="flex items-center gap-4">
        {/* Logo */}
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
            <Cpu className="w-5 h-5 text-white" />
          </div>
          <div className="hidden sm:flex items-center gap-1">
            <span className="font-bold text-base tracking-tight text-white">SiliconBase</span>
            <span className="text-cyan-400 font-bold text-base">V5</span>
          </div>
        </div>

        {/* 分隔线 */}
        <div className="w-px h-6 bg-white/10 hidden sm:block" />

        {/* 当前助手信息 */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-[#232330] border border-white/10">
          <span className="text-xl">{currentAgent.icon}</span>
          <div className="hidden md:block text-left">
            <div className="font-medium text-sm text-white">{currentAgent.name}</div>
            <div className="text-[10px] text-white/40">{currentAgent.description}</div>
          </div>
        </div>
      </div>

      {/* 中间：模式切换 */}
      <div className="absolute left-1/2 -translate-x-1/2">
        <div className="flex items-center rounded-xl bg-[#232330] border border-white/15 p-1">
          <button
            onClick={() => handleModeSwitch('daily')}
            disabled={isLoading}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 ${
              mode === 'daily'
                ? 'bg-gradient-to-r from-amber-500 to-orange-500 text-white shadow-md'
                : 'text-white/60 hover:text-white hover:bg-white/5'
            } ${isLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
            title="日常模式 - AI会主动思考，适合日常对话"
          >
            <Sun className={`w-3.5 h-3.5 ${mode === 'daily' ? 'animate-spin-slow' : ''}`} />
            <span className="hidden sm:inline">日常</span>
          </button>
          <div className="w-px h-4 bg-white/10 mx-1" />
          <button
            onClick={() => handleModeSwitch('focus')}
            disabled={isLoading}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 ${
              mode === 'focus'
                ? 'bg-gradient-to-r from-cyan-500 to-teal-500 text-white shadow-md'
                : 'text-white/60 hover:text-white hover:bg-white/5'
            } ${isLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
            title="专注模式 - AI专注执行任务，适合工作流程"
          >
            <Target className={`w-3.5 h-3.5 ${mode === 'focus' ? 'animate-pulse' : ''}`} />
            <span className="hidden sm:inline">专注</span>
          </button>
        </div>

        {/* 加载状态 */}
        {isLoading && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="absolute -right-6 top-1/2 -translate-y-1/2"
          >
            <div className="w-4 h-4 border-2 border-white/20 border-t-cyan-400 rounded-full animate-spin" />
          </motion.div>
        )}
      </div>

      {/* 右侧：操作区 */}
      <div className="flex items-center gap-2">
        {/* 任务计数 */}
        {activeTaskCount > 0 && (
          <motion.div 
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex items-center gap-1.5 px-2.5 py-1.5 bg-[#232330] rounded-lg text-amber-400 text-sm border border-amber-500/30"
          >
            <Activity className="w-3.5 h-3.5 animate-pulse" />
            <span className="font-medium">{activeTaskCount}</span>
          </motion.div>
        )}
        
        {/* 等级进度 */}
        <div className="hidden lg:block">
          <LevelProgressBar />
        </div>
        
        {/* 用户信息 */}
        {user && (
          <div className="flex items-center gap-2 px-2.5 py-1.5 bg-[#232330] rounded-lg border border-white/10">
            <User className="w-4 h-4 text-sb-cyan" />
            <span className="text-sm text-white hidden sm:inline">{user.username}</span>
          </div>
        )}
        
        {/* 设置按钮 */}
        <button
          onClick={() => {
            if (onNavigate) {
              onNavigate('settings')
            }
          }}
          className="p-2 bg-[#232330] rounded-lg hover:bg-[#2a2a3a] transition-all duration-200 border border-white/10"
          title="设置"
        >
          <Settings className="w-4 h-4 text-white/70 hover:text-white transition-colors" />
        </button>
        
        {/* 退出登录按钮 */}
        {onLogout && (
          <button
            onClick={onLogout}
            className="p-2 bg-[#232330] rounded-lg hover:bg-red-500/15 hover:text-red-400 transition-all duration-200 border border-white/10 group"
            title="退出登录"
          >
            <LogOut className="w-4 h-4 text-white/70 group-hover:text-red-400 transition-colors" />
          </button>
        )}
      </div>

      {/* 错误提示 - 居中显示在TopBar下方 */}
      {showError && error && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          className="fixed top-20 left-1/2 -translate-x-1/2 z-[100]"
        >
          <div className="flex items-center gap-3 px-5 py-3 bg-[#1e1e2a] border border-red-500/40 rounded-xl shadow-2xl">
            <div className="w-8 h-8 rounded-full bg-red-500/20 flex items-center justify-center flex-shrink-0">
              <AlertCircle className="w-4 h-4 text-red-400" />
            </div>
            <div className="flex flex-col">
              <span className="text-sm font-medium text-red-300">模式切换失败</span>
              <span className="text-xs text-red-400/80">{error}</span>
            </div>
            <button
              onClick={() => setShowError(false)}
              className="ml-2 p-1.5 hover:bg-red-500/20 rounded-lg transition-colors"
            >
              <X className="w-4 h-4 text-red-400" />
            </button>
          </div>
        </motion.div>
      )}
    </div>
  )
}
