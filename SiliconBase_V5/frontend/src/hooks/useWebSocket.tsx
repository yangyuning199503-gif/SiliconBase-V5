import { createContext, useContext, useEffect, useRef, useState, ReactNode } from 'react'
import { getAuthToken, getAuthUser } from '../utils/auth'
import { buildWsUrl } from '../config/api'
import type { WebSocketMessage, ClientWebSocketMessage, MemoryMetadata } from '../types'

interface WebSocketContextType {
  ws: WebSocket | null
  isConnected: boolean
  sendMessage: (data: ClientWebSocketMessage | Record<string, any>) => boolean
  lastMessage: WebSocketMessage | null
  sessionId: string | null
}

const WebSocketContext = createContext<WebSocketContextType | null>(null)

// 生成会话ID
const generateSessionId = (): string => {
  return 'sess_' + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15)
}

// 重连配置（指数退避，降低最大间隔）
const MAX_RECONNECT_ATTEMPTS = 10
const INITIAL_RECONNECT_INTERVAL = 1000  // 1秒初始间隔
const MAX_RECONNECT_INTERVAL = 10000     // 最大10秒间隔

// 心跳配置（降低频率，减少卡顿）
const HEARTBEAT_INTERVAL = 30000  // 30秒发送一次心跳
const HEARTBEAT_TIMEOUT = 15000   // 15秒未收到响应认为断开
const HEARTBEAT_GRACE_PERIOD = 60000  // 60秒宽限期才重连

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const heartbeatTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const heartbeatTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const isUnmountingRef = useRef(false)
  const isConnectingRef = useRef(false)  // 防止重复连接
  const isManuallyClosedRef = useRef(false)  // 标记是否主动关闭
  const lastPongRef = useRef(Date.now())
  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null)
  const sessionIdRef = useRef<string | null>(null)

  useEffect(() => {
    isUnmountingRef.current = false
    reconnectAttemptsRef.current = 0
    
    // 计算指数退避间隔
    const getReconnectInterval = () => {
      const interval = INITIAL_RECONNECT_INTERVAL * Math.pow(2, reconnectAttemptsRef.current)
      return Math.min(interval, MAX_RECONNECT_INTERVAL)
    }
    
    // 启动心跳检测
    const startHeartbeat = () => {
      // 清除旧的心跳定时器
      if (heartbeatTimerRef.current) {
        clearInterval(heartbeatTimerRef.current)
      }
      if (heartbeatTimeoutRef.current) {
        clearTimeout(heartbeatTimeoutRef.current)
      }
      
      lastPongRef.current = Date.now()
      
      // 定期发送ping（降低频率）
      heartbeatTimerRef.current = setInterval(() => {
        const ws = wsRef.current
        if (!ws) return
        
        // 双重检查连接状态
        if (ws.readyState !== WebSocket.OPEN) {
          console.debug('[WebSocket] 心跳检测: 连接未打开')
          return
        }
        
        try {
          ws.send(JSON.stringify({ type: 'ping', timestamp: Date.now() }))
        } catch (e) {
          console.warn('[WebSocket] 心跳发送失败:', e)
          // 发送失败时关闭连接触发重连
          try {
            ws.close()
          } catch (closeErr) {
            console.debug('[WebSocket] 关闭连接失败:', closeErr);
          }
          return
        }
        
        // 设置超时检测（放宽条件）
        heartbeatTimeoutRef.current = setTimeout(() => {
          const timeSinceLastPong = Date.now() - lastPongRef.current
          // 只有在长时间无响应才断开，允许偶尔的丢包
          if (timeSinceLastPong > HEARTBEAT_GRACE_PERIOD) {
            console.warn(`[WebSocket] 心跳超时(${Math.round(timeSinceLastPong/1000)}s)，关闭连接进行重连`)
            try {
              wsRef.current?.close()
            } catch (closeErr) {
              console.debug('[WebSocket] 关闭连接失败:', closeErr);
            }
          }
        }, HEARTBEAT_TIMEOUT)
      }, HEARTBEAT_INTERVAL)
    }
    
    // 停止心跳检测
    const stopHeartbeat = () => {
      if (heartbeatTimerRef.current) {
        clearInterval(heartbeatTimerRef.current)
        heartbeatTimerRef.current = null
      }
      if (heartbeatTimeoutRef.current) {
        clearTimeout(heartbeatTimeoutRef.current)
        heartbeatTimeoutRef.current = null
      }
    }
    
    // 连接WebSocket
    const connect = () => {
      // 如果正在卸载、连接中或超过最大重连次数，停止连接
      if (isUnmountingRef.current) return
      if (isConnectingRef.current) {
        console.log('WebSocket 正在连接中，跳过重复连接')
        return
      }
      if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
        console.error(`WebSocket 重连失败，已达到最大重试次数 (${MAX_RECONNECT_ATTEMPTS})`)
        return
      }
      
      // 如果已有连接，先关闭（先置空再 close，防止同步触发的 onclose 误判）
      if (wsRef.current) {
        const oldWs = wsRef.current
        wsRef.current = null
        oldWs.close()
      }
      
      isConnectingRef.current = true
      const reconnectDelay = getReconnectInterval()
      console.log(`WebSocket 尝试连接 (第${reconnectAttemptsRef.current}次，延迟${reconnectDelay}ms)...`)
      
      // 获取用户信息和token用于构建WebSocket URL
      const token = getAuthToken()
      const user = getAuthUser()
      
      if (!token) {
        console.debug('[WebSocket] 用户未登录，跳过WebSocket连接')
        isConnectingRef.current = false
        // 不再频繁重试，等待登录成功事件后再连接
        return
      }
      
      if (!user?.user_id) {
        console.warn('WebSocket 连接失败：未找到用户信息')
        window.dispatchEvent(new CustomEvent('auth_required', {
          detail: { reason: 'Missing user info', message: '用户信息缺失，请重新登录' }
        }))
        isConnectingRef.current = false
        return
      }
      
      // 构建带user_id和token的WebSocket URL
      const wsUrl = `${buildWsUrl(`/ws/${user.user_id}`)}?token=${encodeURIComponent(token)}`
      console.log(`WebSocket 连接URL: ${wsUrl.replace(token, '***')}`)
      
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('WebSocket connected')
        isConnectingRef.current = false
        isManuallyClosedRef.current = false
        reconnectAttemptsRef.current = 0  // 重置重连计数
        setIsConnected(true)
        
        // 启动心跳
        startHeartbeat()
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as WebSocketMessage
          
          // 处理心跳响应
          if (data.type === 'pong') {
            lastPongRef.current = Date.now()
            return
          }
          
          // 【修复】保存session_id用于会话保持
          if (data.type === 'connected' && data.session_id) {
            sessionIdRef.current = data.session_id
            console.log('[WebSocket] Session ID:', data.session_id)
          }
          
          // 【阶段2.2】处理AI响应消息，确保记忆字段正确解析
          if (data.type === 'reply' || data.type === 'message') {
            data.data = normalizeMemoryMetadata(data.data)
          }
          
          setLastMessage(data)
        } catch (e) {
          console.error('[SILENT_FAILURE_BLOCKED] WebSocket消息解析失败:', e)
          // 触发全局错误通知事件
          window.dispatchEvent(new CustomEvent('websocket_parse_error', {
            detail: { 
              error: e instanceof Error ? e.message : '未知错误',
              rawData: event.data?.substring(0, 200) // 限制长度防止日志过大
            }
          }))
        }
      }

      ws.onclose = (event) => {
        isConnectingRef.current = false
        
        // 【修复】如果当前 WebSocket 已被替换（如 connect() 主动关闭了旧连接），忽略旧连接的 onclose
        if (wsRef.current !== ws) {
          return
        }
        wsRef.current = null
        
        const code = event.code
        const reason = event.reason || '无原因'
        const wasClean = event.wasClean
        
        // 错误码说明
        const codeMessages: Record<number, string> = {
          1000: '正常关闭',
          1001: '服务器关闭',
          1006: '连接异常断开（服务器未启动或崩溃）',
          1008: '策略违规/认证失败',
          1011: '服务器遇到异常',
          1015: 'TLS 握手失败'
        }
        const codeMsg = codeMessages[code] || '未知错误'
        
        console.log(`WebSocket断开 [code: ${code}, ${codeMsg}, reason: ${reason}, clean: ${wasClean}]`)
        setIsConnected(false)
        stopHeartbeat()
        
        // 如果是认证失败，尝试重连而不是直接跳转登录页
        if (code === 1008 && (reason?.includes('token') || reason?.includes('Missing') || reason?.includes('Invalid'))) {
          console.error('WebSocket认证失败，尝试重新连接...')
          // 尝试重新获取token并重连，而不是直接跳转登录页
          const currentToken = getAuthToken()
          if (!currentToken) {
            // 只有确实没有token时才触发登录
            window.dispatchEvent(new CustomEvent('auth_required', {
              detail: { reason: 'WebSocket认证失败', message: reason }
            }))
            return  // 不重连
          }
          // 有token，继续重连逻辑
        }
        
        // 延迟重连（指数退避）
        // 【修复】在 onclose 中递增重连计数，确保断线时计数正确增加
        if (!isUnmountingRef.current && !isManuallyClosedRef.current && reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current++
          const delay = getReconnectInterval()
          console.log(`将在${delay}ms后重连 (attempt ${reconnectAttemptsRef.current}/${MAX_RECONNECT_ATTEMPTS})...`)
          reconnectTimerRef.current = setTimeout(connect, delay)
        }
      }

      ws.onerror = (error) => {
        if (isManuallyClosedRef.current || isUnmountingRef.current) {
          return
        }
        console.error('WebSocket连接错误:', error, '可能原因：(1)后端未启动 (2)端口被占用 (3)防火墙阻止 (4)后端崩溃');
      }
    }

    // 延迟连接，避免 React 严格模式快速卸载导致的问题
    const connectTimer = setTimeout(() => {
      if (!isUnmountingRef.current) {
        connect()
      }
    }, 100)

    // 【新增】监听登录成功事件，自动重连WebSocket
    const handleAuthSuccess = () => {
      console.log('[WebSocket] 检测到登录成功，尝试连接')
      reconnectAttemptsRef.current = 0  // 重置重试计数
      if (!isConnectingRef.current && !wsRef.current) {
        connect()
      }
    }

    // 【新增】监听登出事件，关闭WebSocket连接
    const handleAuthLogout = () => {
      console.log('[WebSocket] 检测到登出，关闭连接')
      isManuallyClosedRef.current = true  // 标记主动关闭，防止自动重连
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      // 清理重连定时器
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      stopHeartbeat()
    }

    window.addEventListener('auth:login_success', handleAuthSuccess)
    window.addEventListener('auth:logout', handleAuthLogout)

    return () => {
      isUnmountingRef.current = true
      isManuallyClosedRef.current = true  // 标记主动关闭
      clearTimeout(connectTimer)  // 清除连接定时器
      stopHeartbeat()
      // 清理重连定时器
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      // 关闭连接
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      window.removeEventListener('auth:login_success', handleAuthSuccess)
      window.removeEventListener('auth:logout', handleAuthLogout)
    }
  }, [])

  const sendMessage = (data: any): boolean => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        return false
    }
    try {
        const messageWithSession = {
            ...data,
            session_id: data.session_id ?? sessionIdRef.current ?? generateSessionId(),
            timestamp: Date.now()
        }
        ws.send(JSON.stringify(messageWithSession))
        return true
    } catch (e) {
        console.error('[WebSocket] 发送消息失败:', e)
        ws.close()
        // 延迟重连
        setTimeout(() => {
          if (!isManuallyClosedRef.current && !isUnmountingRef.current) {
            reconnectAttemptsRef.current = 0
            const connect = () => {
              // 触发重新连接逻辑
              window.location.reload()
            }
            connect()
          }
        }, 1000)
        return false
    }
  }

  return (
    <WebSocketContext.Provider value={{
      ws: wsRef.current,
      isConnected,
      sendMessage,
      lastMessage,
      sessionId: sessionIdRef.current,
    }}>
      {children}
    </WebSocketContext.Provider>
  )
}

