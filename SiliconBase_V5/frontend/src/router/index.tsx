import { createBrowserRouter, Navigate, Outlet } from 'react-router-dom'
import { Suspense, lazy, useEffect, useState } from 'react'
import RootLayout from '../layouts/RootLayout'
import { getAuthToken } from '../utils/auth'
import { fetchAPI, APIError, handleUnauthorized } from '../utils/api'

// 同步导入核心页面（首屏需要）
import { LoginPage } from '../pages'

// 懒加载其他页面，减少首屏包体积
const pages = {
  DashboardPage: lazy(() => import('../pages').then(m => ({ default: m.DashboardPage }))),
  ToolsPage: lazy(() => import('../pages').then(m => ({ default: m.ToolsPage }))),
  MemoryPage: lazy(() => import('../pages').then(m => ({ default: m.MemoryPage }))),
  MemoryVisualizationPage: lazy(() => import('../pages').then(m => ({ default: m.MemoryVisualizationPage }))),
  MemoryComponentsDemo: lazy(() => import('../pages').then(m => ({ default: m.MemoryComponentsDemo }))),
  AIConfigPage: lazy(() => import('../pages').then(m => ({ default: m.AIConfigPage }))),
  TasksPage: lazy(() => import('../pages').then(m => ({ default: m.TasksPage }))),
  PromptConfigPage: lazy(() => import('../pages').then(m => ({ default: m.PromptConfigPage }))),
  ThreeViewsConfig: lazy(() => import('../pages').then(m => ({ default: m.ThreeViewsConfig }))),
  ToolMarketPage: lazy(() => import('../pages').then(m => ({ default: m.ToolMarketPage }))),
  SiliconLifeMonitorPage: lazy(() => import('../pages').then(m => ({ default: m.SiliconLifeMonitorPage }))),
  Week5PanelsPage: lazy(() => import('../pages').then(m => ({ default: m.Week5PanelsPage }))),
  ChangePasswordPage: lazy(() => import('../pages').then(m => ({ default: m.ChangePasswordPage }))),
  GlobalViewPage: lazy(() => import('../pages').then(m => ({ default: m.GlobalViewPage }))),
  TradingDashboardPage: lazy(() => import('../pages').then(m => ({ default: m.TradingDashboardPage }))),
  SettingsPage: lazy(() => import('../pages').then(m => ({ default: m.SettingsPage }))),
  AdvancedModelsPage: lazy(() => import('../pages').then(m => ({ default: m.AdvancedModelsPage }))),
  ExperienceQuantificationPage: lazy(() => import('../pages/ExperienceQuantificationPage/ExperienceQuantificationPage')),
  CostsPage: lazy(() => import('../pages').then(m => ({ default: m.CostsPage }))),
  FeaturesPage: lazy(() => import('../pages').then(m => ({ default: m.FeaturesPage }))),
  MemoryGraphPage: lazy(() => import('../pages').then(m => ({ default: m.MemoryGraphPage }))),
  WorkflowsPage: lazy(() => import('../pages').then(m => ({ default: m.WorkflowsPage }))),
  ReflectionsPage: lazy(() => import('../pages').then(m => ({ default: m.ReflectionsPage }))),
  SessionsPage: lazy(() => import('../pages').then(m => ({ default: m.SessionsPage }))),
  LifeStatusPage: lazy(() => import('../pages').then(m => ({ default: m.LifeStatusPage }))),
}

// 首页是聊天主界面，保持同步导入避免路由闪烁
import AppHome from '../AppHome'

function AuthGuard() {
  const token = getAuthToken()
  const [isValid, setIsValid] = useState<boolean | null>(null)

  useEffect(() => {
    if (!token) {
      setIsValid(false)
      return
    }

    let cancelled = false
    setIsValid(null)

    fetchAPI<{ user_id?: string }>('/api/auth/me', { silent: true })
      .then(() => {
        if (!cancelled) setIsValid(true)
      })
      .catch((error) => {
        if (cancelled) return
        if (error instanceof APIError && error.status === 401) {
          handleUnauthorized()
        }
        setIsValid(false)
      })

    return () => { cancelled = true }
  }, [token])

  if (!token || isValid === false) {
    return <Navigate to="/login" replace />
  }

  if (isValid === null) {
    return (
      <div className="h-screen flex items-center justify-center bg-slate-950 text-cyan-400">
        <div className="animate-pulse">校验登录状态...</div>
      </div>
    )
  }

  return <Outlet />
}

