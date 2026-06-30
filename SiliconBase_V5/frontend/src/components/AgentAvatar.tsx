import { useRef, useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Mic, MicOff } from 'lucide-react'
import { Agent } from '../types'
import { fetchWithAuth } from '../utils/apiClient'

// [P0-009] 语音API端点配置 - 支持配置外化
// 配置优先级: 运行时配置 > 环境变量 > 构建时环境变量 > 默认值
interface VoiceApiConfig {
  host: string
  port: number
  scheme: string
  ptt_path: string
}

// 默认配置（向后兼容）
const DEFAULT_VOICE_CONFIG: VoiceApiConfig = {
  host: 'localhost',
  port: 8600,  // [P0-002] 统一为与后端status_server一致
  scheme: 'http',
  ptt_path: '/voice_ptt'
}

// 构建时环境变量配置
const ENV_CONFIG: VoiceApiConfig = {
  host: import.meta.env.VITE_VOICE_API_HOST || DEFAULT_VOICE_CONFIG.host,
  port: parseInt(import.meta.env.VITE_VOICE_API_PORT || String(DEFAULT_VOICE_CONFIG.port)),
  scheme: import.meta.env.VITE_VOICE_API_SCHEME || DEFAULT_VOICE_CONFIG.scheme,
  ptt_path: import.meta.env.VITE_VOICE_API_PTT_PATH || DEFAULT_VOICE_CONFIG.ptt_path
}



interface AgentAvatarProps {
  agent: Agent
  status: 'idle' | 'listening' | 'thinking' | 'executing' | 'observing' | 'error'
  isRecording: boolean
  onRecordingChange: (recording: boolean) => void
  onVoiceInput: (text: string) => void
}

