/**
 * 简化版聊天组件 - 只显示消息
 */
import { useRef, useEffect } from 'react'

interface Message {
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string
  timestamp?: number
}

interface SimpleChatProps {
  messages: Message[]
}

export default function SimpleChat({ messages }: SimpleChatProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
      {messages.length === 0 ? (
        <div className="text-center text-white/50 mt-20">
          <p className="text-lg">发送消息开始对话</p>
        </div>
      ) : (
        messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] p-3 rounded-lg ${
                msg.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : msg.role === 'tool'
                  ? 'bg-yellow-600/50 text-white'
                  : 'bg-gray-700 text-white'
              }`}
            >
              {/* 角色标签 */}
              <div className="text-xs opacity-70 mb-1">
                {msg.role === 'user' ? '你' : msg.role === 'assistant' ? 'AI' : msg.role}
              </div>
              {/* 内容 */}
              <div className="whitespace-pre-wrap">{msg.content}</div>
            </div>
          </div>
        ))
      )}
    </div>
  )
}
