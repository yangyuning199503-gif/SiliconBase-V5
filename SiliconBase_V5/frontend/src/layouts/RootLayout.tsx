import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import TopBar from '../components/TopBar'
import BottomNav, { type PageType } from '../components/BottomNav'
import DiagnosticOverlay from '../components/DiagnosticOverlay'
import { NotificationProvider } from '../hooks/useNotifications'
import { getAuthUser, logout } from '../utils/auth'
import { useModeStore } from '../stores/modeStore'
import { ProposalBubble } from '../components/ProposalBubble'
import type { Agent, TaskStatus } from '../types'

const AGENTS: Agent[] = [
  { id: 'general', name: '通用助手', icon: '🤖', color: '#00d4ff', description: '日常对话和任务执行' },
]

export default function RootLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const [user] = useState(getAuthUser())
  const { fetchCurrentMode } = useModeStore()
  const [activeTasks] = useState<TaskStatus[]>([])

  useEffect(() => {
    fetchCurrentMode()
  }, [fetchCurrentMode])

  // 跨标签页认证同步：当其他标签页修改 localStorage token 时，当前标签页同步跳转
  useEffect(() => {
    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'silicon_token') {
        const newToken = e.newValue
        if (!newToken) {
          navigate('/login', { replace: true })
        } else if (e.oldValue !== newToken) {
          // token 在其它标签页发生变化，刷新当前页以使用新身份
          window.location.reload()
        }
      }
    }

    const handleAuthExpired = () => navigate('/login', { replace: true })
    const handleAuthLogout = () => navigate('/login', { replace: true })

    window.addEventListener('storage', handleStorage)
    window.addEventListener('auth:session_expired', handleAuthExpired)
    window.addEventListener('auth:logout', handleAuthLogout)

    return () => {
      window.removeEventListener('storage', handleStorage)
      window.removeEventListener('auth:session_expired', handleAuthExpired)
      window.removeEventListener('auth:logout', handleAuthLogout)
    }
  }, [navigate])

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  // URL 路径到 PageType 的映射
  const pathToPageType = (pathname: string): PageType => {
    const normalized = pathname.replace(/\/$/, '') || '/'
    switch (normalized) {
      case '/': return 'home'
      case '/tasks': return 'tasks'
      case '/tools': return 'tools'
      case '/memory': return 'memory'
      case '/dashboard': return 'dashboard'
      case '/promptconfig': return 'promptconfig'
      case '/aiconfig': return 'aiconfig'
      case '/threeviews': return 'threeviews'
      case '/settings':
      case '/change-password': return 'settings'
      case '/memory/viz': return 'memoryviz'
      case '/memory/graph': return 'memorygraph'
      case '/memory/demo': return 'memorydemo'
      case '/toolmarket': return 'toolmarket'
      case '/siliconlife': return 'siliconlife'
      case '/lifestatus': return 'lifestatus'
      case '/globalview': return 'globalview'
      case '/trading': return 'trading'
      case '/week5panels': return 'week5panels'
      case '/experience': return 'experience'
      case '/costs': return 'costs'
      case '/features': return 'features'
      case '/workflows': return 'workflows'
      case '/reflections': return 'reflections'
      case '/sessions': return 'sessions'
      case '/advanced-models': return 'advancedmodels'
      default: return 'home'
    }
  }

  // PageType 到 URL 路径的映射
  const pageTypeToPath = (page: PageType): string => {
    switch (page) {
      case 'home': return '/'
      case 'memoryviz': return '/memory/viz'
      case 'memorygraph': return '/memory/graph'
      case 'memorydemo': return '/memory/demo'
      case 'advancedmodels': return '/advanced-models'
      default: return `/${page}`
    }
  }

  const pageFromPath = pathToPageType(location.pathname)

  return (
    <NotificationProvider>
      <DiagnosticOverlay />
      <div className="h-screen flex flex-col bg-slate-950 overflow-hidden">
        <TopBar
          currentAgent={AGENTS[0]}
          activeTaskCount={activeTasks.length}
          activeTasks={activeTasks}
          user={user}
          onLogout={handleLogout}
          onNavigate={(page: string) => navigate(page === 'home' ? '/' : `/${page}`)}
          agentStatus="idle"
        />
        <main className="flex-1 min-h-0 overflow-hidden flex flex-col">
          <Outlet />
        </main>
        <ProposalBubble />
        <BottomNav
          currentPage={pageFromPath}
          onPageChange={(page) => navigate(pageTypeToPath(page))}
        />
      </div>
    </NotificationProvider>
  )
}
