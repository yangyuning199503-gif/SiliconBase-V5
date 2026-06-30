/**
 * MemoryChatIntegration - 记忆组件与聊天面板集成示例
 * 展示如何在 ChatArea 中集成 MemoryAwareness 和 MemoryPanel
 */
import { useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Brain, BookOpen } from 'lucide-react';
import MemoryPanel from './MemoryPanel';
import MemoryAwareness from './MemoryAwareness';
import { Message } from '../../types';

// 扩展消息类型，包含记忆信息
interface MessageWithMemory extends Message {
  memoryCount?: number;
  memoryIds?: string[];
  relevanceScore?: number;
  memoryTypes?: string[];
}

interface MemoryChatIntegrationProps {
  sessionId: string;
  messages: MessageWithMemory[];
  children: React.ReactNode; // 原有的聊天内容
}

/**
 * 记忆感知包装器 - 为AI消息添加记忆提示
 */
export function MemoryAwarenessWrapper({
  message,
  onOpenMemoryPanel
}: {
  message: MessageWithMemory;
  onOpenMemoryPanel: () => void;
}) {
  // 只在AI消息且有关联记忆时显示
  if (message.role !== 'assistant' || !message.memoryCount) {
    return null;
  }

  return (
    <div className="mt-2 ml-12">
      <MemoryAwareness
        memoryCount={message.memoryCount}
        memoryIds={message.memoryIds}
        relevanceScore={message.relevanceScore}
        memoryTypes={message.memoryTypes}
        onClick={onOpenMemoryPanel}
      />
    </div>
  );
}

/**
 * 主集成组件
 */
export default function MemoryChatIntegration({
  sessionId,
  children
}: MemoryChatIntegrationProps) {
  const [isMemoryPanelOpen, setIsMemoryPanelOpen] = useState(false);

  const handleOpenMemoryPanel = useCallback(() => {
    setIsMemoryPanelOpen(true);
  }, []);

  const handleCloseMemoryPanel = useCallback(() => {
    setIsMemoryPanelOpen(false);
  }, []);

  return (
    <div className="relative h-full flex">
      {/* 主聊天区域 */}
      <div className="flex-1 flex flex-col min-w-0">
        {children}
      </div>

      {/* 记忆面板 */}
      <AnimatePresence>
        {isMemoryPanelOpen && (
          <MemoryPanel
            sessionId={sessionId}
            isOpen={isMemoryPanelOpen}
            onClose={handleCloseMemoryPanel}
          />
        )}
      </AnimatePresence>

      {/* 快速访问按钮（当面板关闭时显示） */}
      {!isMemoryPanelOpen && (
        <motion.button
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          whileHover={{ scale: 1.05 }}
          onClick={handleOpenMemoryPanel}
          className="absolute right-4 top-4 z-30
                     flex items-center gap-2 px-3 py-2
                     bg-sb-bg-secondary/80 backdrop-blur-sm
                     border border-white/10 rounded-lg
                     text-xs text-slate-300 hover:text-white
                     hover:border-purple-500/30 hover:bg-purple-500/10
                     transition-all shadow-lg"
          title="查看会话记忆"
        >
          <Brain className="w-4 h-4 text-purple-400" />
          <span>记忆</span>
        </motion.button>
      )}
    </div>
  );
}

/**
 * 使用示例 - 如何修改 ChatArea 组件
 * 
 * 在 ChatArea.tsx 中:
 * 
 * 1. 导入记忆组件:
 *    import { MemoryAwareness } from '../memory';
 * 
 * 2. 在 AI 消息渲染后添加记忆感知:
 *    {message.role === 'assistant' && message.memoryCount && (
 *      <div className="mt-2">
 *        <MemoryAwareness
 *          memoryCount={message.memoryCount}
 *          onClick={() => setShowMemoryPanel(true)}
 *        />
 *      </div>
 *    )}
 * 
 * 3. 添加记忆面板状态:
 *    const [showMemoryPanel, setShowMemoryPanel] = useState(false);
 * 
 * 4. 在组件底部渲染记忆面板:
 *    <MemoryPanel
 *      sessionId={currentSessionId}
 *      isOpen={showMemoryPanel}
 *      onClose={() => setShowMemoryPanel(false)}
 *    />
 */

/**
 * ChatArea 修改示例代码片段
 */
