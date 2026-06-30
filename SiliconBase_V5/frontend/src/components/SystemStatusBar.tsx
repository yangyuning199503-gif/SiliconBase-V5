import React, { useState, useEffect } from 'react';
import { Cpu, Wifi, Server } from 'lucide-react';

interface SystemStatusBarProps {}

export const SystemStatusBar: React.FC<SystemStatusBarProps> = () => {
  const [status, setStatus] = useState({
    isConnected: true,
    cpu: 0,
    memory: 0,
    backendStatus: 'online' as 'online' | 'offline' | 'busy'
  });

  useEffect(() => {
    const interval = setInterval(() => {
      setStatus(prev => ({
        ...prev,
        cpu: Math.floor(Math.random() * 30) + 10,
        memory: Math.floor(Math.random() * 40) + 20,
      }));
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="bg-slate-800/80 backdrop-blur-md border border-white/10 rounded-lg
                    flex items-center px-3 py-1.5 gap-4 text-xs shadow-lg">
      <div className="flex items-center gap-1.5">
        <div className={`w-2 h-2 rounded-full ${
          status.backendStatus === 'online' ? 'bg-green-500 animate-pulse' : 
          status.backendStatus === 'busy' ? 'bg-yellow-500' : 'bg-red-500'
        }`} />
        <span className="text-slate-300 capitalize">{status.backendStatus}</span>
      </div>
      
      <div className="flex items-center gap-1.5 text-slate-400">
        <Cpu className="w-3 h-3" />
        <span>{status.cpu}%</span>
      </div>
      
      <div className="flex items-center gap-1.5 text-slate-400">
        <Server className="w-3 h-3" />
        <span>{status.memory}%</span>
      </div>
      
      <div className="flex items-center gap-1.5 text-slate-400">
        <Wifi className="w-3 h-3" />
        <span>已连接</span>
      </div>
    </div>
  );
};