function PublicGuard() {
  const token = getAuthToken()
  if (token) {
    return <Navigate to="/" replace />
  }
  return <Outlet />
}

function PageWrapper({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={
      <div className="h-screen flex items-center justify-center bg-slate-950 text-cyan-400">
        <div className="animate-pulse">加载中...</div>
      </div>
    }>
      {children}
    </Suspense>
  )
}

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <PublicGuard />,
    children: [
      { index: true, element: <LoginPage /> }
    ]
  },
  {
    element: <AuthGuard />,
    children: [
      {
        path: '/',
        element: <RootLayout />,
        children: [
          { index: true, element: <AppHome /> },
          { path: 'tasks', element: <PageWrapper><pages.TasksPage /></PageWrapper> },
          { path: 'tools', element: <PageWrapper><pages.ToolsPage /></PageWrapper> },
          { path: 'memory', element: <PageWrapper><pages.MemoryPage /></PageWrapper> },
          { path: 'memory/viz', element: <PageWrapper><pages.MemoryVisualizationPage /></PageWrapper> },
          { path: 'memory/graph', element: <PageWrapper><pages.MemoryGraphPage /></PageWrapper> },
          { path: 'memory/demo', element: <PageWrapper><pages.MemoryComponentsDemo /></PageWrapper> },
          { path: 'dashboard', element: <PageWrapper><pages.DashboardPage /></PageWrapper> },
          { path: 'aiconfig', element: <PageWrapper><pages.AIConfigPage /></PageWrapper> },
          { path: 'promptconfig', element: <PageWrapper><pages.PromptConfigPage /></PageWrapper> },
          { path: 'threeviews', element: <PageWrapper><pages.ThreeViewsConfig /></PageWrapper> },
          { path: 'toolmarket', element: <PageWrapper><pages.ToolMarketPage /></PageWrapper> },
          { path: 'siliconlife', element: <PageWrapper><pages.SiliconLifeMonitorPage /></PageWrapper> },
          { path: 'lifestatus', element: <PageWrapper><pages.LifeStatusPage /></PageWrapper> },
          { path: 'globalview', element: <PageWrapper><pages.GlobalViewPage /></PageWrapper> },
          { path: 'trading', element: <PageWrapper><pages.TradingDashboardPage /></PageWrapper> },
          { path: 'week5panels', element: <PageWrapper><pages.Week5PanelsPage /></PageWrapper> },
          { path: 'settings', element: <PageWrapper><pages.SettingsPage /></PageWrapper> },
          { path: 'change-password', element: <PageWrapper><pages.ChangePasswordPage /></PageWrapper> },
          { path: 'advanced-models', element: <PageWrapper><pages.AdvancedModelsPage /></PageWrapper> },
          { path: 'experience', element: <PageWrapper><pages.ExperienceQuantificationPage /></PageWrapper> },
          { path: 'costs', element: <PageWrapper><pages.CostsPage /></PageWrapper> },
          { path: 'features', element: <PageWrapper><pages.FeaturesPage /></PageWrapper> },
          { path: 'workflows', element: <PageWrapper><pages.WorkflowsPage /></PageWrapper> },
          { path: 'reflections', element: <PageWrapper><pages.ReflectionsPage /></PageWrapper> },
          { path: 'sessions', element: <PageWrapper><pages.SessionsPage /></PageWrapper> },
          {
            path: '*',
            element: (
              <div className="h-full flex flex-col items-center justify-center p-8 text-center">
                <div className="text-6xl font-bold text-sb-cyan mb-4">404</div>
                <h1 className="text-2xl font-semibold text-white mb-2">页面不存在</h1>
                <p className="text-sb-text-secondary mb-6">抱歉，您访问的页面不存在或已被移除。</p>
                <a
                  href="/"
                  className="px-6 py-2 rounded-xl bg-sb-cyan text-sb-bg-primary font-medium hover:brightness-110 transition-all"
                >
                  返回首页
                </a>
              </div>
            )
          }
        ]
      }
    ]
  }
])

export default router
