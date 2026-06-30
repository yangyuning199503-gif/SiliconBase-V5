/**
 * PerceptionIndicator 组件使用示例
 * 
 * 展示了如何在应用中使用 PerceptionIndicator 组件和 usePerception Hook
 */

import React, { useState } from 'react';
import { PerceptionIndicator, PerceptionBadge } from './PerceptionIndicator';
import { usePerception, PerceptionData } from '../hooks/usePerception';

// ============================================
// 示例 1: 基础用法（自动监听WebSocket事件）
// ============================================
export const ExampleBasicUsage: React.FC = () => {
  // 只需使用组件，它会自动通过 usePerception Hook 监听 WebSocket 事件
  return (
    <div className="relative min-h-screen">
      {/* 其他页面内容 */}
      <main className="p-8">
        <h1 className="text-2xl font-bold mb-4">基础用法示例</h1>
        <p className="text-slate-400">
          当后端发送 perception_triggered 事件时，指示器会自动显示
        </p>
      </main>

      {/* 感知指示器 - 放置在应用顶层或布局组件中 */}
      <PerceptionIndicator />
    </div>
  );
};

// ============================================
// 示例 2: 在ChatPanel中集成
// ============================================
export const ExampleWithChatPanel: React.FC = () => {
  return (
    <div className="flex h-screen">
      {/* 侧边栏 */}
      <aside className="w-64 bg-slate-900 border-r border-white/10">
        {/* 侧边栏内容 */}
      </aside>

      {/* 主聊天区域 */}
      <main className="flex-1 relative">
        {/* 聊天消息列表 */}
        <div className="flex-1 overflow-y-auto p-4">
          {/* 消息... */}
        </div>

        {/* 输入区域 */}
        <div className="border-t border-white/10 p-4">
          {/* 输入框... */}
        </div>

        {/* 感知指示器 - 悬浮在聊天区域上方 */}
        <PerceptionIndicator position="top-right" />
      </main>
    </div>
  );
};

// ============================================
// 示例 3: 使用 Hook 手动控制
// ============================================
export const ExampleWithHook: React.FC = () => {
  const { 
    isActive, 
    perceptionData, 
    triggerReason, 
    trigger, 
    close 
  } = usePerception();

  // 手动触发感知（调试用）
  const handleManualTrigger = () => {
    const mockData: PerceptionData = {
      type: 'vision',
      trigger_reason: 'manual_debug',
      timestamp: Date.now(),
      confidence: 0.92,
      content_preview: 'Visual Studio Code - PerceptionIndicator.tsx',
    };
    trigger(mockData, '用户正在编辑代码');
  };

  return (
    <div className="p-8 space-y-4">
      <h1 className="text-2xl font-bold">Hook 手动控制示例</h1>
      
      {/* 控制按钮 */}
      <div className="flex gap-2">
        <button
          onClick={handleManualTrigger}
          className="px-4 py-2 bg-sb-cyan/20 text-sb-cyan rounded-lg 
                     hover:bg-sb-cyan/30 transition-colors"
        >
          手动触发感知
        </button>
        <button
          onClick={close}
          disabled={!isActive}
          className="px-4 py-2 bg-slate-700 text-slate-300 rounded-lg 
                     hover:bg-slate-600 transition-colors disabled:opacity-50"
        >
          关闭指示器
        </button>
      </div>

      {/* 状态显示 */}
      <div className="p-4 bg-slate-900/50 rounded-lg space-y-2">
        <p className="text-sm text-slate-400">
          状态: <span className={isActive ? 'text-emerald-400' : 'text-slate-500'}>
            {isActive ? '活跃' : '隐藏'}
          </span>
        </p>
        {isActive && (
          <>
            <p className="text-sm text-slate-400">
              原因: <span className="text-slate-200">{triggerReason}</span>
            </p>
            <p className="text-sm text-slate-400">
              类型: <span className="text-slate-200">{perceptionData?.type}</span>
            </p>
          </>
        )}
      </div>

      {/* 感知指示器 */}
      <PerceptionIndicator />
    </div>
  );
};

