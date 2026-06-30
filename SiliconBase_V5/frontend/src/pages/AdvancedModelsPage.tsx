import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { 
  Cpu, 
  Brain, 
  Volume2, 
  Download, 
  CheckCircle, 
  AlertCircle,
  HardDrive,
  Zap,
  Settings
} from 'lucide-react'
import { fetchAPI } from '../utils/api'
import { getAuthToken } from '../utils/auth'

// 模型信息接口
interface ModelInfo {
  id: string
  name: string
  description: string
  size: string
  sizeBytes: number
  category: string
  icon: any
  useCases: string[]
  enabled: boolean
  downloaded: boolean
  loaded: boolean
  device?: string
}

// 分类图标映射
const categoryIcons: Record<string, any> = {
  speech: Volume2,
  nlp: Brain,
  vad: Cpu
}

// 调用后端 /api/advanced-models 获取真实模型列表（统一走 fetchAPI）
const fetchModels = async (): Promise<ModelInfo[]> => {
  const data = await fetchAPI<ModelInfo[] | { models: ModelInfo[] }>('/api/advanced-models')
  const models = Array.isArray(data) ? data : (data.models || [])
  return models.map((model: any) => ({
    ...model,
    icon: categoryIcons[model.category] || Cpu,
    useCases: model.use_cases || []
  }))
}

const categoryLabels: Record<string, { label: string; color: string; bg: string }> = {
  speech: { label: '语音增强', color: 'text-blue-400', bg: 'bg-blue-500/10' },
  nlp: { label: '高级NLP', color: 'text-purple-400', bg: 'bg-purple-500/10' },
  vad: { label: '语音检测', color: 'text-green-400', bg: 'bg-green-500/10' }
}

