/**
 * Phase1-Agent9: 可视化兼容性修复代码
 * 
 * 基于兼容性测试报告的问题修复
 * 
 * 修复内容:
 * 1. WebSocket连接稳定性
 * 2. 响应式布局支持
 * 3. 触摸事件支持
 * 4. CSS降级处理
 * 5. Canvas高DPI支持
 * 
 * @author Agent-9
 * @version 1.0.0
 */

// ═══════════════════════════════════════════════════════════════════
// 修复1: WebSocket Hook with 重连限制
// ═══════════════════════════════════════════════════════════════════

import { useEffect, useRef, useState, useCallback } from 'react';

interface WebSocketMessage {
  type: string;
  data: any;
}

interface UseMemoryWebSocketOptions {
  userId: string;
  maxReconnectAttempts?: number;
  reconnectDelay?: number;
  onMessage?: (data: WebSocketMessage) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Event) => void;
}

export function useMemoryWebSocket(options: UseMemoryWebSocketOptions) {
  const {
    userId,
    maxReconnectAttempts = 5,
    reconnectDelay = 5000,
    onMessage,
    onConnect,
    onDisconnect,
    onError
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const [reconnectCount, setReconnectCount] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (!userId) {
      console.warn('[MemoryWebSocket] userId is required');
      return;
    }

    // 清理旧连接（先置空再 close，防止同步触发的 onclose 误判）
    if (wsRef.current) {
      const oldWs = wsRef.current;
      wsRef.current = null;
      oldWs.close();
    }

    // 动态检测协议和端口
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.hostname;
    const port = window.location.port || (protocol === 'wss:' ? '443' : '8600');
    const token = localStorage.getItem('silicon_token');
    const wsUrl = `${protocol}//${host}:${port}/api/memories/ws/realtime/${userId}${token ? `?token=${token}` : ''}`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('[MemoryWebSocket] Connected');
        reconnectAttemptsRef.current = 0;
        setReconnectCount(0);
        setIsConnected(true);
        onConnect?.();
        
        // 订阅消息
        ws.send(JSON.stringify({ action: 'subscribe' }));
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          onMessage?.(data);
        } catch (e) {
          console.error('[MemoryWebSocket] Failed to parse message:', e);
        }
      };

      ws.onerror = (error) => {
        console.error('[MemoryWebSocket] Error:', error);
        onError?.(error);
      };

      ws.onclose = (event) => {
        // 【修复】如果当前 WebSocket 已被替换（如 connect() 主动关闭了旧连接），忽略旧连接的 onclose
        if (wsRef.current !== ws) {
          return;
        }
        wsRef.current = null;
        
        console.log('[MemoryWebSocket] Disconnected:', event.code, event.reason);
        setIsConnected(false);
        onDisconnect?.();

        // 指数退避重连
        if (reconnectAttemptsRef.current < maxReconnectAttempts) {
          reconnectAttemptsRef.current++;
          setReconnectCount(reconnectAttemptsRef.current);
          
          const delay = Math.min(
            reconnectDelay * Math.pow(1.5, reconnectAttemptsRef.current - 1),
            30000 // 最大30秒
          );
          
          console.log(`[MemoryWebSocket] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current}/${maxReconnectAttempts})`);
          
          reconnectTimerRef.current = setTimeout(() => {
            connect();
          }, delay);
        } else {
          console.error('[MemoryWebSocket] Max reconnect attempts reached');
        }
      };
    } catch (error) {
      console.error('[MemoryWebSocket] Failed to create connection:', error);
    }
  }, [userId, maxReconnectAttempts, reconnectDelay, onMessage, onConnect, onDisconnect, onError]);

  const disconnect = useCallback(() => {
    reconnectAttemptsRef.current = maxReconnectAttempts; // 阻止自动重连
    
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    
    setIsConnected(false);
  }, [maxReconnectAttempts]);

  const send = useCallback((data: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
      return true;
    }
    return false;
  }, []);

  useEffect(() => {
    connect();
    
    // 页面可见性变化处理
    const handleVisibilityChange = () => {
      if (document.hidden) {
        // 页面隐藏时断开连接
        disconnect();
      } else {
        // 页面显示时重新连接
        reconnectAttemptsRef.current = 0;
        connect();
      }
    };
    
    document.addEventListener('visibilitychange', handleVisibilityChange);
    
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    isConnected,
    reconnectCount,
    send,
    connect,
    disconnect
  };
}

