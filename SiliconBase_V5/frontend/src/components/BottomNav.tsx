import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Home,
  ListTodo,
  Wrench,
  Brain,
  Activity,
  FileText,
  Bot,
  Heart,
  Settings,
  Cloud,
  ChevronUp,
  X,
  Sparkles,
  LayoutGrid,
  HardDrive,
  TrendingUp,
  DollarSign,
  Puzzle,
  GitBranch,
  MessageCircle,
  Users,
  Cpu,
  Network,
  Layers
} from 'lucide-react'

export type PageType = 'home' | 'tasks' | 'tools' | 'memory' | 'dashboard' | 'promptconfig' | 'aiconfig' | 'threeviews' | 'settings' | 'memoryviz' | 'toolmarket' | 'siliconlife' | 'memorydemo' | 'week5panels' | 'globalview' | 'trading' | 'lifestatus' | 'experience' | 'costs' | 'features' | 'workflows' | 'reflections' | 'sessions' | 'advancedmodels' | 'memorygraph'

interface PageItem {
  id: PageType
  name: string
  icon: React.ElementType
  description?: string
}

// 主导航项（显示在底部栏）
const MAIN_NAV_ITEMS: PageItem[] = [
  { id: 'home', name: '首页', icon: Home, description: '主交互界面' },
  { id: 'tasks', name: '任务', icon: ListTodo, description: '任务管理' },
  { id: 'tools', name: '工具', icon: Wrench, description: '工具列表' },
  { id: 'memory', name: '记忆', icon: Brain, description: '记忆管理' },
]

// 更多菜单项
const MORE_NAV_ITEMS: PageItem[] = [
  { id: 'trading', name: '交易', icon: TrendingUp, description: 'BTC量化交易监控' },
  { id: 'dashboard', name: '监控', icon: Activity, description: '系统状态监控' },
  { id: 'lifestatus', name: '生命体征', icon: Heart, description: '零号机实时生命状态面板' },
  { id: 'siliconlife', name: '成长监控', icon: Sparkles, description: '硅基生命成长监控面板' },
  { id: 'memoryviz', name: '记忆流', icon: Activity, description: '记忆流动可视化' },
  { id: 'memorygraph', name: '记忆图谱', icon: Network, description: '记忆关联关系可视化' },
  { id: 'memorydemo', name: '记忆组件', icon: Layers, description: '记忆组件演示' },
  { id: 'toolmarket', name: '云市场', icon: Cloud, description: '云端工具市场' },
  { id: 'promptconfig', name: '提示词', icon: FileText, description: '提示词模块配置' },
  { id: 'aiconfig', name: 'AI配置', icon: Bot, description: 'AI参数配置' },
  { id: 'threeviews', name: '三观', icon: Heart, description: '三观提示词配置' },
  { id: 'week5panels', name: 'Week 5', icon: LayoutGrid, description: '阶段锚点/反思/语气' },
  { id: 'globalview', name: '磁盘扫描', icon: HardDrive, description: '磁盘文件扫描可视化' },
  { id: 'experience', name: '体验量化', icon: Sparkles, description: '体验量化与A/B测试' },
  { id: 'costs', name: '成本分析', icon: DollarSign, description: '调用成本与资源统计' },
  { id: 'features', name: '特性开关', icon: Puzzle, description: '系统特性与能力配置' },
  { id: 'advancedmodels', name: '高级模型', icon: Cpu, description: '大模型与高级模型配置' },
  { id: 'workflows', name: '工作流', icon: GitBranch, description: '工作流与自动化编排' },
  { id: 'reflections', name: '反思记录', icon: MessageCircle, description: 'AI 反思与自我评估' },
  { id: 'sessions', name: '会话管理', icon: Users, description: '历史会话与消息管理' },
  { id: 'settings', name: '设置', icon: Settings, description: '系统设置' },
]

interface BottomNavProps {
  currentPage: PageType
  onPageChange: (page: PageType) => void
}

export default function BottomNav({ currentPage, onPageChange }: BottomNavProps) {
  const [showMore, setShowMore] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // 点击外部关闭菜单
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setShowMore(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleMainNavClick = (pageId: PageType) => {
    onPageChange(pageId)
    setShowMore(false)
  }

  const handleMoreItemClick = (pageId: PageType) => {
    onPageChange(pageId)
    setShowMore(false)
  }

  return (
    <div className="relative">
      {/* 底部导航栏 */}
      <div className="h-16 bg-[#1e1e2a] border-t border-white/15 flex items-center justify-between px-4 shrink-0">
        {/* 左侧：主导航 */}
        <div className="flex items-center gap-1">
          {MAIN_NAV_ITEMS.map((item) => {
            const Icon = item.icon
            const isActive = currentPage === item.id
            return (
              <button
                key={item.id}
                onClick={() => handleMainNavClick(item.id)}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-xl transition-all duration-200 ${
                  isActive
                    ? 'bg-gradient-to-r from-cyan-500/20 to-blue-500/20 text-cyan-400 border border-cyan-500/30'
                    : 'text-white/50 hover:text-white/80 hover:bg-white/5'
                }`}
                title={item.description}
              >
                <Icon className="w-5 h-5" />
                <span className="text-sm font-medium hidden sm:inline">{item.name}</span>
              </button>
            )
          })}
        </div>

        {/* 右侧：更多菜单按钮 */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setShowMore(!showMore)}
            className={`flex items-center gap-1.5 px-4 py-2.5 rounded-xl transition-all duration-200 ${
              showMore || MORE_NAV_ITEMS.some(item => item.id === currentPage)
                ? 'bg-[#2a2a3a] text-white border border-cyan-500/30'
                : 'bg-[#2a2a3a] text-white/80 border border-white/10 hover:bg-[#353548] hover:text-white'
            }`}
          >
            <span className="text-sm font-medium">更多</span>
            <motion.div
              animate={{ rotate: showMore ? 180 : 0 }}
              transition={{ duration: 0.2 }}
            >
              <ChevronUp className="w-4 h-4" />
            </motion.div>
          </button>

          {/* 更多菜单弹出层 */}
          <AnimatePresence>
            {showMore && (
              <motion.div
                initial={{ opacity: 0, y: 10, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 10, scale: 0.95 }}
                transition={{ duration: 0.15 }}
                className="absolute bottom-full right-0 mb-2 w-64 bg-[#232330] rounded-2xl border border-white/15 shadow-2xl overflow-hidden z-50"
              >
                {/* 菜单头部 */}
                <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-[#2a2a3a]">
                  <span className="text-sm font-medium text-white/90">更多功能</span>
                  <button
                    onClick={() => setShowMore(false)}
                    className="p-1 rounded-lg hover:bg-white/10 text-white/60 hover:text-white transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                {/* 菜单项网格 */}
                <div className="p-2 grid grid-cols-2 gap-1 bg-[#232330]">
                  {MORE_NAV_ITEMS.map((item) => {
                    const Icon = item.icon
                    const isActive = currentPage === item.id
                    return (
                      <button
                        key={item.id}
                        onClick={() => handleMoreItemClick(item.id)}
                        className={`flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-200 text-left ${
                          isActive
                            ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                            : 'text-white/75 hover:text-white hover:bg-white/10'
                        }`}
                        title={item.description}
                      >
                        <Icon className="w-4 h-4 shrink-0" />
                        <span className="text-xs font-medium">{item.name}</span>
                      </button>
                    )
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}
