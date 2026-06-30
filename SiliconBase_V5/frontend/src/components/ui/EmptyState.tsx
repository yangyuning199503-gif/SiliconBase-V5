import { Inbox } from 'lucide-react'

interface EmptyStateProps {
  title?: string
  description?: string
  className?: string
}

export function EmptyState({
  title = '暂无数据',
  description = '当前没有可显示的内容',
  className = '',
}: EmptyStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 text-slate-400 py-12 ${className}`}>
      <div className="w-12 h-12 rounded-xl bg-white/5 flex items-center justify-center">
        <Inbox className="w-6 h-6 text-slate-500" />
      </div>
      <div className="text-center">
        <p className="text-sm font-medium text-slate-300">{title}</p>
        <p className="text-xs text-slate-500 mt-1">{description}</p>
      </div>
    </div>
  )
}

export default EmptyState