// ============================================
// 示例 4: 不同位置配置
// ============================================
export const ExamplePositions: React.FC = () => {
  const [position, setPosition] = useState<'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'>('top-right');

  const mockData: PerceptionData = {
    type: 'vision',
    trigger_reason: 'position_test',
    timestamp: Date.now(),
    confidence: 0.85,
    content_preview: 'Test Window',
  };

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-4">位置配置示例</h1>
      
      {/* 位置选择器 */}
      <div className="flex gap-2 mb-8">
        {(['top-left', 'top-right', 'bottom-left', 'bottom-right'] as const).map((pos) => (
          <button
            key={pos}
            onClick={() => setPosition(pos)}
            className={`px-3 py-1.5 rounded text-sm transition-colors ${
              position === pos 
                ? 'bg-sb-cyan/20 text-sb-cyan' 
                : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
            }`}
          >
            {pos.replace('-', ' ')}
          </button>
        ))}
      </div>

      {/* 强制显示的感知指示器 */}
      <PerceptionIndicator
        forceShow={true}
        forceData={mockData}
        forceReason="测试位置: 查看不同角落"
        position={position}
      />
    </div>
  );
};

// ============================================
// 示例 5: 使用 Badge 版本
// ============================================
export const ExampleWithBadge: React.FC = () => {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-4">徽章版本示例</h1>
      
      {/* 在标题栏或其他紧凑空间使用 Badge */}
      <div className="flex items-center justify-between p-4 bg-slate-900/50 rounded-lg">
        <h2 className="text-lg font-medium">聊天会话 #123</h2>
        
        {/* 感知徽章 - 紧凑版本 */}
        <PerceptionBadge />
      </div>

      {/* 完整感知指示器 */}
      <PerceptionIndicator />
    </div>
  );
};

// ============================================
// 示例 6: 完整集成示例（App级别）
// ============================================
export const ExampleAppIntegration: React.FC = () => {
  return (
    <div className="app-container">
      {/* 全局UI元素 */}
      <nav className="navbar">
        {/* 导航内容 */}
      </nav>

      {/* 路由内容 */}
      <main className="main-content">
        {/* 页面路由 */}
      </main>

      {/* 
        全局感知指示器
        放在应用最顶层，这样在任何页面都能显示
      */}
      <PerceptionIndicator position="top-right" />
      
      {/* 其他全局组件 */}
      {/* <ToastContainer /> */}
      {/* <ModalContainer /> */}
    </div>
  );
};

// ============================================
// 模拟WebSocket消息测试
// ============================================
export const ExampleWebSocketSimulation: React.FC = () => {
  const simulatePerceptionEvent = () => {
    // 模拟从后端接收到的 WebSocket 消息
    const mockMessage = {
      type: 'perception_triggered',
      timestamp: new Date().toISOString(),
      data: {
        type: 'vision',
        trigger_reason: ['用户输入内容', '系统状态变化', '定时触发'][Math.floor(Math.random() * 3)],
        timestamp: Date.now(),
        confidence: Math.random(),
        content_preview: `Window - ${Math.random().toString(36).substring(7)}`,
      },
      trigger_reason: ['用户输入内容', '系统状态变化', '定时触发'][Math.floor(Math.random() * 3)],
    };

    // 通过自定义事件模拟 WebSocket 消息
    window.dispatchEvent(new CustomEvent('websocket_message', {
      detail: mockMessage,
    }));
  };

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-4">WebSocket 模拟测试</h1>
      <button
        onClick={simulatePerceptionEvent}
        className="px-4 py-2 bg-sb-cyan/20 text-sb-cyan rounded-lg 
                   hover:bg-sb-cyan/30 transition-colors"
      >
        模拟感知事件
      </button>

      <PerceptionIndicator />
    </div>
  );
};

// ============================================
// 导出所有示例
// ============================================
const PerceptionIndicatorExamples = {
  BasicUsage: ExampleBasicUsage,
  WithChatPanel: ExampleWithChatPanel,
  WithHook: ExampleWithHook,
  Positions: ExamplePositions,
  WithBadge: ExampleWithBadge,
  AppIntegration: ExampleAppIntegration,
  WebSocketSimulation: ExampleWebSocketSimulation,
};

export default PerceptionIndicatorExamples;
