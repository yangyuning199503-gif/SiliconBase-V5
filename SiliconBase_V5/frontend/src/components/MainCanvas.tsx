import { useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import { Agent } from '../types'

interface MainCanvasProps {
  currentAgent: Agent
  agentStatus: string
}

export default function MainCanvas({ currentAgent, agentStatus }: MainCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // 绘制神经网络背景 - 科技感增强版
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animationId: number
    let time = 0

    const resize = () => {
      canvas.width = canvas.offsetWidth
      canvas.height = canvas.offsetHeight
    }
    resize()
    window.addEventListener('resize', resize)

    // 增加节点数量，更大的节点
    const nodes: { x: number; y: number; vx: number; vy: number; size: number }[] = []
    const nodeCount = 25 // 从16增加到25
    for (let i = 0; i < nodeCount; i++) {
      nodes.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.5,
        vy: (Math.random() - 0.5) * 0.5,
        size: 4 + Math.random() * 4, // 节点大小随机 4-8px
      })
    }

    // 粒子效果
    const particles: { x: number; y: number; vx: number; vy: number; life: number; maxLife: number }[] = []
    
    const createParticle = (x: number, y: number) => {
      if (particles.length < 15) {
        particles.push({
          x,
          y,
          vx: (Math.random() - 0.5) * 2,
          vy: (Math.random() - 0.5) * 2,
          life: 0,
          maxLife: 60 + Math.random() * 40
        })
      }
    }

    const draw = () => {
      // 清除画布 - 使用更透明的背景创造拖尾效果
      ctx.fillStyle = 'rgba(20, 20, 28, 0.2)'
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      // 更新节点位置
      nodes.forEach((node) => {
        node.x += node.vx
        node.y += node.vy

        if (node.x < 0 || node.x > canvas.width) node.vx *= -1
        if (node.y < 0 || node.y > canvas.height) node.vy *= -1
      })

      // 绘制连线 - 更粗的连线，更大的连接范围
      nodes.forEach((node, i) => {
        nodes.slice(i + 1).forEach((other) => {
          const dx = other.x - node.x
          const dy = other.y - node.y
          const dist = Math.sqrt(dx * dx + dy * dy)

          if (dist < 180) { // 从120增加到180
            const opacity = (1 - dist / 180) * 0.5
            const hexOpacity = Math.floor(opacity * 255).toString(16).padStart(2, '0')
            
            // 绘制发光连线
            ctx.beginPath()
            ctx.strokeStyle = `${currentAgent.color}${hexOpacity}`
            ctx.lineWidth = 2 // 从1.5增加到2
            ctx.moveTo(node.x, node.y)
            ctx.lineTo(other.x, other.y)
            ctx.stroke()

            // 随机在连线上创建粒子
            if (Math.random() < 0.01) {
              const t = Math.random()
              const px = node.x + (other.x - node.x) * t
              const py = node.y + (other.y - node.y) * t
              createParticle(px, py)
            }
          }
        })
      })

      // 更新和绘制粒子
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i]
        p.x += p.vx
        p.y += p.vy
        p.life++

        if (p.life >= p.maxLife) {
          particles.splice(i, 1)
          continue
        }

        const lifeRatio = 1 - (p.life / p.maxLife)
        ctx.beginPath()
        ctx.fillStyle = `${currentAgent.color}${Math.floor(lifeRatio * 128).toString(16).padStart(2, '0')}`
        ctx.arc(p.x, p.y, 2 * lifeRatio, 0, Math.PI * 2)
        ctx.fill()
      }

      // 绘制节点 - 更大的发光节点
      nodes.forEach((node, i) => {
        const pulse = Math.sin(time + i * 0.5) * 0.5 + 0.5
        
        // 外圈光晕 - 更大更亮
        const gradient = ctx.createRadialGradient(
          node.x, node.y, 0,
          node.x, node.y, 15 + pulse * 8 // 从8+4增加到15+8
        )
        gradient.addColorStop(0, `${currentAgent.color}${Math.floor((0.4 + pulse * 0.3) * 255).toString(16).padStart(2, '0')}`)
        gradient.addColorStop(0.5, `${currentAgent.color}${Math.floor((0.2 + pulse * 0.2) * 255).toString(16).padStart(2, '0')}`)
        gradient.addColorStop(1, 'transparent')
        
        ctx.fillStyle = gradient
        ctx.beginPath()
        ctx.arc(node.x, node.y, 15 + pulse * 8, 0, Math.PI * 2)
        ctx.fill()
        
        // 内核 - 更大更亮
        ctx.fillStyle = currentAgent.color
        ctx.globalAlpha = 0.8 + pulse * 0.2
        ctx.beginPath()
        ctx.arc(node.x, node.y, node.size + pulse * 2, 0, Math.PI * 2)
        ctx.fill()
        ctx.globalAlpha = 1

        // 内核高光
        ctx.fillStyle = 'rgba(255, 255, 255, 0.8)'
        ctx.beginPath()
        ctx.arc(node.x - 2, node.y - 2, (node.size + pulse * 2) * 0.3, 0, Math.PI * 2)
        ctx.fill()
      })

      // 绘制六边形网格背景效果
      const hexSize = 40
      const hexOpacity = 0.03
      ctx.strokeStyle = `${currentAgent.color}${Math.floor(hexOpacity * 255).toString(16).padStart(2, '0')}`
      ctx.lineWidth = 0.5
      
      for (let x = 0; x < canvas.width + hexSize; x += hexSize * 3) {
        for (let y = 0; y < canvas.height + hexSize; y += hexSize * 1.73) {
          const offsetX = (y / (hexSize * 1.73)) % 2 === 0 ? 0 : hexSize * 1.5
          drawHexagon(ctx, x + offsetX - hexSize, y, hexSize)
        }
      }

      time += 0.02
      animationId = requestAnimationFrame(draw)
    }

    // 绘制六边形辅助函数
    const drawHexagon = (ctx: CanvasRenderingContext2D, x: number, y: number, size: number) => {
      ctx.beginPath()
      for (let i = 0; i < 6; i++) {
        const angle = (Math.PI / 3) * i
        const hx = x + size * Math.cos(angle)
        const hy = y + size * Math.sin(angle)
        if (i === 0) ctx.moveTo(hx, hy)
        else ctx.lineTo(hx, hy)
      }
      ctx.closePath()
      ctx.stroke()
    }

    draw()

    return () => {
      cancelAnimationFrame(animationId)
      window.removeEventListener('resize', resize)
    }
  }, [currentAgent.color])

  // 状态配置
  const statusConfig = {
    idle: { text: '就绪', color: '#00ff88', glowColor: 'rgba(0, 255, 136, 0.4)' },
    listening: { text: '聆听中', color: '#00ff88', glowColor: 'rgba(0, 255, 136, 0.5)' },
    thinking: { text: '思考中', color: '#aa66ff', glowColor: 'rgba(170, 102, 255, 0.5)' },
    executing: { text: '执行中', color: '#ffaa00', glowColor: 'rgba(255, 170, 0, 0.5)' },
    observing: { text: '观察中', color: '#00d4ff', glowColor: 'rgba(0, 212, 255, 0.5)' },
    error: { text: '错误', color: '#ff4444', glowColor: 'rgba(255, 68, 68, 0.5)' },
  }

  const status = statusConfig[agentStatus as keyof typeof statusConfig] || statusConfig.idle

  return (
    <div className="h-32 relative overflow-hidden border-b border-white/5 bg-gradient-to-b from-transparent to-black/10 shrink-0">
      {/* 背景Canvas */}
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full opacity-95"
      />

      {/* 状态指示器 - 增强设计 */}
      <div className="absolute inset-0 flex items-center justify-center">
        <motion.div
          className="flex items-center gap-4 px-6 py-3 rounded-2xl bg-[#1e1e2a]/80 border border-white/10 backdrop-blur-md"
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          key={agentStatus}
          style={{
            boxShadow: `0 0 30px ${status.glowColor}, 0 0 60px ${status.glowColor.replace('0.5', '0.2')}`,
          }}
        >
          {/* 状态指示灯 - 脉冲效果 */}
          <div className="relative">
            <motion.div
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: status.color }}
              animate={{
                scale: agentStatus === 'thinking' ? [1, 1.3, 1] : [1, 1.2, 1],
              }}
              transition={{
                duration: agentStatus === 'thinking' ? 0.8 : 2,
                repeat: Infinity,
                ease: 'easeInOut',
              }}
            />
            {/* 外圈脉冲 */}
            <motion.div
              className="absolute inset-0 w-3 h-3 rounded-full"
              style={{ backgroundColor: status.color }}
              animate={{
                scale: [1, 2, 2.5],
                opacity: [0.6, 0.3, 0],
              }}
              transition={{
                duration: 2,
                repeat: Infinity,
                ease: 'easeOut',
              }}
            />
          </div>
          
          {/* 状态文字 */}
          <span 
            className="text-sm font-semibold tracking-wider"
            style={{ color: status.color }}
          >
            {status.text}
          </span>

          {/* 动态指示器 */}
          {agentStatus === 'thinking' && (
            <div className="flex gap-1">
              {[0, 1, 2].map((i) => (
                <motion.div
                  key={i}
                  className="w-1 h-1 rounded-full"
                  style={{ backgroundColor: status.color }}
                  animate={{ opacity: [0.3, 1, 0.3] }}
                  transition={{
                    duration: 1,
                    repeat: Infinity,
                    delay: i * 0.2,
                  }}
                />
              ))}
            </div>
          )}
        </motion.div>
      </div>

      {/* 角落信息 - 增强样式 */}
      <div className="absolute bottom-4 left-5 text-[11px] text-white/40 hidden sm:block">
        <div className="flex items-center gap-2 bg-[#1e1e2a]/50 px-3 py-1.5 rounded-full border border-white/5">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <span>WebSocket 已连接</span>
        </div>
      </div>

      <div className="absolute bottom-4 right-5 text-[11px] text-white/40 hidden sm:block">
        <div className="bg-[#1e1e2a]/50 px-3 py-1.5 rounded-full border border-white/5">
          <span>Agent: {currentAgent.name}</span>
        </div>
      </div>
    </div>
  )
}