export default function AgentAvatar({ 
  agent, 
  status, 
  isRecording, 
  onRecordingChange,
  onVoiceInput: _onVoiceInput  // 由父组件(App.tsx)通过WebSocket统一处理
}: AgentAvatarProps) {
  
  // 脉冲动画强度控制（预留）
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // [P0-009] 语音API配置状态
  const [_voiceConfig, setVoiceConfig] = useState<VoiceApiConfig>(ENV_CONFIG)

  // 组件挂载时获取运行时配置
  useEffect(() => {
    // 尝试从后端获取配置
    const fetchRuntimeConfig = async () => {
      try {
        // 优先从全局 window 对象获取（后端注入）
        if ((window as any).__SILICONBASE_CONFIG__?.voice?.api_endpoint) {
          const runtimeConfig = (window as any).__SILICONBASE_CONFIG__.voice.api_endpoint
          setVoiceConfig({
            host: runtimeConfig.host || ENV_CONFIG.host,
            port: runtimeConfig.port || ENV_CONFIG.port,
            scheme: runtimeConfig.scheme || ENV_CONFIG.scheme,
            ptt_path: runtimeConfig.ptt_path || ENV_CONFIG.ptt_path
          })
          console.log('[P0-009] 使用运行时语音配置:', runtimeConfig)
        }
      } catch (error) {
        console.warn('[P0-009] 获取运行时配置失败，使用环境变量配置:', error)
      } finally {
        // config loaded
      }
    }

    fetchRuntimeConfig()
  }, [])

  // 状态动画配置
  const statusConfig = {
    idle: { scale: 1, glow: 30, color: agent.color },
    listening: { scale: 1.1, glow: 50, color: '#00ff88' },
    thinking: { scale: 1.05, glow: 40, color: '#aa66ff' },
    executing: { scale: 1.08, glow: 45, color: '#ffaa00' },
    observing: { scale: 0.95, glow: 20, color: '#00d4ff' },
    error: { scale: 0.9, glow: 25, color: '#ff4444' },
  }

  const config = statusConfig[status]

  // 绘制波形动画
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animationId: number
    let time = 0

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      
      const centerX = canvas.width / 2
      const centerY = canvas.height / 2
      const radius = 60

      // 绘制多个圆环
      for (let i = 0; i < 3; i++) {
        ctx.beginPath()
        ctx.strokeStyle = `${agent.color}${20 + i * 10}`
        ctx.lineWidth = 2
        
        for (let angle = 0; angle < Math.PI * 2; angle += 0.1) {
          const wave = Math.sin(angle * 4 + time + i) * 5
          const r = radius + i * 15 + wave
          const x = centerX + Math.cos(angle) * r
          const y = centerY + Math.sin(angle) * r
          
          if (angle === 0) {
            ctx.moveTo(x, y)
          } else {
            ctx.lineTo(x, y)
          }
        }
        
        ctx.closePath()
        ctx.stroke()
      }

      time += 0.05
      animationId = requestAnimationFrame(draw)
    }

    draw()

    return () => cancelAnimationFrame(animationId)
  }, [agent.color, status])

  // 控制免唤醒模式（PTT）
  const setPTTMode = async (enabled: boolean) => {
    try {
      // [CORS FIX] 使用相对路径通过Vite代理访问后端
      const response = await fetchWithAuth('/voice_ptt', {
        method: 'POST',
        body: JSON.stringify({
          action: enabled ? 'start' : 'end'
        }),
      })
      
      // 检查HTTP响应状态
      if (!response.ok) {
        throw new Error(`HTTP错误: ${response.status} ${response.statusText}`)
      }
      
      let data
      try {
        data = await response.json()
      } catch (parseErr) {
        throw new Error('响应格式错误：无法解析JSON数据')
      }
      
      console.log('[PTT]', data?.message || '操作成功')
    } catch (error) {
      console.error('[PTT] 请求失败:', error)
    }
  }

  // 处理录音按钮点击
  const handleMicClick = async () => {
    if (isRecording) {
      // 结束录音
      onRecordingChange(false)
      await setPTTMode(false)  // 结束免唤醒模式
      // 注意：真实识别结果通过WebSocket从后端接收，不是这里直接产生
    } else {
      // 开始录音
      onRecordingChange(true)
      await setPTTMode(true)  // 启动免唤醒模式
      // 录音状态由后端控制，前端只发送开始信号
    }
  }

  return (
    <div className="flex flex-col items-center gap-4">
      {/* Avatar Container */}
      <div className="relative z-50">
        {/* 外发光 */}
        <motion.div
          className="absolute inset-0 rounded-full blur-xl z-40"
          animate={{
            scale: [1, 1.2, 1],
            opacity: [0.3, 0.6, 0.3],
          }}
          transition={{
            duration: 3,
            repeat: Infinity,
            ease: "easeInOut",
          }}
          style={{ backgroundColor: config.color }}
        />

        {/* 波形Canvas */}
        <canvas
          ref={canvasRef}
          width={200}
          height={200}
          className="absolute inset-0 -m-[50px] z-30"
        />

        {/* Avatar Circle */}
        <motion.div
          className="w-24 h-24 rounded-full flex items-center justify-center text-4xl relative z-50"
          style={{
            background: `linear-gradient(135deg, ${agent.color}40 0%, ${agent.color}20 100%)`,
            border: `2px solid ${agent.color}`,
            boxShadow: `0 0 ${config.glow}px ${agent.color}50`,
          }}
          animate={{
            scale: config.scale,
          }}
          transition={{ duration: 0.3 }}
        >
          {agent.icon}
        </motion.div>

        {/* 状态指示器 */}
        <div 
          className="absolute -bottom-1 -right-1 w-6 h-6 rounded-full border-2 border-sb-bg-primary flex items-center justify-center z-50"
          style={{ backgroundColor: config.color }}
        >
          {status === 'listening' && <div className="w-2 h-2 bg-white rounded-full animate-pulse" />}
          {status === 'thinking' && <div className="w-2 h-2 border-2 border-white border-t-transparent rounded-full animate-spin" />}
          {status === 'executing' && <div className="w-2 h-2 bg-white rounded-full" />}
          {status === 'observing' && <div className="w-2 h-2 border border-white/60 rounded-full" />}
        </div>
      </div>

      {/* 状态文字 */}
      <div className="text-xs text-white/50 capitalize">
        {status === 'idle' && '就绪'}
        {status === 'listening' && '聆听中...'}
        {status === 'thinking' && '思考中...'}
        {status === 'executing' && '执行中...'}
        {status === 'observing' && '观察中...'}
      </div>

      {/* 语音按钮 */}
      <button
        onClick={handleMicClick}
        className={`w-12 h-12 rounded-full flex items-center justify-center transition-all ${
          isRecording 
            ? 'bg-red-500 text-white animate-pulse' 
            : 'glass hover:bg-white/10'
        }`}
      >
        {isRecording ? <MicOff className="w-5 h-5" /> : <Mic className="w-5 h-5" />}
      </button>

      <span className="text-xs text-white/30">{isRecording ? '点击停止' : '按住说话'}</span>
    </div>
  )
}
