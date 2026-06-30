/**
 * 生命状态图表组件
 * 
 * 使用 Canvas 展示三感指标的雷达图和趋势图
 */
import { useEffect, useRef } from 'react';

interface LifeStateChartProps {
  presence: number;
  competence: number;
  curiosity: number;
  history?: Array<{
    timestamp: string;
    presence: number;
    competence: number;
    curiosity: number;
  }>;
}

export function LifeStateRadarChart({ presence, competence, curiosity }: LifeStateChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // 设置画布尺寸
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const centerX = rect.width / 2;
    const centerY = rect.height / 2;
    const radius = Math.min(centerX, centerY) - 40;

    // 清空画布
    ctx.clearRect(0, 0, rect.width, rect.height);

    // 三角形三个顶点角度
    const angles = [-Math.PI / 2, Math.PI / 6, Math.PI * 5 / 6];
    
    // 绘制网格圈
    for (let i = 1; i <= 5; i++) {
      ctx.beginPath();
      const r = (radius / 5) * i;
      angles.forEach((angle, index) => {
        const x = centerX + Math.cos(angle) * r;
        const y = centerY + Math.sin(angle) * r;
        if (index === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      });
      ctx.closePath();
      ctx.strokeStyle = `rgba(255, 255, 255, ${0.1 + i * 0.05})`;
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // 绘制轴线
    angles.forEach((angle) => {
      ctx.beginPath();
      ctx.moveTo(centerX, centerY);
      ctx.lineTo(centerX + Math.cos(angle) * radius, centerY + Math.sin(angle) * radius);
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
      ctx.lineWidth = 1;
      ctx.stroke();
    });

    // 绘制数据区域
    const values = [presence, competence, curiosity];
    const colors = ['#00d4ff', '#00ff88', '#ffaa00'];
    const labels = ['存在感', '胜任感', '好奇心'];

    ctx.beginPath();
    values.forEach((value, index) => {
      const r = (value / 10) * radius;
      const x = centerX + Math.cos(angles[index]) * r;
      const y = centerY + Math.sin(angles[index]) * r;
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.closePath();
    ctx.fillStyle = 'rgba(0, 212, 255, 0.3)';
    ctx.fill();
    ctx.strokeStyle = '#00d4ff';
    ctx.lineWidth = 2;
    ctx.stroke();

    // 绘制数据点和标签
    values.forEach((value, index) => {
      const r = (value / 10) * radius;
      const x = centerX + Math.cos(angles[index]) * r;
      const y = centerY + Math.sin(angles[index]) * r;

      // 数据点
      ctx.beginPath();
      ctx.arc(x, y, 6, 0, Math.PI * 2);
      ctx.fillStyle = colors[index];
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 2;
      ctx.stroke();

      // 标签
      const labelR = radius + 25;
      const labelX = centerX + Math.cos(angles[index]) * labelR;
      const labelY = centerY + Math.sin(angles[index]) * labelR;
      
      ctx.font = '12px sans-serif';
      ctx.fillStyle = colors[index];
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(labels[index], labelX, labelY);
      
      // 数值
      ctx.font = 'bold 11px sans-serif';
      ctx.fillStyle = '#fff';
      ctx.fillText(String(value), labelX, labelY + 14);
    });
  }, [presence, competence, curiosity]);

  return (
    <div className="relative w-full h-64">
      <canvas
        ref={canvasRef}
        className="w-full h-full"
        style={{ width: '100%', height: '100%' }}
      />
    </div>
  );
}

/**
 * 生命状态趋势图
 */
export function LifeStateTrendChart({ history = [] }: { history?: LifeStateChartProps['history'] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || history.length < 2) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // 设置画布尺寸
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const padding = { top: 20, right: 20, bottom: 30, left: 30 };
    const chartWidth = rect.width - padding.left - padding.right;
    const chartHeight = rect.height - padding.top - padding.bottom;

    // 清空画布
    ctx.clearRect(0, 0, rect.width, rect.height);

    // 绘制网格
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
    ctx.lineWidth = 1;
    
    // Y轴网格线 (0-10)
    for (let i = 0; i <= 5; i++) {
      const y = padding.top + (chartHeight / 5) * i;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(padding.left + chartWidth, y);
      ctx.stroke();
      
      // Y轴标签
      ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(10 - i * 2), padding.left - 5, y);
    }

    // 绘制数据线
    const colors = {
      presence: '#00d4ff',
      competence: '#00ff88',
      curiosity: '#ffaa00'
    };

    const drawLine = (key: 'presence' | 'competence' | 'curiosity', color: string) => {
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      
      history.forEach((point, index) => {
        const x = padding.left + (index / (history.length - 1)) * chartWidth;
        const y = padding.top + chartHeight - (point[key] / 10) * chartHeight;
        
        if (index === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      });
      
      ctx.stroke();

      // 绘制数据点
      history.forEach((point, index) => {
        const x = padding.left + (index / (history.length - 1)) * chartWidth;
        const y = padding.top + chartHeight - (point[key] / 10) * chartHeight;
        
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
      });
    };

    drawLine('presence', colors.presence);
    drawLine('competence', colors.competence);
    drawLine('curiosity', colors.curiosity);

    // X轴标签（显示时间）
    const timeLabels = [0, Math.floor(history.length / 2), history.length - 1];
    timeLabels.forEach((index) => {
      const x = padding.left + (index / (history.length - 1)) * chartWidth;
      const timestamp = new Date(history[index].timestamp);
      const label = `${timestamp.getHours()}:${timestamp.getMinutes().toString().padStart(2, '0')}`;
      
      ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
      ctx.font = '9px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(label, x, padding.top + chartHeight + 5);
    });

  }, [history]);

  if (history.length < 2) {
    return (
      <div className="h-32 flex items-center justify-center text-white/40 text-sm">
        历史数据不足
      </div>
    );
  }

  return (
    <div className="relative w-full h-32">
      <canvas
        ref={canvasRef}
        className="w-full h-full"
        style={{ width: '100%', height: '100%' }}
      />
      {/* 图例 */}
      <div className="flex items-center justify-center gap-4 mt-2">
        {[
          { key: '存在感', color: '#00d4ff' },
          { key: '胜任感', color: '#00ff88' },
          { key: '好奇心', color: '#ffaa00' }
        ].map(item => (
          <div key={item.key} className="flex items-center gap-1">
            <div className="w-3 h-1 rounded" style={{ backgroundColor: item.color }} />
            <span className="text-xs text-white/50">{item.key}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default { LifeStateRadarChart, LifeStateTrendChart };
