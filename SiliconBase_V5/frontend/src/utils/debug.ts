/**
 * 前端调试工具
 * 在浏览器控制台输入: window.debug.show()
 */

export function initDebugTools() {
  const debug = {
    // 显示当前消息状态
    show() {
      const messages = (window as any).store?.getState?.()?.messages || [];
      console.log('【当前消息列表】', messages);
      return messages;
    },
    
    // 模拟收到AI消息
    testReply(content: string) {
      const event = new CustomEvent('debug-message', {
        detail: {
          type: 'reply',
          data: { content },
          timestamp: Date.now()
        }
      });
      window.dispatchEvent(event);
      console.log('【测试】已发送模拟消息:', content);
    },
    
    // 检查WebSocket状态
    wsStatus() {
      const ws = (window as any).ws;
      console.log('【WebSocket状态】', {
        connected: ws?.readyState === WebSocket.OPEN,
        readyState: ws?.readyState,
        url: ws?.url
      });
    }
  };
  
  (window as any).debug = debug;
  console.log('【调试工具已加载】输入 debug.show() 查看消息状态');
}
