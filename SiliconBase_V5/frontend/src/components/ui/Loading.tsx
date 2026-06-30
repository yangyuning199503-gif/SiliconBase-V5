import { Loader2 } from 'lucide-react'

interface LoadingProps {
  text?: string
  className?: string
}

export function Loading({ text = '加载中...', className = '' }: LoadingProps) {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 text-slate-400 ${className}`}>
      <Loader2 className="w-6 h-6 animate-spin text-cyan-400" />
      <span className="text-sm">{text}</span>
    </div>
  )
}

export default Loading
