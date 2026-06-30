import { useCallback } from 'react';

export const useAudioNotifications = () => {
  const playSound = useCallback((type: 'notification' | 'success' | 'error' = 'notification') => {
    try {
      const AudioContext = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioContext) return;
      
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      
      osc.connect(gain);
      gain.connect(ctx.destination);
      
      const frequency = type === 'success' ? 800 : type === 'error' ? 200 : 600;
      osc.frequency.value = frequency;
      gain.gain.value = 0.1;
      
      osc.start();
      osc.stop(ctx.currentTime + 0.1);
    } catch (error) {
      console.warn('Audio notification failed:', error);
    }
  }, []);

  return { playSound };
};