export function AdvancedModelsPage() {
  const [models, setModels] = useState<ModelInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [downloading, setDownloading] = useState<string | null>(null)
  const [totalMemory, setTotalMemory] = useState(0)

  useEffect(() => {
    loadModels()
  }, [])

  const loadModels = async () => {
    setLoading(true)
    const data = await fetchModels()
    setModels(data)
    calculateMemory(data)
    setLoading(false)
  }

  const calculateMemory = (modelList: ModelInfo[]) => {
    const used = modelList
      .filter(m => m.loaded)
      .reduce((sum, m) => sum + m.sizeBytes, 0)
    setTotalMemory(used)
  }

  const handleToggle = async (modelId: string) => {
    const model = models.find(m => m.id === modelId)
    if (!model) return

    try {
      if (model.enabled) {
        // 禁用模型
        await fetchAPI(`/api/advanced-models/${modelId}/disable`, { method: 'POST' })
        setModels(prev => prev.map(m => 
          m.id === modelId ? { ...m, enabled: false, loaded: false } : m
        ))
      } else {
        // 启用模型
        if (!model.downloaded) {
          // 需要下载
          handleDownload(modelId)
          return
        }
        
        await fetchAPI(`/api/advanced-models/${modelId}/enable`, {
          method: 'POST',
          body: { auto_download: false }
        })
        setModels(prev => prev.map(m => 
          m.id === modelId ? { ...m, enabled: true } : m
        ))
      }
      
      calculateMemory(models)
    } catch (err) {
      console.error('[AdvancedModels] 切换模型失败:', err)
      alert(err instanceof Error ? err.message : '操作失败')
    }
  }

  const handleDownload = async (modelId: string) => {
    setDownloading(modelId)

    // SSE 无法携带 Authorization header，通过 query token 传递认证信息
    const token = getAuthToken()
    const eventSource = new EventSource(
      `/api/advanced-models/${modelId}/download-progress?token=${encodeURIComponent(token || '')}`
    )

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.status === 'complete') {
        setModels(prev => prev.map(m =>
          m.id === modelId ? { ...m, downloaded: true } : m
        ))
        setDownloading(null)
        eventSource.close()

        // 自动启用
        handleToggle(modelId)
      } else if (data.status === 'error') {
        setDownloading(null)
        eventSource.close()
        alert(data.message || '下载失败')
      }
    }

    eventSource.onerror = (err) => {
      console.error('[AdvancedModels] SSE连接错误:', err)
      setDownloading(null)
      eventSource.close()
      alert('下载进度连接失败')
    }

    // 开始下载
    try {
      await fetchAPI(`/api/advanced-models/${modelId}/download`, { method: 'POST' })
    } catch (err) {
      console.error('[AdvancedModels] 下载启动失败:', err)
      setDownloading(null)
      eventSource.close()
      alert(err instanceof Error ? err.message : '下载启动失败')
    }
  }

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-sb-cyan" />
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col p-6 space-y-6 overflow-auto">
      {/* 头部 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">高级模型管理</h1>
          <p className="text-sb-text-secondary mt-1">
            可选的高级AI模型，按需启用以提升能力
          </p>
        </div>
        
        {/* 内存使用 */}
        <div className="flex items-center gap-4 px-4 py-2 bg-sb-bg-secondary rounded-lg">
          <HardDrive className="w-5 h-5 text-sb-cyan" />
          <div>
            <div className="text-sm text-sb-text-secondary">内存使用</div>
            <div className="text-white font-mono">{formatBytes(totalMemory)}</div>
          </div>
        </div>
      </div>

      {/* 分类筛选 */}
      <div className="flex gap-2">
        {Object.entries(categoryLabels).map(([key, { label, color }]) => (
          <button
            key={key}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${color} bg-white/5 hover:bg-white/10`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* 模型列表 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {models.map((model) => {
          const Icon = model.icon
          const category = categoryLabels[model.category]
          
          return (
            <motion.div
              key={model.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className={`p-5 rounded-xl border transition-all ${
                model.enabled 
                  ? 'border-sb-cyan/50 bg-sb-cyan/5' 
                  : 'border-white/10 bg-sb-bg-secondary/30'
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-4">
                  {/* 图标 */}
                  <div className={`p-3 rounded-xl ${category.bg}`}>
                    <Icon className={`w-6 h-6 ${category.color}`} />
                  </div>
                  
                  {/* 信息 */}
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-lg font-semibold text-white">{model.name}</h3>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${category.bg} ${category.color}`}>
                        {category.label}
                      </span>
                    </div>
                    
                    <p className="text-sm text-sb-text-secondary mt-1 max-w-md">
                      {model.description}
                    </p>
                    
                    {/* 使用场景 */}
                    <div className="flex flex-wrap gap-2 mt-3">
                      {model.useCases.map((useCase, idx) => (
                        <span 
                          key={idx}
                          className="text-xs px-2 py-1 rounded bg-white/5 text-sb-text-secondary"
                        >
                          {useCase}
                        </span>
                      ))}
                    </div>
                    
                    {/* 大小 */}
                    <div className="flex items-center gap-4 mt-3 text-sm">
                      <span className="text-sb-text-secondary">
                        <HardDrive className="w-4 h-4 inline mr-1" />
                        {model.size}
                      </span>
                      
                      {/* 状态指示 */}
                      {model.loaded && (
                        <span className="text-green-400 flex items-center gap-1">
                          <Zap className="w-4 h-4" />
                          已加载
                        </span>
                      )}
                      {model.downloaded && !model.loaded && (
                        <span className="text-blue-400 flex items-center gap-1">
                          <CheckCircle className="w-4 h-4" />
                          已下载
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                
                {/* 操作按钮 */}
                <div className="flex flex-col items-end gap-2">
                  {/* 开关 */}
                  <button
                    onClick={() => handleToggle(model.id)}
                    disabled={downloading === model.id}
                    className={`relative w-14 h-7 rounded-full transition-colors ${
                      model.enabled ? 'bg-sb-cyan' : 'bg-white/20'
                    }`}
                  >
                    <div className={`absolute top-1 w-5 h-5 rounded-full bg-white transition-transform ${
                      model.enabled ? 'translate-x-7' : 'translate-x-1'
                    }`} />
                  </button>
                  
                  {/* 下载/状态 */}
                  {!model.downloaded && (
                    <button
                      onClick={() => handleDownload(model.id)}
                      disabled={downloading === model.id}
                      className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-blue-500/20 text-blue-400 text-sm hover:bg-blue-500/30 transition-colors disabled:opacity-50"
                    >
                      {downloading === model.id ? (
                        <>
                          <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                          下载中...
                        </>
                      ) : (
                        <>
                          <Download className="w-4 h-4" />
                          下载
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>
              
              {/* 警告信息 */}
              {model.id === 'w2v_bert' && model.enabled && (
                <div className="mt-4 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30">
                  <div className="flex items-start gap-2">
                    <AlertCircle className="w-5 h-5 text-yellow-400 flex-shrink-0 mt-0.5" />
                    <div className="text-sm">
                      <p className="text-yellow-400 font-medium">内存警告</p>
                      <p className="text-yellow-400/80">
                        此模型需要4.4GB内存，加载后可能影响系统性能。建议在16GB以上内存设备使用。
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </motion.div>
          )
        })}
      </div>
      
      {/* 底部提示 */}
      <div className="p-4 rounded-lg bg-white/5 border border-white/10">
        <div className="flex items-start gap-3">
          <Settings className="w-5 h-5 text-sb-cyan flex-shrink-0 mt-0.5" />
          <div className="text-sm text-sb-text-secondary">
            <p className="text-white font-medium mb-1">使用提示</p>
            <ul className="space-y-1 list-disc list-inside">
              <li>启用模型后会自动下载（首次使用）</li>
              <li>模型下载后可随时启用/禁用，无需重复下载</li>
              <li>内存不足时会自动卸载不常用的模型</li>
              <li>禁用的模型不会占用内存资源</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}