export function useWebSocket() {
  const context = useContext(WebSocketContext)
  if (!context) {
    throw new Error('useWebSocket must be used within WebSocketProvider')
  }
  return context
}

// 【阶段2.2新增】记忆元数据标准化函数
/**
 * 标准化记忆元数据字段
 * 
 * 功能：
 * 1. 确保AI响应消息的记忆字段符合类型定义
 * 2. 向后兼容：处理旧消息（无记忆字段）的情况
 * 3. 数据清洗：转换无效值为null
 * 
 * @param data WebSocket消息数据
 * @returns 标准化后的数据（包含记忆元数据字段）
 */
function normalizeMemoryMetadata(data: any): any {
  if (!data || typeof data !== 'object') {
    return data
  }

  const normalized = { ...data }

  // memory_count: 必须是数字或null
  if ('memory_count' in normalized) {
    const count = normalized.memory_count
    if (count === undefined || count === null) {
      normalized.memory_count = null
    } else if (typeof count !== 'number' || isNaN(count)) {
      // 尝试转换
      const parsed = parseInt(count, 10)
      normalized.memory_count = isNaN(parsed) ? null : parsed
    }
  }

  // memory_ids: 必须是字符串数组或null
  if ('memory_ids' in normalized) {
    const ids = normalized.memory_ids
    if (ids === undefined || ids === null) {
      normalized.memory_ids = null
    } else if (!Array.isArray(ids)) {
      // 尝试转换
      if (typeof ids === 'string') {
        normalized.memory_ids = [ids]
      } else {
        normalized.memory_ids = null
      }
    } else {
      // 过滤非字符串值
      normalized.memory_ids = ids.filter(id => typeof id === 'string')
      if (normalized.memory_ids.length === 0) {
        normalized.memory_ids = null
      }
    }
  }

  // relevance_score: 必须是0-1之间的数字或null
  if ('relevance_score' in normalized) {
    const score = normalized.relevance_score
    if (score === undefined || score === null) {
      normalized.relevance_score = null
    } else if (typeof score !== 'number' || isNaN(score)) {
      // 尝试转换
      const parsed = parseFloat(score)
      normalized.relevance_score = isNaN(parsed) ? null : Math.max(0, Math.min(1, parsed))
    } else {
      // 限制在0-1范围内
      normalized.relevance_score = Math.max(0, Math.min(1, score))
    }
  }

  // memory_types: 必须是字符串数组或null
  if ('memory_types' in normalized) {
    const types = normalized.memory_types
    if (types === undefined || types === null) {
      normalized.memory_types = null
    } else if (!Array.isArray(types)) {
      // 尝试转换
      if (typeof types === 'string') {
        normalized.memory_types = [types]
      } else {
        normalized.memory_types = null
      }
    } else {
      // 过滤非字符串值
      normalized.memory_types = types.filter(t => typeof t === 'string')
      if (normalized.memory_types.length === 0) {
        normalized.memory_types = null
      }
    }
  }

  return normalized
}

