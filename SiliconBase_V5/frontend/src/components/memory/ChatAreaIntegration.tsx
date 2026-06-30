/**
 * ChatArea 集成示例
 * 展示如何在现有 ChatArea 组件中集成记忆展示功能
 * 
 * 使用说明：
 * 1. 复制以下代码到 ChatArea.tsx
 * 2. 或者使用提供的 Hook 方式集成
 */

import { useState, useCallback } from 'react';
import { MemoryPanel, MemoryAwareness } from './index';
import { Message } from '../../types';

// 扩展的消息类型
export interface MessageWithMemory extends Message {
  memoryCount?: number;
  memoryIds?: string[];
  relevanceScore?: number;
  memoryTypes?: string[];
}

/**
 * Hook: 使用记忆功能
 */
export function useMemoryIntegration(sessionId: string) {
  const [isMemoryPanelOpen, setIsMemoryPanelOpen] = useState(false);
  const [selectedMemoryIds, setSelectedMemoryIds] = useState<string[]>([]);

  const openMemoryPanel = useCallback(() => {
    setIsMemoryPanelOpen(true);
  }, []);

  const closeMemoryPanel = useCallback(() => {
    setIsMemoryPanelOpen(false);
  }, []);

  const toggleMemoryPanel = useCallback(() => {
    setIsMemoryPanelOpen(prev => !prev);
  }, []);

  // 渲染记忆感知组件
  const renderMemoryAwareness = useCallback((
    message: MessageWithMemory
  ) => {
    if (message.role !== 'assistant' || !message.memoryCount) {
      return null;
    }

    return (
      <MemoryAwareness
        memoryCount={message.memoryCount}
        memoryIds={message.memoryIds}
        relevanceScore={message.relevanceScore}
        memoryTypes={message.memoryTypes}
        onClick={openMemoryPanel}
      />
    );
  }, [openMemoryPanel]);

  // 渲染记忆面板
  const renderMemoryPanel = useCallback(() => {
    return (
      <MemoryPanel
        sessionId={sessionId}
        isOpen={isMemoryPanelOpen}
        onClose={closeMemoryPanel}
      />
    );
  }, [sessionId, isMemoryPanelOpen, closeMemoryPanel]);

  return {
    isMemoryPanelOpen,
    openMemoryPanel,
    closeMemoryPanel,
    toggleMemoryPanel,
    renderMemoryAwareness,
    renderMemoryPanel,
    selectedMemoryIds,
    setSelectedMemoryIds
  };
}

/**
 * 完整的 ChatArea 修改示例
 * 
 * 将以下代码集成到现有的 ChatArea.tsx 中：
 */
export const ChatAreaModificationGuide = `
// ============================================
// ChatArea.tsx 修改指南
// ============================================

// 1. 导入记忆组件
import { MemoryPanel, MemoryAwareness } from './memory';
import { useMemoryIntegration } from './memory/ChatAreaIntegration';

// 2. 扩展消息类型（如果还没有）
interface MessageWithMemory extends Message {
  memoryCount?: number;
  memoryIds?: string[];
  relevanceScore?: number;
  memoryTypes?: string[];
}

// 3. 在 ChatArea 组件中添加
export default function ChatArea({ 
  messages, 
  currentAgent, 
  sessionId,  // 需要传入 sessionId
  ...props 
}) {
  // 使用记忆集成 Hook
  const { 
    isMemoryPanelOpen, 
    openMemoryPanel, 
    closeMemoryPanel,
    renderMemoryPanel 
  } = useMemoryIntegration(sessionId);

  return (
    <div className="flex-1 flex flex-col relative">
      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message, index) => (
          <div key={index}>
            {/* 原有消息气泡 */}
            <MessageBubble 
              message={message} 
              agent={currentAgent} 
            />
            
            {/* 新增：AI消息的记忆感知提示 */}
            {message.role === 'assistant' && message.memoryCount && (
              <div className="mt-2 ml-12">
                <MemoryAwareness
                  memoryCount={message.memoryCount}
                  memoryIds={message.memoryIds}
                  relevanceScore={message.relevanceScore}
                  memoryTypes={message.memoryTypes}
                  onClick={openMemoryPanel}
                />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* 新增：记忆面板 */}
      {renderMemoryPanel()}

      {/* 新增：快速打开按钮（当面板关闭时） */}
      {!isMemoryPanelOpen && (
        <button
          onClick={openMemoryPanel}
          className="absolute right-4 top-4 z-30
                     flex items-center gap-2 px-3 py-2
                     bg-sb-bg-secondary/80 backdrop-blur-sm
                     border border-white/10 rounded-lg
                     text-xs text-slate-300 hover:text-white
                     hover:border-purple-500/30
                     transition-all shadow-lg"
        >
          <Brain className="w-4 h-4 text-purple-400" />
          <span>记忆</span>
        </button>
      )}
    </div>
  );
}
`;

/**
 * 后端消息格式示例
 * 后端需要在AI回复时返回记忆信息
 */
export const BackendMessageFormat = `
{
  "role": "assistant",
  "content": "AI回复内容...",
  "timestamp": 1704067200,
  
  // 新增：记忆相关信息
  "memory_count": 3,
  "memory_ids": ["mem-1", "mem-2", "mem-3"],
  "relevance_score": 0.85,
  "memory_types": ["context", "experience", "preference"]
}
`;

/**
 * WebSocket 消息处理示例
 */
export const WebSocketIntegration = `
// 在 WebSocket 消息处理中添加

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  switch (data.type) {
    case 'reply':
      // 处理AI回复，包含记忆信息
      const message: MessageWithMemory = {
        role: 'assistant',
        content: data.content,
        timestamp: Date.now(),
        // 记忆信息
        memoryCount: data.memory_count,
        memoryIds: data.memory_ids,
        relevanceScore: data.relevance_score,
        memoryTypes: data.memory_types
      };
      
      addMessage(message);
      break;
      
    // ... 其他消息类型
  }
};
`;

/**
 * 快速集成组件
 * 如果不想修改现有 ChatArea，可以包装使用
 */
interface MemoryChatWrapperProps {
  sessionId: string;
  messages?: MessageWithMemory[];
  children: React.ReactNode;
}

export function MemoryChatWrapper({ 
  sessionId, 
  children 
}: MemoryChatWrapperProps) {
  const [isPanelOpen, setIsPanelOpen] = useState(false);

  return (
    <div className="relative h-full flex">
      {/* 主内容 */}
      <div className="flex-1 min-w-0">
        {children}
      </div>

      {/* 记忆面板 */}
      <MemoryPanel
        sessionId={sessionId}
        isOpen={isPanelOpen}
        onClose={() => setIsPanelOpen(false)}
      />

      {/* 快速访问按钮 */}
      {!isPanelOpen && (
        <button
          onClick={() => setIsPanelOpen(true)}
          className="absolute right-4 top-4 z-30
                     flex items-center gap-2 px-3 py-2
                     bg-sb-bg-secondary/80 backdrop-blur-sm
                     border border-white/10 rounded-lg
                     text-xs text-slate-300 hover:text-white
                     hover:border-purple-500/30 hover:bg-purple-500/10
                     transition-all shadow-lg"
        >
          <Brain className="w-4 h-4 text-purple-400" />
          <span>记忆</span>
        </button>
      )}
    </div>
  );
}

// 导入图标
import { Brain } from 'lucide-react';
