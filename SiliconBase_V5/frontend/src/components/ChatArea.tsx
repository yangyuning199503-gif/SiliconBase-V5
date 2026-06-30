/**
 * ChatArea - 聊天区域容器组件
 *
 * 将 MessageList 和 InputArea 封装为一个整体聊天面板，
 * 负责两者之间的布局关系，不处理具体业务逻辑。
 */

import MessageList from './MessageList'
import InputArea from './InputArea'
import type { Agent, TaskStatus, UploadedFile } from '../types'

interface ChatAreaProps {
  currentAgent: Agent
  onSuggestionClick?: (suggestion: string) => void
  onMemoryClick?: (memoryId?: string) => void
  isProcessing?: boolean
  onSend: (
    content: string,
    type?: 'text' | 'voice' | 'chat' | 'auto',
    files?: UploadedFile[],
  ) => void
  onSendControl?: (action: string) => void
  isRecording: boolean
  onRecordingChange: (recording: boolean) => void
  agentStatus: string
  activeTasks?: TaskStatus[]
  sessionId?: string
}

export default function ChatArea({
  currentAgent,
  onSuggestionClick,
  onMemoryClick,
  isProcessing = false,
  onSend,
  onSendControl,
  isRecording,
  onRecordingChange,
  agentStatus,
  activeTasks = [],
  sessionId = 'default',
}: ChatAreaProps) {
  return (
    <div className="h-full min-h-0 overflow-hidden relative grid grid-rows-[1fr_auto]">
      {/* 消息列表区：明确限定高度，内部独立滚动 */}
      <div className="relative h-full min-h-0 overflow-hidden flex flex-col">
        <MessageList
          currentAgent={currentAgent}
          onSuggestionClick={onSuggestionClick}
          onMemoryClick={onMemoryClick}
          isProcessing={isProcessing}
        />
      </div>

      {/* 输入框：固定在聊天父组件底部 */}
      <InputArea
        onSend={onSend}
        onSendControl={onSendControl}
        isRecording={isRecording}
        onRecordingChange={onRecordingChange}
        agentStatus={agentStatus}
        activeTasks={activeTasks}
        sessionId={sessionId}
      />
    </div>
  )
}