// 【阶段2.2新增】提取记忆元数据的辅助函数
/**
 * 从WebSocket消息数据中提取记忆元数据
 * 
 * @param data WebSocket消息数据
 * @returns 记忆元数据对象（字段可能为null）
 */
export function extractMemoryMetadata(data: any): MemoryMetadata {
  if (!data || typeof data !== 'object') {
    return {
      memory_count: null,
      memory_ids: null,
      relevance_score: null,
      memory_types: null
    }
  }

  return {
    memory_count: data.memory_count ?? null,
    memory_ids: data.memory_ids ?? null,
    relevance_score: data.relevance_score ?? null,
    memory_types: data.memory_types ?? null
  }
}

// 【阶段2.2新增】检查消息是否包含记忆元数据
/**
 * 检查消息是否包含有效的记忆元数据
 * 
 * @param data WebSocket消息数据
 * @returns 是否包含至少一个有效的记忆字段
 */
export function hasMemoryMetadata(data: any): boolean {
  if (!data || typeof data !== 'object') {
    return false
  }

  return (
    (data.memory_count !== undefined && data.memory_count !== null) ||
    (data.memory_ids !== undefined && data.memory_ids !== null) ||
    (data.relevance_score !== undefined && data.relevance_score !== null) ||
    (data.memory_types !== undefined && data.memory_types !== null)
  )
}