export const ChatAreaIntegrationExample = `
// ChatArea.tsx 修改示例

import { useState } from 'react';
import { MemoryPanel, MemoryAwareness } from '../memory';

export default function ChatArea({ messages, currentAgent, ...props }) {
  // 新增：记忆面板状态
  const [showMemoryPanel, setShowMemoryPanel] = useState(false);
  const [currentSessionId] = useState('session-123'); // 从props或context获取

  return (
    <div className="flex-1 flex flex-col relative">
      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message, index) => (
          <div key={index}>
            {/* 原有消息渲染 */}
            <MessageBubble message={message} agent={currentAgent} />
            
            {/* 新增：AI消息的记忆感知提示 */}
            {message.role === 'assistant' && (
              <div className="mt-2 ml-12">
                <MemoryAwareness
                  memoryCount={message.memoryCount || 0}
                  memoryIds={message.memoryIds}
                  relevanceScore={message.relevanceScore}
                  onClick={() => setShowMemoryPanel(true)}
                />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* 新增：记忆面板 */}
      <MemoryPanel
        sessionId={currentSessionId}
        isOpen={showMemoryPanel}
        onClose={() => setShowMemoryPanel(false)}
      />

      {/* 新增：快速打开按钮（可选） */}
      {!showMemoryPanel && (
        <button
          onClick={() => setShowMemoryPanel(true)}
          className="absolute right-4 top-4 p-2 rounded-lg
                     bg-slate-800/80 text-slate-400
                     hover:text-white hover:bg-slate-700
                     transition-colors"
        >
          <Brain className="w-5 h-5" />
        </button>
      )}
    </div>
  );
}
`;

/**
 * 模拟数据生成（用于测试）
 */
export function generateMockMemories(count: number = 5): {
  memoryCount: number;
  memoryIds: string[];
  relevanceScore: number;
  memoryTypes: string[];
} {
  const types = ['context', 'reference', 'experience', 'preference'];
  const memoryIds = Array.from({ length: count }, (_, i) => `mem-${Date.now()}-${i}`);
  const memoryTypes = Array.from({ length: count }, () => 
    types[Math.floor(Math.random() * types.length)]
  );

  return {
    memoryCount: count,
    memoryIds,
    relevanceScore: 0.6 + Math.random() * 0.35,
    memoryTypes
  };
}

/**
 * 测试组件 - 展示记忆组件的使用
 */
export function MemoryComponentsDemo() {
  const [showPanel, setShowPanel] = useState(false);
  const mockData = generateMockMemories(3);

  return (
    <div className="p-8 space-y-8">
      <h2 className="text-xl font-bold text-white mb-4">记忆组件测试</h2>
      
      {/* MemoryAwareness 演示 */}
      <div className="space-y-4">
        <h3 className="text-sm font-medium text-slate-400">MemoryAwareness 组件</h3>
        
        <div className="p-4 bg-sb-bg-secondary rounded-lg space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 w-20">有记忆:</span>
            <MemoryAwareness
              {...mockData}
              onClick={() => setShowPanel(true)}
            />
          </div>
          
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 w-20">无记忆:</span>
            <MemoryAwareness
              memoryCount={0}
              onClick={() => setShowPanel(true)}
            />
          </div>
          
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 w-20">多条记忆:</span>
            <MemoryAwareness
              memoryCount={12}
              memoryIds={Array.from({ length: 12 }, (_, i) => `mem-${i}`)}
              relevanceScore={0.85}
              memoryTypes={['context', 'context', 'experience', 'reference']}
              onClick={() => setShowPanel(true)}
            />
          </div>
        </div>
      </div>

      {/* MemoryPanel 演示按钮 */}
      <div className="space-y-4">
        <h3 className="text-sm font-medium text-slate-400">MemoryPanel 组件</h3>
        <button
          onClick={() => setShowPanel(true)}
          className="flex items-center gap-2 px-4 py-2 bg-sb-cyan text-sb-bg-primary rounded-lg font-medium hover:bg-sb-cyan-hover transition-colors"
        >
          <BookOpen className="w-4 h-4" />
          打开记忆面板
        </button>
      </div>

      {/* 面板 */}
      <MemoryPanel
        sessionId="demo-session-123"
        isOpen={showPanel}
        onClose={() => setShowPanel(false)}
      />
    </div>
  );
}
