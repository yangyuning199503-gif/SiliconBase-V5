import { motion } from 'framer-motion'
import { Message } from '../types'

interface PulseTimelineProps {
  messages: Message[]
}

export default function PulseTimeline({ messages }: PulseTimelineProps) {
  // 只取最近10条消息生成脉冲
  const recentMessages = messages.slice(-10)

  const getPulseColor = (role: string) => {
    switch (role) {
      case 'user':
        return '#00d4ff'
      case 'assistant':
        return '#aa66ff'
      case 'tool':
        return '#ffaa00'
      default:
        return '#ffffff'
    }
  }

  const getPulseIcon = (role: string) => {
    switch (role) {
      case 'user':
        return 'U'
      case 'assistant':
        return 'A'
      case 'tool':
        return 'T'
      default:
        return '•'
    }
  }

  return (
    <div className="h-12 shrink-0 border-b border-white/5 flex items-center px-4 gap-1 overflow-x-auto">
      <span className="text-xs text-white/30 shrink-0 mr-2">脉冲流:</span>
      
      {recentMessages.length === 0 ? (
        <span className="text-xs text-white/20">等待交互...</span>
      ) : (
        recentMessages.map((msg, index) => (
          <motion.div
            key={index}
            className="flex items-center shrink-0"
            initial={{ opacity: 0, scale: 0 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: index * 0.05 }}
          >
            <div
              className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold cursor-pointer hover:scale-110 transition-transform"
              style={{
                backgroundColor: `${getPulseColor(msg.role)}20`,
                border: `2px solid ${getPulseColor(msg.role)}`,
                color: getPulseColor(msg.role),
              }}
              title={`${msg.role}: ${msg.content.slice(0, 30)}...`}
            >
              {getPulseIcon(msg.role)}
            </div>
            {index < recentMessages.length - 1 && (
              <div className="w-4 h-0.5 bg-white/10 mx-1" />
            )}
          </motion.div>
        ))
      )}

      {/* 脉冲指示器 */}
      <motion.div
        className="ml-auto flex items-center gap-2 text-xs"
        animate={{ opacity: [0.5, 1, 0.5] }}
        transition={{ duration: 2, repeat: Infinity }}
      >
        <div className="w-2 h-2 rounded-full bg-green-400" />
        <span className="text-white/30">系统正常</span>
      </motion.div>
    </div>
  )
}
