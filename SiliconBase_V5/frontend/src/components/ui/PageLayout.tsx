import { ReactNode } from 'react'

interface PageLayoutProps {
  title: string
  subtitle?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
}

export function PageLayout({
  title,
  subtitle,
  actions,
  children,
  className = '',
}: PageLayoutProps) {
  return (
    <div className={`h-full flex flex-col bg-slate-950 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 shrink-0">
        <div>
          <h1 className="text-lg font-semibold text-white">{title}</h1>
          {subtitle && (
            <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>
          )}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {children}
      </div>
    </div>
  )
}

export default PageLayout