// ═══════════════════════════════════════════════════════════════════
// 修复2: 响应式Canvas组件
// ═══════════════════════════════════════════════════════════════════

interface ResponsiveCanvasProps {
  className?: string;
  onDraw: (ctx: CanvasRenderingContext2D, width: number, height: number) => void;
  onResize?: (width: number, height: number) => void;
  animationFrame?: boolean;
}

export function ResponsiveCanvas({
  className,
  onDraw,
  onResize,
  animationFrame = false
}: ResponsiveCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number>(0);
  const dprRef = useRef(window.devicePixelRatio || 1);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // 设置高DPI支持
    const setupCanvas = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      dprRef.current = dpr;

      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); // 使用setTransform代替scale
      
      onResize?.(rect.width, rect.height);
    };

    setupCanvas();

    // 使用ResizeObserver监听尺寸变化
    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.target === canvas) {
          setupCanvas();
        }
      }
    });

    resizeObserver.observe(canvas);

    // 动画循环
    let lastTime = 0;
    const targetFPS = 30;
    const frameInterval = 1000 / targetFPS;

    const animate = (time: number) => {
      if (time - lastTime >= frameInterval) {
        const rect = canvas.getBoundingClientRect();
        onDraw(ctx, rect.width, rect.height);
        lastTime = time;
      }
      
      if (animationFrame) {
        animationRef.current = requestAnimationFrame(animate);
      }
    };

    if (animationFrame) {
      animationRef.current = requestAnimationFrame(animate);
    } else {
      const rect = canvas.getBoundingClientRect();
      onDraw(ctx, rect.width, rect.height);
    }

    return () => {
      resizeObserver.disconnect();
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [onDraw, onResize, animationFrame]);

  return (
    <canvas
      ref={canvasRef}
      className={`w-full h-full ${className || ''}`}
      style={{
        imageRendering: 'crisp-edges'
      }}
    />
  );
}

// ═══════════════════════════════════════════════════════════════════
// 修复3: 触摸事件支持Hook
// ═══════════════════════════════════════════════════════════════════

interface TouchPosition {
  x: number;
  y: number;
}

interface UseTouchEventsOptions {
  onTouchStart?: (pos: TouchPosition, e: TouchEvent) => void;
  onTouchMove?: (pos: TouchPosition, delta: TouchPosition, e: TouchEvent) => void;
  onTouchEnd?: (pos: TouchPosition, e: TouchEvent) => void;
  onTap?: (pos: TouchPosition, e: TouchEvent) => void;
  onDoubleTap?: (pos: TouchPosition, e: TouchEvent) => void;
  onPinch?: (scale: number, center: TouchPosition, e: TouchEvent) => void;
}

