import React, { useState, useEffect } from 'react';
import { Activity, Cpu, MemoryStick, HardDrive, Network } from 'lucide-react';

interface SystemMetrics {
  cpu: number;
  memory: number;
  disk: number;
  network: number;
  activeTasks: number;
}

export const DashboardPanel: React.FC = () => {
  const [metrics, setMetrics] = useState<SystemMetrics>({
    cpu: 0,
    memory: 0,
    disk: 0,
    network: 0,
    activeTasks: 0
  });

  useEffect(() => {
    const interval = setInterval(() => {
      setMetrics({
        cpu: Math.floor(Math.random() * 40) + 10,
        memory: Math.floor(Math.random() * 30) + 20,
        disk: Math.floor(Math.random() * 20) + 5,
        network: Math.floor(Math.random() * 50) + 20,
        activeTasks: Math.floor(Math.random() * 5)
      });
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  const MetricCard = ({ icon: Icon, label, value, unit, color }: any) => (
    <div className="bg-slate-800/50 rounded-lg p-4 border border-white/5">
      <div className="flex items-center gap-3 mb-2">
        <Icon className={`w-5 h-5 ${color}`} />
        <span className="text-slate-400 text-sm">{label}</span>
      </div>
      <div className="text-2xl font-bold text-white">
        {value}<span className="text-sm text-slate-500 ml-1">{unit}</span>
      </div>
      <div className="mt-2 h-1 bg-slate-700 rounded-full overflow-hidden">
        <div 
          className={`h-full ${color.replace('text-', 'bg-')} transition-all duration-500`}
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  );

  return (
    <div className="p-6 bg-slate-900 rounded-xl border border-white/10">
      <h2 className="text-lg font-semibold flex items-center gap-2 mb-6 text-white">
        <Activity className="w-5 h-5 text-cyan-400" />
        系统监控
      </h2>
      
      <div className="grid grid-cols-2 gap-4">
        <MetricCard 
          icon={Cpu} 
          label="CPU 使用率" 
          value={metrics.cpu} 
          unit="%" 
          color="text-cyan-400"
        />
        <MetricCard 
          icon={MemoryStick} 
          label="内存使用" 
          value={metrics.memory} 
          unit="%" 
          color="text-purple-400"
        />
        <MetricCard 
          icon={HardDrive} 
          label="磁盘 IO" 
          value={metrics.disk} 
          unit="%" 
          color="text-green-400"
        />
        <MetricCard 
          icon={Network} 
          label="网络活动" 
          value={metrics.network} 
          unit="KB/s" 
          color="text-yellow-400"
        />
      </div>

      <div className="mt-4 p-3 bg-slate-800/30 rounded-lg">
        <span className="text-slate-400 text-sm">活跃任务: </span>
        <span className="text-white font-semibold">{metrics.activeTasks}</span>
      </div>
    </div>
  );
};
