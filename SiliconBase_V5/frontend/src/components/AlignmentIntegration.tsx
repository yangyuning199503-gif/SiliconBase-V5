/**
 * AlignmentDialog 集成组件
 * 
 * 在应用的根组件中使用此组件来启用全局对齐对话框功能
 * 
 * 使用方法：
 * 1. 在 App.tsx 中导入并放置此组件
 * 2. 确保组件在 WebSocketProvider 内部
 * 
 * 示例：
 * ```tsx
 * function App() {
 *   return (
 *     <WebSocketProvider>
 *       <AlignmentIntegration />
 *       <YourApp />
 *     </WebSocketProvider>
 *   );
 * }
 * ```
 */

import React from 'react';
import { AlignmentDialog } from './AlignmentDialog';
import { useAlignment } from '../hooks/useAlignment';

/**
 * AlignmentDialog 集成组件
 * 自动监听WebSocket事件并显示对齐对话框
 */
export const AlignmentIntegration: React.FC = () => {
  const { 
    dialogProps, 
    isOpen, 
    sendClarification, 
    sendConfirmation, 
    cancelAlignment,
    pendingCount 
  } = useAlignment();

  return (
    <>
      {/* 对齐对话框 */}
      <AlignmentDialog
        {...dialogProps}
        onConfirm={() => sendConfirmation(true)}
        onClarify={(response) => sendClarification(response)}
        onCancel={cancelAlignment}
      />
      
      {/* 待处理指示器（可选）- 当对话框关闭但有待处理请求时显示 */}
      {!isOpen && pendingCount > 0 && (
        <div className="fixed bottom-4 right-4 z-50 animate-slide-up">
          <div className="flex items-center gap-2 px-4 py-2 
                        bg-amber-500 text-white rounded-full shadow-lg
                        cursor-pointer hover:bg-amber-600 transition-colors"
               onClick={() => {/* 可以在这里添加点击显示队列的功能 */}}>
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full 
                             rounded-full bg-white opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-white"></span>
            </span>
            <span className="text-sm font-medium">
              {pendingCount} 个待确认
            </span>
          </div>
        </div>
      )}
    </>
  );
};

/**
 * 简化的集成方式 - 直接在App中使用
 * 
 * 如果你不想创建单独的组件，可以直接在App.tsx中使用：
 * 
 * ```tsx
 * import { AlignmentDialog } from './components/AlignmentDialog';
 * import { useAlignment } from './hooks/useAlignment';
 * 
 * function App() {
 *   const { dialogProps, sendClarification, sendConfirmation, cancelAlignment } = useAlignment();
 * 
 *   return (
 *     <>
 *       <AlignmentDialog
 *         {...dialogProps}
 *         onConfirm={() => sendConfirmation(true)}
 *         onClarify={(response) => sendClarification(response)}
 *         onCancel={cancelAlignment}
 *       />
 *       
 *       {/* 其他组件 *\/}
 *     </>
 *   );
 * }
 * ```
 */

export default AlignmentIntegration;
