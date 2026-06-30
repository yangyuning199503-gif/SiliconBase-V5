/**
 * K 线图组件
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 使用 lightweight-charts 实现专业K线图
 * 支持 AI 交易标记、多时间周期
 */

import React, { useEffect, useRef, useCallback } from 'react'
import { createChart, IChartApi, ISeriesApi, CandlestickSeries, HistogramSeries, createSeriesMarkers, Time, CandlestickData, HistogramData } from 'lightweight-charts'
import { useTradingStore } from '../../stores/tradingStore'
import { authFetch } from '../../utils/api'

interface KLineChartProps {
  symbol: string
  interval?: string
}

const KLineChart: React.FC<KLineChartProps> = ({ symbol, interval = '1h' }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candlestickSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  
  const { klines, markers, setCurrentInterval, fetchKlines } = useTradingStore()
  const [isLoading, setIsLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  
  const intervals = [
    { value: '1m', label: '1分' },
    { value: '5m', label: '5分' },
    { value: '15m', label: '15分' },
    { value: '1h', label: '1小时' },
    { value: '4h', label: '4小时' },
    { value: '1d', label: '日线' },
  ]
  
  // 初始化时获取数据
  useEffect(() => {
    const loadData = async () => {
      setIsLoading(true)
      setError(null)
      try {
        await fetchKlines(symbol, interval)
      } catch (err) {
        setError('获取数据失败')
      } finally {
        setIsLoading(false)
      }
    }
    loadData()
  }, [symbol, interval, fetchKlines])

  // 初始化图表
  useEffect(() => {
    if (!chartContainerRef.current) return
    
    try {
    // 创建图表
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: '#0a0a0f' },
        textColor: '#8b8b8b',
      },
      grid: {
        vertLines: { color: '#1a1a2e' },
        horzLines: { color: '#1a1a2e' },
      },
      crosshair: {
        mode: 1,
        vertLine: {
          color: '#00d4ff',
          labelBackgroundColor: '#00d4ff',
        },
        horzLine: {
          color: '#00d4ff',
          labelBackgroundColor: '#00d4ff',
        },
      },
      rightPriceScale: {
        borderColor: '#1a1a2e',
      },
      timeScale: {
        borderColor: '#1a1a2e',
        timeVisible: true,
        secondsVisible: false,
      },
      width: chartContainerRef.current.clientWidth,
      height: 450,
    })
    
    // 创建K线系列
    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#00d084',
      downColor: '#ff4757',
      borderUpColor: '#00d084',
      borderDownColor: '#ff4757',
      wickUpColor: '#00d084',
      wickDownColor: '#ff4757',
    })
    
    // 创建成交量系列
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: '#26a69a',
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '',
    })
    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    })
    
    chartRef.current = chart
    candlestickSeriesRef.current = candlestickSeries
    volumeSeriesRef.current = volumeSeries
    
    // 处理窗口大小变化
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        })
      }
    }
    
    window.addEventListener('resize', handleResize)
    
    return () => {
      window.removeEventListener('resize', handleResize)
      try {
        chart.remove()
      } catch (e) {
        // 忽略清理错误
      }
    }
    } catch (err) {
      setError('图表初始化失败')
      console.error('Chart init error:', err)
    }
  }, [symbol])
  
  // 更新K线数据
  useEffect(() => {
    if (!candlestickSeriesRef.current || !volumeSeriesRef.current || klines.length === 0) return
    
    // 转换数据格式
    const candleData: CandlestickData<Time>[] = klines.map((k) => ({
      time: k.time as Time,
      open: k.open,
      high: k.high,
      low: k.low,
      close: k.close,
    }))
    
    const volumeData: HistogramData<Time>[] = klines.map((k) => ({
      time: k.time as Time,
      value: k.volume,
      color: k.close >= k.open ? '#00d084' : '#ff4757',
    }))
    
    candlestickSeriesRef.current.setData(candleData)
    volumeSeriesRef.current.setData(volumeData)
    
    // 调整视图
    chartRef.current?.timeScale().fitContent()
  }, [klines])
  
  // 更新标记
  useEffect(() => {
    if (!candlestickSeriesRef.current) return
    
    // 创建标记数据
    const chartMarkers = markers.map((marker) => ({
      time: marker.time as Time,
      position: (marker.type === 'buy' ? 'belowBar' : 'aboveBar') as 'belowBar' | 'aboveBar',
      color: marker.type === 'buy' ? '#00d084' : '#ff4757',
      shape: (marker.type === 'buy' ? 'arrowUp' : 'arrowDown') as 'arrowUp' | 'arrowDown',
      text: marker.source === 'ai' ? '🤖 AI' : marker.type === 'buy' ? '买入' : '卖出',
      size: 2,
      price: marker.price,
    }))
    
    if (candlestickSeriesRef.current) {
      createSeriesMarkers(candlestickSeriesRef.current, chartMarkers)
    }
  }, [markers])
  
  // 获取K线数据
  const loadKlines = async (sym: string, intv: string) => {
    try {
      const response = await authFetch(`/api/trading/klines/${sym}?interval=${intv}&limit=500`)
      if (response.ok) {
        const data = await response.json()
        useTradingStore.getState().setKlines(data)
      }
    } catch (error) {
      console.error('获取K线数据失败:', error)
    }
  }
  
  // 处理时间周期切换
  const handleIntervalChange = useCallback((newInterval: string) => {
    setCurrentInterval(newInterval)
    // 重新获取K线数据
    loadKlines(symbol, newInterval)
  }, [symbol, setCurrentInterval])
  
  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
      {/* 时间周期选择器 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-1">
          {intervals.map((intv) => (
            <button
              key={intv.value}
              onClick={() => handleIntervalChange(intv.value)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200
                         ${interval === intv.value
                           ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/30'
                           : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                         }`}
            >
              {intv.label}
            </button>
          ))}
        </div>
        
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <span>{symbol}/USDT</span>
          <span className="text-gray-600">|</span>
          <span>{klines.length} 条数据</span>
          {isLoading && <span className="text-blue-400">加载中...</span>}
        </div>
      </div>
      
      {/* 图表容器 */}
      <div 
        ref={chartContainerRef} 
        className="w-full rounded-lg overflow-hidden relative"
        style={{ height: '450px' }}
      >
        {error && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900/80">
            <div className="text-center">
              <div className="text-red-400 mb-2">⚠️ {error}</div>
              <button 
                onClick={() => loadKlines(symbol, interval)}
                className="px-4 py-2 bg-blue-600 rounded-lg text-white hover:bg-blue-500"
              >
                重试
              </button>
            </div>
          </div>
        )}
        {isLoading && klines.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900/50">
            <div className="text-center">
              <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
              <div className="text-gray-400">加载数据中...</div>
            </div>
          </div>
        )}
      </div>
      
      {/* 图例说明 */}
      <div className="flex items-center gap-6 mt-3 pt-3 border-t border-gray-700 text-xs">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-green-500 rounded-sm" />
          <span className="text-gray-400">上涨</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-red-500 rounded-sm" />
          <span className="text-gray-400">下跌</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-b-[10px] border-b-green-500" />
          <span className="text-gray-400">AI买入</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-t-[10px] border-t-red-500" />
          <span className="text-gray-400">AI卖出</span>
        </div>
      </div>
    </div>
  )
}

export default KLineChart