export function useTouchEvents(
  elementRef: React.RefObject<HTMLElement>,
  options: UseTouchEventsOptions
) {
  const {
    onTouchStart,
    onTouchMove,
    onTouchEnd,
    onTap,
    onDoubleTap,
    onPinch
  } = options;

  const touchStartRef = useRef<TouchPosition | null>(null);
  const touchStartTimeRef = useRef<number>(0);
  const lastTapTimeRef = useRef<number>(0);
  const initialPinchDistanceRef = useRef<number>(0);
  const initialPinchCenterRef = useRef<TouchPosition>({ x: 0, y: 0 });

  const getTouchPos = useCallback((touch: Touch, element: HTMLElement): TouchPosition => {
    const rect = element.getBoundingClientRect();
    return {
      x: touch.clientX - rect.left,
      y: touch.clientY - rect.top
    };
  }, []);

  const getDistance = useCallback((touch1: Touch, touch2: Touch): number => {
    const dx = touch1.clientX - touch2.clientX;
    const dy = touch1.clientY - touch2.clientY;
    return Math.sqrt(dx * dx + dy * dy);
  }, []);

  const getCenter = useCallback((touch1: Touch, touch2: Touch, element: HTMLElement): TouchPosition => {
    const rect = element.getBoundingClientRect();
    return {
      x: (touch1.clientX + touch2.clientX) / 2 - rect.left,
      y: (touch1.clientY + touch2.clientY) / 2 - rect.top
    };
  }, []);

  useEffect(() => {
    const element = elementRef.current;
    if (!element) return;

    const handleTouchStart = (e: TouchEvent) => {
      e.preventDefault();
      
      if (e.touches.length === 1) {
        const pos = getTouchPos(e.touches[0], element);
        touchStartRef.current = pos;
        touchStartTimeRef.current = Date.now();
        
        onTouchStart?.(pos, e);

        // 检测双击
        const now = Date.now();
        if (now - lastTapTimeRef.current < 300) {
          onDoubleTap?.(pos, e);
          lastTapTimeRef.current = 0;
        } else {
          lastTapTimeRef.current = now;
        }
      } else if (e.touches.length === 2) {
        // 双指缩放
        initialPinchDistanceRef.current = getDistance(e.touches[0], e.touches[1]);
        initialPinchCenterRef.current = getCenter(e.touches[0], e.touches[1], element);
      }
    };

    const handleTouchMove = (e: TouchEvent) => {
      e.preventDefault();

      if (e.touches.length === 1 && touchStartRef.current) {
        const pos = getTouchPos(e.touches[0], element);
        const delta = {
          x: pos.x - touchStartRef.current.x,
          y: pos.y - touchStartRef.current.y
        };
        onTouchMove?.(pos, delta, e);
      } else if (e.touches.length === 2 && initialPinchDistanceRef.current > 0) {
        const distance = getDistance(e.touches[0], e.touches[1]);
        const scale = distance / initialPinchDistanceRef.current;
        onPinch?.(scale, initialPinchCenterRef.current, e);
      }
    };

    const handleTouchEnd = (e: TouchEvent) => {
      if (touchStartRef.current) {
        const touch = e.changedTouches[0];
        const pos = getTouchPos(touch, element);
        
        // 检测点击
        const touchDuration = Date.now() - touchStartTimeRef.current;
        const moveDistance = touchStartRef.current 
          ? Math.sqrt(
              Math.pow(pos.x - touchStartRef.current.x, 2) +
              Math.pow(pos.y - touchStartRef.current.y, 2)
            )
          : Infinity;

        if (touchDuration < 300 && moveDistance < 10) {
          onTap?.(pos, e);
        }

        onTouchEnd?.(pos, e);
      }

      touchStartRef.current = null;
      initialPinchDistanceRef.current = 0;
    };

    element.addEventListener('touchstart', handleTouchStart, { passive: false });
    element.addEventListener('touchmove', handleTouchMove, { passive: false });
    element.addEventListener('touchend', handleTouchEnd);
    element.addEventListener('touchcancel', handleTouchEnd);

    return () => {
      element.removeEventListener('touchstart', handleTouchStart);
      element.removeEventListener('touchmove', handleTouchMove);
      element.removeEventListener('touchend', handleTouchEnd);
      element.removeEventListener('touchcancel', handleTouchEnd);
    };
  }, [elementRef, onTouchStart, onTouchMove, onTouchEnd, onTap, onDoubleTap, onPinch, getTouchPos, getDistance, getCenter]);
}

// ═══════════════════════════════════════════════════════════════════
// 修复4: 响应式布局组件
// ═══════════════════════════════════════════════════════════════════

interface ResponsiveLayoutProps {
  children: React.ReactNode;
  sidebar: React.ReactNode;
  className?: string;
}

