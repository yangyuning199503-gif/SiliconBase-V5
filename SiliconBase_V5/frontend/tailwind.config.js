import scrollbar from 'tailwind-scrollbar'

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // 主色调 - 深色模式（调亮）
        'sb-bg': {
          primary: '#14141c',
          secondary: '#1e1e2a',
          card: 'rgba(35,35,48,0.95)',
        },
        // 强调色
        'sb-accent': {
          primary: '#00d4ff',   // 硅基蓝
          secondary: '#7b2cbf', // 神经紫
          success: '#00ff88',   // 成功绿
          warning: '#ffaa00',   // 警告橙
          error: '#ff3366',     // 错误红
        },
        // Agent颜色
        'sb-agent': {
          general: '#00d4ff',
          coder: '#00ff88',
          trading: '#ffaa00',
          creative: '#ff66cc',
          research: '#aa66ff',
        },
        // 快捷颜色
        'sb-cyan': '#00d4ff',
        'sb-cyan-hover': '#00b8e0',
        'sb-text-secondary': 'rgba(255,255,255,0.75)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['Fira Code', 'monospace'],
      },
      animation: {
        'breathe': 'breathe 3s ease-in-out infinite',
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'slide-up': 'slide-up 0.3s ease-out',
        'fade-in': 'fade-in 0.3s ease-out',
        'spin-slow': 'spin 3s linear infinite',
      },
      keyframes: {
        breathe: {
          '0%, 100%': { transform: 'scale(1)', boxShadow: '0 0 30px rgba(0, 212, 255, 0.5)' },
          '50%': { transform: 'scale(1.05)', boxShadow: '0 0 50px rgba(0, 212, 255, 0.8)' },
        },
        'pulse-glow': {
          '0%, 100%': { opacity: '0.5' },
          '50%': { opacity: '1' },
        },
        'slide-up': {
          from: { transform: 'translateY(20px)', opacity: '0' },
          to: { transform: 'translateY(0)', opacity: '1' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
      },
      backdropBlur: {
        xs: '2px',
      },
    },
  },
  plugins: [scrollbar],
}
