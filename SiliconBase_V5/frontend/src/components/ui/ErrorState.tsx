import { AlertTriangle, RefreshCw } from 'lucide-react'

interface ErrorStateProps {
  title?: string
  error?: string
  onRetry?: () => void
  className?: string
}

export function ErrorState({
  title = '加载失败',
  error = '请求出错，请稍后重试',
  onRetry,
  className = '',
}: ErrorStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 text-slate-400 py-12 ${className}`}>
      <div className="w-12 h-12 rounded-xl bg-red-500/10 flex items-center justify-center">
        <AlertTriangle className="w-6 h-6 text-red-400" />
      </div>
      <div className="text-center">
        <p className="text-sm font-medium text-slate-300">{title}</p>
        <p className="text-xs text-slate-500 mt-1">{error}</p>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 text-xs text-slate-300 hover:bg-white/10 hover:text-white transition-colors border border-white/10"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          重试
        </button>
      )}
    </div>
  )
}

export default ErrorState
