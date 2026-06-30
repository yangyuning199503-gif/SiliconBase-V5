import React from 'react';
import { motion } from 'framer-motion';
import { Eye } from 'lucide-react';

interface ObserverIndicatorProps {
  isActive: boolean;
}

export const ObserverIndicator: React.FC<ObserverIndicatorProps> = ({ isActive }) => {
  if (!isActive) return null;
  
  return (
    <motion.div
      initial={{ opacity: 0, y: -20, scale: 0.9 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -20, scale: 0.9 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className="fixed top-20 right-4 z-50"
    >
      <div className="glass-card px-4 py-2 rounded-full flex items-center gap-2 shadow-lg">
        <motion.div
          animate={{ scale: [1, 1.2, 1], opacity: [0.7, 1, 0.7] }}
          transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
        >
          <Eye className="w-5 h-5 text-sb-cyan" />
        </motion.div>
        <span className="text-sm text-white/80 font-medium">观察中</span>
        
        {/* 呼吸点指示器 */}
        <motion.div
          className="w-1.5 h-1.5 rounded-full bg-sb-cyan"
          animate={{ opacity: [0.3, 1, 0.3] }}
          transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
        />
      </div>
    </motion.div>
  );
};

export default ObserverIndicator;