export function ResponsiveLayout({ children, sidebar, className }: ResponsiveLayoutProps) {
  const [isMobile, setIsMobile] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 1024);
    };

    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  return (
    <div className={`flex flex-col lg:flex-row h-full ${className || ''}`}>
      {/* 移动端侧边栏切换按钮 */}
      {isMobile && (
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="lg:hidden p-3 bg-sb-bg-secondary border-b border-white/10 text-white"
        >
          {sidebarOpen ? '关闭面板' : '打开面板'}
        </button>
      )}

      {/* 主内容区 */}
      <div className="flex-1 overflow-hidden order-2 lg:order-1">
        {children}
      </div>

      {/* 侧边栏 */}
      <div
        className={`
          ${isMobile 
            ? `fixed inset-x-0 bottom-0 bg-sb-bg-primary z-50 transform transition-transform duration-300 ${sidebarOpen ? 'translate-y-0' : 'translate-y-full'}` 
            : 'w-80 border-l border-white/10'
          }
          p-4 space-y-4 overflow-auto
          order-1 lg:order-2
        `}
        style={{ maxHeight: isMobile ? '60vh' : undefined }}
      >
        {sidebar}
      </div>

      {/* 移动端遮罩 */}
      {isMobile && sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 修复5: 性能优化的记忆流动图
// ═══════════════════════════════════════════════════════════════════

interface MemoryFlowItem {
  id: string;
  type: 'input' | 'output' | 'transform';
  content: string;
  layer: string;
  timestamp: string;
}

interface OptimizedMemoryFlowChartProps {
  data: {
    inputs: MemoryFlowItem[];
    outputs: MemoryFlowItem[];
    transforms: MemoryFlowItem[];
  };
  isPlaying: boolean;
}

export function OptimizedMemoryFlowChart({ data, isPlaying }: OptimizedMemoryFlowChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number>(0);
  const particlesRef = useRef<Array<{
    x: number;
    y: number;
    vx: number;
    vy: number;
    life: number;
    maxLife: number;
    color: string;
  }>>([]);
  const offscreenCanvasRef = useRef<HTMLCanvasElement | null>(null);

  // 初始化离屏Canvas用于静态内容
  useEffect(() => {
    offscreenCanvasRef.current = document.createElement('canvas');
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const offscreen = offscreenCanvasRef.current;
    const offCtx = offscreen?.getContext('2d');

    // 高DPI支持
    const setupCanvas = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      if (offscreen && offCtx) {
        offscreen.width = canvas.width;
        offscreen.height = canvas.height;
        offCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
    };

    setupCanvas();

    // 绘制静态内容到离屏Canvas
    const drawStatic = (width: number, height: number) => {
      if (!offCtx) return;
      
      offCtx.clearRect(0, 0, width, height);

      // 绘制三个区域
      const sectionWidth = width / 3;
      
      offCtx.fillStyle = 'rgba(0, 212, 255, 0.05)';
      offCtx.fillRect(0, 0, sectionWidth, height);
      offCtx.fillStyle = 'rgba(255, 170, 0, 0.05)';
      offCtx.fillRect(sectionWidth, 0, sectionWidth, height);
      offCtx.fillStyle = 'rgba(0, 255, 136, 0.05)';
      offCtx.fillRect(sectionWidth * 2, 0, sectionWidth, height);

      // 绘制分隔线
      offCtx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
      offCtx.lineWidth = 1;
      offCtx.beginPath();
      offCtx.moveTo(sectionWidth, 0);
      offCtx.lineTo(sectionWidth, height);
      offCtx.moveTo(sectionWidth * 2, 0);
      offCtx.lineTo(sectionWidth * 2, height);
      offCtx.stroke();

      // 绘制标题
      offCtx.font = '14px system-ui, -apple-system, sans-serif';
      offCtx.fillStyle = '#00d4ff';
      offCtx.textAlign = 'center';
      offCtx.fillText(`新增记忆 (${data.inputs.length})`, sectionWidth / 2, 30);
      offCtx.fillStyle = '#ffaa00';
      offCtx.fillText(`转换/升级 (${data.transforms.length})`, sectionWidth * 1.5, 30);
      offCtx.fillStyle = '#00ff88';
      offCtx.fillText(`检索/输出 (${data.outputs.length})`, sectionWidth * 2.5, 30);
    };

    // 动画循环
    let lastTime = 0;
    let frameCount = 0;
    const targetFPS = 30;
    const frameInterval = 1000 / targetFPS;

    const animate = (time: number) => {
      // 使用Page Visibility API优化
      if (document.hidden) {
        animationRef.current = requestAnimationFrame(animate);
        return;
      }

      // FPS限制
      if (time - lastTime < frameInterval) {
        animationRef.current = requestAnimationFrame(animate);
        return;
      }

      const elapsed = time - lastTime;
      lastTime = time;
      frameCount++;

      const rect = canvas.getBoundingClientRect();
      const width = rect.width;
      const height = rect.height;
      const sectionWidth = width / 3;

      ctx.clearRect(0, 0, width, height);

      // 绘制静态背景（从离屏Canvas复制）
      if (offscreen && frameCount % 10 === 0) { // 每10帧更新一次静态内容
        drawStatic(width, height);
      }
      if (offscreen) {
        ctx.drawImage(offscreen, 0, 0, width, height);
      }

      // 绘制数据项
      const drawItems = (items: MemoryFlowItem[], x: number, color: string) => {
        items.slice(0, 8).forEach((item, i) => {
          const y = 60 + i * 45;
          
          ctx.beginPath();
          ctx.arc(x, y, 6, 0, Math.PI * 2);
          ctx.fillStyle = color;
          ctx.fill();

          ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
          ctx.font = '11px system-ui, -apple-system, sans-serif';
          ctx.textAlign = 'left';
          const content = item.content.slice(0, 20) + (item.content.length > 20 ? '...' : '');
          ctx.fillText(content, x + 15, y + 4);

          ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
          ctx.font = '9px system-ui, -apple-system, sans-serif';
          ctx.fillText(item.layer, x + 15, y + 16);
        });
      };

      drawItems(data.inputs, sectionWidth / 2, '#00d4ff');
      drawItems(data.transforms, sectionWidth * 1.5, '#ffaa00');
      drawItems(data.outputs, sectionWidth * 2.5, '#00ff88');

      // 粒子动画
      if (isPlaying) {
        // 控制粒子数量
        if (particlesRef.current.length < 20 && Math.random() < 0.1) {
          const sourceSection = Math.floor(Math.random() * 2);
          particlesRef.current.push({
            x: sourceSection === 0 ? sectionWidth : sectionWidth * 2,
            y: 60 + Math.random() * (height - 100),
            vx: sectionWidth / 60,
            vy: (Math.random() - 0.5) * 0.5,
            life: 60,
            maxLife: 60,
            color: sourceSection === 0 ? '#00d4ff' : '#ffaa00'
          });
        }

        // 更新和绘制粒子
        particlesRef.current = particlesRef.current.filter(p => {
          p.x += p.vx * (elapsed / 33); // 基于时间的移动
          p.y += p.vy * (elapsed / 33);
          p.life--;

          if (p.life > 0) {
            ctx.beginPath();
            ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
            ctx.fillStyle = p.color;
            ctx.globalAlpha = p.life / p.maxLife;
            ctx.fill();
            ctx.globalAlpha = 1;
            return true;
          }
          return false;
        });
      }

      animationRef.current = requestAnimationFrame(animate);
    };

    animate(0);

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [data, isPlaying]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full"
      style={{
        imageRendering: 'crisp-edges'
      }}
    />
  );
}

// ═══════════════════════════════════════════════════════════════════
// 修复6: CSS兼容性降级
// ═══════════════════════════════════════════════════════════════════

/**
 * 添加到 index.css 的修复代码
 */
export const cssFixes = `
/* ═══════════════════════════════════════════════════════════════
   Agent9 兼容性修复 - CSS降级支持
   ═══════════════════════════════════════════════════════════════ */

/* 1. backdrop-filter Firefox降级 */
.glass {
  /* Firefox降级 - 不使用backdrop-filter时的样式 */
  background: rgba(255, 255, 255, 0.08);
}

@supports (backdrop-filter: blur(12px)) {
  .glass {
    background: rgba(255, 255, 255, 0.04);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
  }
}

/* 2. 响应式布局断点 */
@media (max-width: 1023px) {
  .viz-container {
    flex-direction: column;
  }
  
  .viz-sidebar {
    width: 100%;
    border-left: none;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    max-height: 40vh;
  }
}

@media (max-width: 767px) {
  .viz-grid-4 {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .viz-grid-2 {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 479px) {
  .viz-grid-4 {
    grid-template-columns: 1fr;
  }
}

/* 3. 触摸设备优化 */
@media (pointer: coarse) {
  .viz-canvas {
    touch-action: none; /* 禁用默认触摸行为 */
  }
  
  .viz-button {
    min-height: 44px; /* iOS推荐最小点击区域 */
    min-width: 44px;
  }
}

/* 4. 减少动画偏好 */
@media (prefers-reduced-motion: reduce) {
  .viz-animated {
    animation: none !important;
    transition: none !important;
  }
  
  .viz-particle {
    display: none;
  }
}

/* 5. 高对比度模式支持 */
@media (prefers-contrast: high) {
  .glass {
    border-width: 2px;
  }
  
  .viz-text-muted {
    color: rgba(255, 255, 255, 0.7);
  }
}

/* 6. 打印样式 */
@media print {
  .viz-canvas {
    break-inside: avoid;
  }
  
  .viz-no-print {
    display: none !important;
  }
}
`;

// ═══════════════════════════════════════════════════════════════════
// 修复7: 错误边界组件
// ═══════════════════════════════════════════════════════════════════

import { Component, ErrorInfo, ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class VisualizationErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('[VisualizationErrorBoundary] Canvas error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback || (
        <div className="flex items-center justify-center h-full bg-sb-bg-secondary rounded-xl border border-white/10 p-8">
          <div className="text-center">
            <div className="text-4xl mb-4">⚠️</div>
            <h3 className="text-white font-medium mb-2">可视化渲染失败</h3>
            <p className="text-white/60 text-sm mb-4">
              您的浏览器可能不支持某些图形功能
            </p>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="px-4 py-2 bg-sb-cyan text-sb-bg-primary rounded-lg hover:bg-sb-cyan/80 transition-colors"
            >
              重试
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

// ═══════════════════════════════════════════════════════════════════
// 使用示例
// ═══════════════════════════════════════════════════════════════════

/*
// 在 MemoryVisualizationPage.tsx 中使用修复后的组件:

import {
  useMemoryWebSocket,
  ResponsiveLayout,
  OptimizedMemoryFlowChart,
  VisualizationErrorBoundary
} from './AGENT9_COMPATIBILITY_FIXES';

export function MemoryVisualizationPage() {
  const user = JSON.parse(localStorage.getItem('auth_user') || '{}');
  
  const { isConnected, reconnectCount } = useMemoryWebSocket({
    userId: user.user_id,
    onMessage: (data) => {
      if (data.type === 'memory_update') {
        setRealtimeUpdates(prev => [data.data, ...prev].slice(0, 50));
      }
    }
  });

  return (
    <VisualizationErrorBoundary>
      <ResponsiveLayout
        sidebar={
          <>
            <RealtimeMonitor updates={realtimeUpdates} />
            {!isConnected && reconnectCount > 0 && (
              <div className="text-yellow-400 text-sm">
                重连中... ({reconnectCount})
              </div>
            )}
          </>
        }
      >
        <OptimizedMemoryFlowChart data={flowData} isPlaying={isPlaying} />
      </ResponsiveLayout>
    </VisualizationErrorBoundary>
  );
}
*/
