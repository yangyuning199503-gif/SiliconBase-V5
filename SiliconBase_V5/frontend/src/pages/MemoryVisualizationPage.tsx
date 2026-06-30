/**
 * Memory Visualization Page - 记忆可视化页面
 *
 * 提供记忆流动图、关联图谱、统计数据等可视化功能
 *
 * @author Agent-9 (记忆可视化设计师)
 * @author Agent-9-Fix (可视化修复代理) - 修复WebSocket重连、移动端兼容、触摸事件
 * @version 1.1.0
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Activity,
  Brain,
  GitBranch,
  BarChart3,
  Clock,
  Layers,
  RefreshCw,
  Download,
  Maximize2,
  Minimize2,
  Play,
  Pause,
  Zap,
  Database,
  TrendingUp,
  Target,
} from "lucide-react";
import { fetchAPI } from "../utils/api";
import { getAuthUser } from "../utils/auth";
import { useNotifications } from "../hooks/useNotifications";
import { useQuery } from "@tanstack/react-query";
import { buildWsUrl } from "../config/api";

// ═══════════════════════════════════════════════════════════════════
// 常量定义
// ═══════════════════════════════════════════════════════════════════

/** 最大WebSocket重连次数 */
const MAX_RECONNECT_ATTEMPTS = 10;
/** 基础重连延迟(ms) */
const BASE_RECONNECT_DELAY = 1000;
/** 最大重连延迟(ms) */
const MAX_RECONNECT_DELAY = 30000;

// ═══════════════════════════════════════════════════════════════════
// 类型定义
// ═══════════════════════════════════════════════════════════════════

interface MemoryFlowItem {
  id: string;
  type: "input" | "output" | "transform";
  content: string;
  layer: string;
  timestamp: string;
  metadata: Record<string, any>;
}

interface MemoryFlowData {
  inputs: MemoryFlowItem[];
  outputs: MemoryFlowItem[];
  transforms: MemoryFlowItem[];
  timeline: any[];
}

interface MemoryNode {
  id: string;
  label: string;
  layer: string;
  type: string;
  size: number;
  color: string;
  x?: number;
  y?: number;
}

interface MemoryEdge {
  source: string;
  target: string;
  weight: number;
  type: string;
}

interface MemoryGraphData {
  nodes: MemoryNode[];
  edges: MemoryEdge[];
}

interface LayerDistribution {
  L1: number;
  L2: number;
  L3: number;
  L4: number;
  L5: number;
}

interface SourceDistribution {
  AI: number;
  system: number;
  user: number;
  tool: number;
}

interface DailyGrowth {
  date: string;
  count: number;
  layer: string;
}

interface MemoryStats {
  layer_distribution: LayerDistribution;
  source_distribution: SourceDistribution;
  daily_growth: DailyGrowth[];
  retention_rate: number;
  total_memories: number;
  active_memories: number;
}

/**
 * 检测设备类型的Hook
 */
const useDeviceType = () => {
  const [isMobile, setIsMobile] = useState(false);
  const [isTablet, setIsTablet] = useState(false);

  useEffect(() => {
    const checkDevice = () => {
      const width = window.innerWidth;
      setIsMobile(width < 768);
      setIsTablet(width >= 768 && width < 1024);
    };

    checkDevice();
    window.addEventListener("resize", checkDevice);
    return () => window.removeEventListener("resize", checkDevice);
  }, []);

  return { isMobile, isTablet };
};

// ═══════════════════════════════════════════════════════════════════
// 子组件
// ═══════════════════════════════════════════════════════════════════

/**
 * 记忆流动图（Sankey风格）
 */
const MemoryFlowChart: React.FC<{
  data: MemoryFlowData;
  isPlaying: boolean;
  isMobile: boolean;
}> = ({ data, isPlaying, isMobile }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number>(0);
  const particlesRef = useRef<
    Array<{
      x: number;
      y: number;
      vx: number;
      vy: number;
      life: number;
      color: string;
    }>
  >([]);

  // 绘制流动动画
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // ✅ 使用ResizeObserver监听容器尺寸变化
    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          canvas.width = width * window.devicePixelRatio;
          canvas.height = height * window.devicePixelRatio;
          ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
        }
      }
    });

    // 监听canvas的父元素
    const parent = canvas.parentElement;
    if (parent) {
      resizeObserver.observe(parent);
    }

    let lastTime = 0;
    const animate = (time: number) => {
      if (time - lastTime < 33) {
        // ~30fps
        animationRef.current = requestAnimationFrame(animate);
        return;
      }
      lastTime = time;

      const width = canvas.offsetWidth;
      const height = canvas.offsetHeight;

      ctx.clearRect(0, 0, width, height);

      // 绘制三个区域
      const sectionWidth = width / 3;
      const colors = {
        input: "#00d4ff",
        transform: "#ffaa00",
        output: "#00ff88",
      };

      // 绘制区域背景
      ctx.fillStyle = "rgba(0, 212, 255, 0.05)";
      ctx.fillRect(0, 0, sectionWidth, height);
      ctx.fillStyle = "rgba(255, 170, 0, 0.05)";
      ctx.fillRect(sectionWidth, 0, sectionWidth, height);
      ctx.fillStyle = "rgba(0, 255, 136, 0.05)";
      ctx.fillRect(sectionWidth * 2, 0, sectionWidth, height);

      // 绘制分隔线
      ctx.strokeStyle = "rgba(255, 255, 255, 0.1)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(sectionWidth, 0);
      ctx.lineTo(sectionWidth, height);
      ctx.moveTo(sectionWidth * 2, 0);
      ctx.lineTo(sectionWidth * 2, height);
      ctx.stroke();

      // 绘制标题
      ctx.font = isMobile ? "11px sans-serif" : "14px sans-serif";
      ctx.fillStyle = colors.input;
      ctx.textAlign = "center";
      ctx.fillText(`新增记忆 (${data.inputs.length})`, sectionWidth / 2, 30);
      ctx.fillStyle = colors.transform;
      ctx.fillText(
        `转换/升级 (${data.transforms.length})`,
        sectionWidth * 1.5,
        30,
      );
      ctx.fillStyle = colors.output;
      ctx.fillText(
        `检索/输出 (${data.outputs.length})`,
        sectionWidth * 2.5,
        30,
      );

      // 绘制最近的项目
      const maxItems = isMobile ? 5 : 8;
      const itemHeight = isMobile ? 50 : 45;

      const drawItems = (items: MemoryFlowItem[], x: number, color: string) => {
        items.slice(0, maxItems).forEach((item, i) => {
          const y = 60 + i * itemHeight;

          // 绘制节点
          ctx.beginPath();
          ctx.arc(x, y, isMobile ? 5 : 6, 0, Math.PI * 2);
          ctx.fillStyle = color;
          ctx.fill();

          // 绘制内容
          ctx.fillStyle = "rgba(255, 255, 255, 0.7)";
          ctx.font = isMobile ? "10px sans-serif" : "11px sans-serif";
          ctx.textAlign = "left";
          const maxLen = isMobile ? 12 : 20;
          const content =
            item.content.slice(0, maxLen) +
            (item.content.length > maxLen ? "..." : "");
          ctx.fillText(content, x + 15, y + 4);

          // 绘制层级标签
          ctx.fillStyle = "rgba(255, 255, 255, 0.4)";
          ctx.font = isMobile ? "8px sans-serif" : "9px sans-serif";
          ctx.fillText(item.layer, x + 15, y + 16);
        });
      };

      drawItems(data.inputs, sectionWidth / 2, colors.input);
      drawItems(data.transforms, sectionWidth * 1.5, colors.transform);
      drawItems(data.outputs, sectionWidth * 2.5, colors.output);

      // 动画粒子
      if (isPlaying) {
        // 生成新粒子
        if (Math.random() < 0.1) {
          const sourceSection = Math.floor(Math.random() * 2); // 0: input->transform, 1: transform->output
          particlesRef.current.push({
            x: sourceSection === 0 ? sectionWidth : sectionWidth * 2,
            y: 60 + Math.random() * (height - 100),
            vx: (sourceSection === 0 ? sectionWidth : sectionWidth) / 60,
            vy: (Math.random() - 0.5) * 0.5,
            life: 60,
            color: sourceSection === 0 ? colors.input : colors.transform,
          });
        }

        // 更新和绘制粒子
        particlesRef.current = particlesRef.current.filter((p) => {
          p.x += p.vx;
          p.y += p.vy;
          p.life--;

          if (p.life > 0) {
            ctx.beginPath();
            ctx.arc(p.x, p.y, isMobile ? 2 : 3, 0, Math.PI * 2);
            ctx.fillStyle = p.color;
            ctx.globalAlpha = p.life / 60;
            ctx.fill();
            ctx.globalAlpha = 1;
            return true;
          }
          return false;
        });
      }

      animationRef.current = requestAnimationFrame(animate);
    };

    animate(0);

    return () => {
      resizeObserver.disconnect();
      cancelAnimationFrame(animationRef.current);
    };
  }, [data, isPlaying, isMobile]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full"
      style={{ imageRendering: "crisp-edges" }}
    />
  );
};

/**
 * 力导向关联图谱 - 支持触摸事件
 */
const MemoryGraphCanvas: React.FC<{
  data: MemoryGraphData;
  selectedNode: string | null;
  onNodeSelect: (id: string) => void;
  isMobile: boolean;
}> = ({ data, selectedNode, onNodeSelect, isMobile }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nodesRef = useRef<MemoryNode[]>([]);
  const animationRef = useRef<number>(0);
  const dragRef = useRef<{
    node: MemoryNode | null;
    offsetX: number;
    offsetY: number;
  }>({ node: null, offsetX: 0, offsetY: 0 });
  const touchDragRef = useRef<{
    node: MemoryNode | null;
    offsetX: number;
    offsetY: number;
  }>({ node: null, offsetX: 0, offsetY: 0 });

  useEffect(() => {
    // 初始化节点位置
    const initialX = isMobile ? 150 : 400;
    const initialY = isMobile ? 200 : 300;
    const radius = isMobile ? 80 : 200;

    nodesRef.current = data.nodes.map((node, i) => ({
      ...node,
      x:
        node.x ||
        initialX + Math.cos((i * 2 * Math.PI) / data.nodes.length) * radius,
      y:
        node.y ||
        initialY + Math.sin((i * 2 * Math.PI) / data.nodes.length) * radius,
    }));
  }, [data.nodes, isMobile]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const resize = () => {
      canvas.width = canvas.offsetWidth * window.devicePixelRatio;
      canvas.height = canvas.offsetHeight * window.devicePixelRatio;
      ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    };
    resize();
    window.addEventListener("resize", resize);

    // ═══════════════════════════════════════════════════════════════════
    // 鼠标事件处理
    // ═══════════════════════════════════════════════════════════════════
    const handleMouseDown = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      // 查找点击的节点
      for (const node of nodesRef.current) {
        const dx = x - (node.x || 0);
        const dy = y - (node.y || 0);
        if (dx * dx + dy * dy < 100) {
          dragRef.current.node = node;
          dragRef.current.offsetX = dx;
          dragRef.current.offsetY = dy;
          onNodeSelect(node.id);
          break;
        }
      }
    };

    const handleMouseMove = (e: MouseEvent) => {
      if (dragRef.current.node) {
        const rect = canvas.getBoundingClientRect();
        dragRef.current.node.x =
          e.clientX - rect.left - dragRef.current.offsetX;
        dragRef.current.node.y = e.clientY - rect.top - dragRef.current.offsetY;
      }
    };

    const handleMouseUp = () => {
      dragRef.current.node = null;
    };

    // ═══════════════════════════════════════════════════════════════════
    // 触摸事件处理
    // ═══════════════════════════════════════════════════════════════════
    const handleTouchStart = (e: TouchEvent) => {
      e.preventDefault(); // 防止滚动
      const touch = e.touches[0];
      const rect = canvas.getBoundingClientRect();
      const x = touch.clientX - rect.left;
      const y = touch.clientY - rect.top;

      // 查找点击的节点
      for (const node of nodesRef.current) {
        const dx = x - (node.x || 0);
        const dy = y - (node.y || 0);
        if (dx * dx + dy * dy < (isMobile ? 400 : 100)) {
          // 移动端增大触摸区域
          touchDragRef.current.node = node;
          touchDragRef.current.offsetX = dx;
          touchDragRef.current.offsetY = dy;
          onNodeSelect(node.id);
          break;
        }
      }
    };

    const handleTouchMove = (e: TouchEvent) => {
      e.preventDefault(); // 防止滚动
      if (touchDragRef.current.node) {
        const touch = e.touches[0];
        const rect = canvas.getBoundingClientRect();
        touchDragRef.current.node.x =
          touch.clientX - rect.left - touchDragRef.current.offsetX;
        touchDragRef.current.node.y =
          touch.clientY - rect.top - touchDragRef.current.offsetY;
      }
    };

    const handleTouchEnd = () => {
      touchDragRef.current.node = null;
    };

    // ═══════════════════════════════════════════════════════════════════
    // 事件监听绑定
    // ═══════════════════════════════════════════════════════════════════
    canvas.addEventListener("mousedown", handleMouseDown);
    canvas.addEventListener("mousemove", handleMouseMove);
    canvas.addEventListener("mouseup", handleMouseUp);
    canvas.addEventListener("mouseleave", handleMouseUp);

    // 触摸事件
    canvas.addEventListener("touchstart", handleTouchStart, { passive: false });
    canvas.addEventListener("touchmove", handleTouchMove, { passive: false });
    canvas.addEventListener("touchend", handleTouchEnd);
    canvas.addEventListener("touchcancel", handleTouchEnd);

    // 力导向模拟
    let lastTime = 0;
    const animate = (time: number) => {
      if (time - lastTime < 33) {
        animationRef.current = requestAnimationFrame(animate);
        return;
      }
      lastTime = time;

      const width = canvas.offsetWidth;
      const height = canvas.offsetHeight;

      ctx.clearRect(0, 0, width, height);

      // 绘制边
      ctx.strokeStyle = "rgba(255, 255, 255, 0.15)";
      ctx.lineWidth = 1;
      for (const edge of data.edges) {
        const source = nodesRef.current.find((n) => n.id === edge.source);
        const target = nodesRef.current.find((n) => n.id === edge.target);
        if (source && target && source.x && source.y && target.x && target.y) {
          ctx.beginPath();
          ctx.moveTo(source.x, source.y);
          ctx.lineTo(target.x, target.y);
          ctx.stroke();
        }
      }

      // 简单的力导向更新
      if (!dragRef.current.node && !touchDragRef.current.node) {
        for (const node of nodesRef.current) {
          if (!node.x || !node.y) continue;

          // 向中心引力
          const centerX = width / 2;
          const centerY = height / 2;
          const dx = centerX - node.x;
          const dy = centerY - node.y;
          node.x += dx * 0.001;
          node.y += dy * 0.001;

          // 节点间斥力
          for (const other of nodesRef.current) {
            if (node === other || !other.x || !other.y) continue;
            const odx = node.x - other.x;
            const ody = node.y - other.y;
            const dist = Math.sqrt(odx * odx + ody * ody);
            if (dist < 100 && dist > 0) {
              const force = ((100 - dist) / dist) * 0.5;
              node.x += odx * force;
              node.y += ody * force;
            }
          }
        }
      }

      // 绘制节点
      for (const node of nodesRef.current) {
        if (!node.x || !node.y) continue;

        const isSelected = selectedNode === node.id;
        const radius = (isMobile ? 6 : 8) + node.size * (isMobile ? 1.5 : 2);

        // 选中光环
        if (isSelected) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, radius + (isMobile ? 6 : 8), 0, Math.PI * 2);
          ctx.fillStyle = "rgba(255, 255, 255, 0.2)";
          ctx.fill();
        }

        // 节点本体
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
        ctx.fillStyle = node.color;
        ctx.fill();

        // 边框
        ctx.strokeStyle = isSelected ? "#ffffff" : "rgba(255, 255, 255, 0.3)";
        ctx.lineWidth = isSelected ? 2 : 1;
        ctx.stroke();

        // 标签
        ctx.fillStyle = "rgba(255, 255, 255, 0.8)";
        ctx.font = isMobile ? "9px sans-serif" : "10px sans-serif";
        ctx.textAlign = "center";
        const labelMaxLen = isMobile ? 10 : 15;
        ctx.fillText(
          node.label.slice(0, labelMaxLen),
          node.x,
          node.y + radius + (isMobile ? 12 : 15),
        );
      }

      animationRef.current = requestAnimationFrame(animate);
    };

    animate(0);

    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(animationRef.current);
      canvas.removeEventListener("mousedown", handleMouseDown);
      canvas.removeEventListener("mousemove", handleMouseMove);
      canvas.removeEventListener("mouseup", handleMouseUp);
      canvas.removeEventListener("mouseleave", handleMouseUp);
      canvas.removeEventListener("touchstart", handleTouchStart);
      canvas.removeEventListener("touchmove", handleTouchMove);
      canvas.removeEventListener("touchend", handleTouchEnd);
      canvas.removeEventListener("touchcancel", handleTouchEnd);
    };
  }, [data.edges, selectedNode, onNodeSelect, isMobile]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full cursor-move touch-none"
      style={{ imageRendering: "crisp-edges", touchAction: "none" }}
    />
  );
};

/**
 * 层级分布饼图
 */
const LayerDistributionChart: React.FC<{
  data: LayerDistribution;
  isMobile: boolean;
}> = ({ data, isMobile }) => {
  const total = data.L1 + data.L2 + data.L3 + data.L4 + data.L5;

  // 【Phase 5修复】更新层级标签，L1改为"工作"
  const layers = [
    { label: isMobile ? "L1" : "L1 工作", value: data.L1, color: "#00d4ff" },
    { label: isMobile ? "L2" : "L2 短期", value: data.L2, color: "#00ff88" },
    { label: isMobile ? "L3" : "L3 中期", value: data.L3, color: "#ffaa00" },
    { label: isMobile ? "L4" : "L4 长期", value: data.L4, color: "#ff00ff" },
    { label: isMobile ? "L5" : "L5 执行", value: data.L5, color: "#ff5555" },
  ];

  let currentAngle = 0;

  const svgSize = isMobile ? 100 : 150;
  const viewBoxSize = 100;
  const pieRadius = 40;
  const centerRadius = 20;

  return (
    <div
      className={`flex items-center gap-4 ${isMobile ? "flex-col" : "gap-6"}`}
    >
      <svg
        width={svgSize}
        height={svgSize}
        viewBox={`0 0 ${viewBoxSize} ${viewBoxSize}`}
      >
        {layers.map((layer, i) => {
          if (layer.value === 0) return null;
          const angle = (layer.value / total) * 2 * Math.PI;
          const x1 = 50 + pieRadius * Math.cos(currentAngle);
          const y1 = 50 + pieRadius * Math.sin(currentAngle);
          const x2 = 50 + pieRadius * Math.cos(currentAngle + angle);
          const y2 = 50 + pieRadius * Math.sin(currentAngle + angle);
          const largeArc = angle > Math.PI ? 1 : 0;

          const path = `M 50 50 L ${x1} ${y1} A ${pieRadius} ${pieRadius} 0 ${largeArc} 1 ${x2} ${y2} Z`;
          const element = (
            <path
              key={i}
              d={path}
              fill={layer.color}
              stroke="rgba(0,0,0,0.3)"
              strokeWidth="0.5"
            />
          );
          currentAngle += angle;
          return element;
        })}
        <circle cx="50" cy="50" r={centerRadius} fill="#1a1a2e" />
        <text
          x="50"
          y="50"
          textAnchor="middle"
          dominantBaseline="middle"
          fill="white"
          fontSize={isMobile ? 10 : 12}
        >
          {total}
        </text>
      </svg>

      <div
        className={`space-y-1 ${isMobile ? "grid grid-cols-2 gap-x-4 gap-y-1" : ""}`}
      >
        {layers.map((layer, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <div
              className="w-3 h-3 rounded"
              style={{ backgroundColor: layer.color }}
            />
            <span className={`text-white/70 ${isMobile ? "w-8" : "w-16"}`}>
              {layer.label}
            </span>
            <span className="text-white font-medium">{layer.value}</span>
            <span className="text-white/40">
              {total > 0
                ? `(${((layer.value / total) * 100).toFixed(isMobile ? 0 : 1)}%)`
                : "(0%)"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

/**
 * 增长趋势折线图
 */
const GrowthTrendChart: React.FC<{
  data: DailyGrowth[];
  isMobile: boolean;
}> = ({ data, isMobile }) => {
  if (data.length === 0) {
    return (
      <div
        className={`flex items-center justify-center text-white/40 text-sm ${isMobile ? "h-24" : "h-32"}`}
      >
        暂无数据
      </div>
    );
  }

  // 按日期聚合
  const dailyCounts: Record<string, number> = {};
  data.forEach((d) => {
    dailyCounts[d.date] = (dailyCounts[d.date] || 0) + d.count;
  });

  const sortedDates = Object.keys(dailyCounts).sort().slice(-14); // 最近14天
  const maxCount = Math.max(...Object.values(dailyCounts), 1);

  const points = sortedDates
    .map((date, i) => {
      const x = (i / (sortedDates.length - 1 || 1)) * 100;
      const y = 100 - (dailyCounts[date] / maxCount) * 100;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div className={isMobile ? "h-24" : "h-32"}>
      <svg
        width="100%"
        height="100%"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
      >
        {/* 网格线 */}
        <line x1="0" y1="25" x2="100" y2="25" stroke="rgba(255,255,255,0.05)" />
        <line x1="0" y1="50" x2="100" y2="50" stroke="rgba(255,255,255,0.05)" />
        <line x1="0" y1="75" x2="100" y2="75" stroke="rgba(255,255,255,0.05)" />

        {/* 折线 */}
        <polyline
          points={points}
          fill="none"
          stroke="#00d4ff"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />

        {/* 数据点 */}
        {sortedDates.map((date, i) => {
          const x = (i / (sortedDates.length - 1 || 1)) * 100;
          const y = 100 - (dailyCounts[date] / maxCount) * 100;
          return (
            <circle
              key={i}
              cx={x}
              cy={y}
              r={isMobile ? 1 : 1.5}
              fill="#00d4ff"
            />
          );
        })}
      </svg>

      {/* X轴标签 */}
      <div className="flex justify-between text-[10px] text-white/40 mt-1">
        {sortedDates
          .filter((_, i) => i % 3 === 0)
          .map((date, i) => (
            <span key={i}>{date.slice(5)}</span>
          ))}
      </div>
    </div>
  );
};

/**
 * 实时注入监控
 */
const RealtimeMonitor: React.FC<{ updates: any[]; isMobile: boolean }> = ({
  updates,
  isMobile,
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [updates]);

  return (
    <div ref={scrollRef} className="h-full overflow-auto space-y-2">
      <AnimatePresence>
        {updates.length === 0 ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-center text-white/40 py-8 text-sm"
          >
            等待记忆更新...
          </motion.div>
        ) : (
          updates.slice(0, 20).map((update, i) => (
            <motion.div
              key={update.id || i}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0 }}
              className="p-2 rounded bg-white/5 border border-white/10 text-xs"
            >
              <div className="flex items-center justify-between mb-1">
                <span
                  className={`px-1.5 py-0.5 rounded text-[10px] ${
                    update.change_type === "add"
                      ? "bg-green-500/20 text-green-400"
                      : update.change_type === "update"
                        ? "bg-yellow-500/20 text-yellow-400"
                        : "bg-red-500/20 text-red-400"
                  }`}
                >
                  {update.change_type === "add"
                    ? "新增"
                    : update.change_type === "update"
                      ? "更新"
                      : "删除"}
                </span>
                <span className="text-white/40">
                  {new Date(update.timestamp).toLocaleTimeString()}
                </span>
              </div>
              <div className="text-white/70 truncate">
                {update.memory?.content?.slice(0, isMobile ? 30 : 50) ||
                  "No content"}
              </div>
            </motion.div>
          ))
        )}
      </AnimatePresence>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════
// 主组件
// ═══════════════════════════════════════════════════════════════════

export function MemoryVisualizationPage() {
  // 通知 hook
  const { showNotification } = useNotifications();

  // 设备类型检测
  const { isMobile } = useDeviceType();

  // 状态
  const [activeTab, setActiveTab] = useState<"flow" | "graph" | "stats">(
    "flow",
  );
  const [timeRange, setTimeRange] = useState<"1h" | "24h" | "7d" | "30d">(
    "24h",
  );
  const [isPlaying, setIsPlaying] = useState(true);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // 数据状态
  const [flowData, setFlowData] = useState<MemoryFlowData>({
    inputs: [],
    outputs: [],
    transforms: [],
    timeline: [],
  });
  const [graphData, setGraphData] = useState<MemoryGraphData>({
    nodes: [],
    edges: [],
  });
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [realtimeUpdates, setRealtimeUpdates] = useState<any[]>([]);

  // 加载状态
  const [loading, setLoading] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectCountRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);

  // 获取流动数据
  const fetchFlowData = useCallback(async () => {
    try {
      // 【Phase 5修复】添加X-Session-Id header以支持用户ID统一
      const user = getAuthUser();
      const headers: Record<string, string> = {};
      if (user?.user_id) {
        headers["X-Session-Id"] = `user_${user.user_id}`;
      }

      const data = await fetchAPI<MemoryFlowData>(
        `/api/memories/viz/flow?time_range=${timeRange}`,
        {
          headers,
        },
      );
      setFlowData(data);
    } catch (error) {
      console.error("[MemoryVisualizationPage] 获取流动数据失败:", error);
      showNotification({
        type: "error",
        title: "数据加载失败",
        message: `获取记忆流动数据失败: ${error instanceof Error ? error.message : "未知错误"}`,
        duration: 5000,
      });
    }
  }, [timeRange, showNotification]);

  // 获取图谱数据
  const fetchGraphData = useCallback(async () => {
    try {
      // 【Phase 5修复】添加X-Session-Id header以支持用户ID统一
      const user = getAuthUser();
      const headers: Record<string, string> = {};
      if (user?.user_id) {
        headers["X-Session-Id"] = `user_${user.user_id}`;
      }

      const data = await fetchAPI<MemoryGraphData>(
        `/api/memories/viz/graph?layer=all`,
        {
          headers,
        },
      );
      setGraphData(data);
    } catch (error) {
      console.error("[MemoryVisualizationPage] 获取图谱数据失败:", error);
      showNotification({
        type: "error",
        title: "数据加载失败",
        message: `获取记忆图谱数据失败: ${error instanceof Error ? error.message : "未知错误"}`,
        duration: 5000,
      });
    }
  }, [showNotification]);

  // 获取统计数据
  const fetchStats = useCallback(async () => {
    try {
      // 【Phase 5修复】添加X-Session-Id header以支持用户ID统一
      const user = getAuthUser();
      const headers: Record<string, string> = {};
      if (user?.user_id) {
        headers["X-Session-Id"] = `user_${user.user_id}`;
      }

      const data = await fetchAPI<MemoryStats>(`/api/memories/viz/stats`, {
        headers,
      });
      setStats(data);
    } catch (error) {
      console.error("[MemoryVisualizationPage] 获取统计数据失败:", error);
      showNotification({
        type: "error",
        title: "数据加载失败",
        message: `获取记忆统计数据失败: ${error instanceof Error ? error.message : "未知错误"}`,
        duration: 5000,
      });
    }
  }, [showNotification]);

  // 加载所有数据
  const loadAllData = useCallback(async () => {
    setLoading(true);
    await Promise.all([fetchFlowData(), fetchGraphData(), fetchStats()]);
    setLoading(false);
  }, [fetchFlowData, fetchGraphData, fetchStats]);

  // 条件轮询
  useQuery({
    queryKey: ["memoryViz", activeTab],
    queryFn: () => {
      if (activeTab === "flow") return fetchFlowData();
      if (activeTab === "stats") return fetchStats();
      return Promise.resolve();
    },
    refetchInterval: 30000,
    enabled: activeTab === "flow" || activeTab === "stats",
  });

  // 初始化
  useEffect(() => {
    loadAllData();
  }, [loadAllData, activeTab]);

  // ═══════════════════════════════════════════════════════════════════
  // WebSocket连接 - 指数退避重连
  // ═══════════════════════════════════════════════════════════════════
  useEffect(() => {
    const connectWebSocket = () => {
      const user = JSON.parse(localStorage.getItem("silicon_user") || "{}");
      if (!user.user_id) {
        console.log("[MemoryViz] 用户未登录，跳过WebSocket连接");
        return;
      }

      // 如果已有连接，先关闭
      if (wsRef.current) {
        wsRef.current.close();
      }

      const token = localStorage.getItem("silicon_token");
      const wsUrl = `${buildWsUrl("/ws/memory-sync")}${token ? `?token=${token}` : ""}`;
      console.log(
        `[MemoryViz] 正在连接WebSocket... (重连次数: ${reconnectCountRef.current})`,
      );

      try {
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          console.log("[MemoryViz] WebSocket已连接");
          reconnectCountRef.current = 0; // 重置重连计数
          ws.send(JSON.stringify({ action: "subscribe" }));
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === "memory_update") {
              setRealtimeUpdates((prev) => [data.data, ...prev].slice(0, 50));
            }
          } catch (e) {
            console.error("解析WebSocket消息失败:", e);
          }
        };

        ws.onerror = (error) => {
          console.error("[MemoryViz] WebSocket错误:", error);
        };

        ws.onclose = (event) => {
          console.log(
            `[MemoryViz] WebSocket已断开 (code: ${event.code}, reason: ${event.reason})`,
          );

          // 清理当前连接
          wsRef.current = null;

          // 检查是否达到最大重连次数
          if (reconnectCountRef.current >= MAX_RECONNECT_ATTEMPTS) {
            console.log("[MemoryViz] 达到最大重连次数，停止重连");
            return;
          }

          // 计算指数退避延迟
          const delay = Math.min(
            BASE_RECONNECT_DELAY * Math.pow(2, reconnectCountRef.current),
            MAX_RECONNECT_DELAY,
          );

          console.log(`[MemoryViz] 将在 ${delay}ms 后重连...`);

          reconnectCountRef.current++;

          // 清除之前的定时器
          if (reconnectTimerRef.current) {
            window.clearTimeout(reconnectTimerRef.current);
          }

          reconnectTimerRef.current = window.setTimeout(() => {
            connectWebSocket();
          }, delay);
        };

        wsRef.current = ws;
      } catch (error) {
        console.error("[MemoryViz] WebSocket连接失败:", error);
      }
    };

    connectWebSocket();

    return () => {
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  // 导出数据
  const handleExport = () => {
    const data = {
      flow: flowData,
      graph: graphData,
      stats: stats,
      exported_at: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `memory-visualization-${Date.now()}.json`;
    a.click();
  };

  return (
    <div
      className={`flex flex-col bg-sb-bg-primary ${isFullscreen ? "fixed inset-0 z-50" : "h-full"}`}
    >
      {/* ═══════════════════════════════════════════════════════════════════
          顶部工具栏 - 响应式布局
          ═══════════════════════════════════════════════════════════════════ */}
      <div className="p-2 md:p-4 border-b border-white/10 flex flex-col md:flex-row md:items-center gap-2 md:gap-4">
        {/* 左侧标题和标签页 */}
        <div className="flex items-center gap-2 md:gap-4">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 md:w-5 md:h-5 text-sb-cyan" />
            <h1 className="text-base md:text-lg font-bold text-white">
              记忆可视化
            </h1>
          </div>

          {/* 标签页切换 - 移动端滚动 */}
          <div className="flex-1 overflow-x-auto">
            <div className="flex items-center gap-1 bg-white/5 rounded-lg p-1 min-w-fit">
              {[
                {
                  id: "flow",
                  label: isMobile ? "流动" : "流动图",
                  icon: GitBranch,
                },
                {
                  id: "graph",
                  label: isMobile ? "图谱" : "关联图谱",
                  icon: Database,
                },
                { id: "stats", label: "统计", icon: BarChart3 },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as any)}
                  className={`flex items-center gap-1 px-2 md:px-3 py-1.5 rounded text-xs md:text-sm transition-colors whitespace-nowrap ${
                    activeTab === tab.id
                      ? "bg-sb-cyan text-sb-bg-primary"
                      : "text-white/70 hover:text-white hover:bg-white/5"
                  }`}
                >
                  <tab.icon className="w-3 h-3 md:w-4 md:h-4" />
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* 右侧工具按钮 */}
        <div className="flex items-center gap-1 md:gap-2">
          {/* 时间范围选择 */}
          {activeTab === "flow" && (
            <select
              value={timeRange}
              onChange={(e) => setTimeRange(e.target.value as any)}
              className="bg-white/5 border border-white/10 rounded px-2 py-1 text-xs md:text-sm text-white"
            >
              <option value="1h">{isMobile ? "1h" : "最近1小时"}</option>
              <option value="24h">{isMobile ? "24h" : "最近24小时"}</option>
              <option value="7d">{isMobile ? "7d" : "最近7天"}</option>
              <option value="30d">{isMobile ? "30d" : "最近30天"}</option>
            </select>
          )}

          {/* 播放/暂停 */}
          {activeTab === "flow" && (
            <button
              onClick={() => setIsPlaying(!isPlaying)}
              className="p-1.5 md:p-2 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
            >
              {isPlaying ? (
                <Pause className="w-3 h-3 md:w-4 md:h-4 text-white" />
              ) : (
                <Play className="w-3 h-3 md:w-4 md:h-4 text-white" />
              )}
            </button>
          )}

          {/* 刷新 */}
          <button
            onClick={loadAllData}
            disabled={loading}
            className="p-1.5 md:p-2 rounded-lg bg-white/5 hover:bg-white/10 transition-colors disabled:opacity-50"
          >
            <RefreshCw
              className={`w-3 h-3 md:w-4 md:h-4 text-white ${loading ? "animate-spin" : ""}`}
            />
          </button>

          {/* 导出 - 移动端隐藏文字 */}
          <button
            onClick={handleExport}
            className="flex items-center gap-1 px-2 md:px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 transition-colors text-xs md:text-sm text-white"
          >
            <Download className="w-3 h-3 md:w-4 md:h-4" />
            {!isMobile && "导出"}
          </button>

          {/* 全屏 */}
          <button
            onClick={() => setIsFullscreen(!isFullscreen)}
            className="p-1.5 md:p-2 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
          >
            {isFullscreen ? (
              <Minimize2 className="w-3 h-3 md:w-4 md:h-4 text-white" />
            ) : (
              <Maximize2 className="w-3 h-3 md:w-4 md:h-4 text-white" />
            )}
          </button>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════════════════
          主内容区 - 响应式布局
          ═══════════════════════════════════════════════════════════════════ */}
      <div
        className={`flex-1 flex overflow-hidden ${isMobile ? "flex-col" : ""}`}
      >
        {/* 左侧/主可视化区 */}
        <div className="flex-1 p-2 md:p-4 min-h-0">
          <AnimatePresence mode="wait">
            {activeTab === "flow" && (
              <motion.div
                key="flow"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="h-full bg-sb-bg-secondary rounded-xl border border-white/10 overflow-hidden"
              >
                <MemoryFlowChart
                  data={flowData}
                  isPlaying={isPlaying}
                  isMobile={isMobile}
                />
              </motion.div>
            )}

            {activeTab === "graph" && (
              <motion.div
                key="graph"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="h-full bg-sb-bg-secondary rounded-xl border border-white/10 overflow-hidden"
              >
                <MemoryGraphCanvas
                  data={graphData}
                  selectedNode={selectedNode}
                  onNodeSelect={setSelectedNode}
                  isMobile={isMobile}
                />
              </motion.div>
            )}

            {activeTab === "stats" && (
              <motion.div
                key="stats"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="h-full overflow-auto space-y-3 md:space-y-4"
              >
                {/* 统计卡片 - 响应式网格 */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 md:gap-4">
                  <div className="bg-sb-bg-secondary rounded-xl border border-white/10 p-3 md:p-4">
                    <div className="flex items-center gap-2 text-white/60 text-xs md:text-sm mb-1 md:mb-2">
                      <Database className="w-3 h-3 md:w-4 md:h-4" />
                      总记忆数
                    </div>
                    <div className="text-xl md:text-3xl font-bold text-white">
                      {stats?.total_memories || 0}
                    </div>
                  </div>

                  <div className="bg-sb-bg-secondary rounded-xl border border-white/10 p-3 md:p-4">
                    <div className="flex items-center gap-2 text-white/60 text-xs md:text-sm mb-1 md:mb-2">
                      <Zap className="w-3 h-3 md:w-4 md:h-4" />
                      活跃记忆
                    </div>
                    <div className="text-xl md:text-3xl font-bold text-sb-cyan">
                      {stats?.active_memories || 0}
                    </div>
                  </div>

                  <div className="bg-sb-bg-secondary rounded-xl border border-white/10 p-3 md:p-4">
                    <div className="flex items-center gap-2 text-white/60 text-xs md:text-sm mb-1 md:mb-2">
                      <Target className="w-3 h-3 md:w-4 md:h-4" />
                      留存率
                    </div>
                    <div className="text-xl md:text-3xl font-bold text-green-400">
                      {((stats?.retention_rate || 0) * 100).toFixed(1)}%
                    </div>
                  </div>

                  <div className="bg-sb-bg-secondary rounded-xl border border-white/10 p-3 md:p-4">
                    <div className="flex items-center gap-2 text-white/60 text-xs md:text-sm mb-1 md:mb-2">
                      <TrendingUp className="w-3 h-3 md:w-4 md:h-4" />
                      今日新增
                    </div>
                    <div className="text-xl md:text-3xl font-bold text-orange-400">
                      {stats?.daily_growth
                        .filter(
                          (d) =>
                            d.date === new Date().toISOString().split("T")[0],
                        )
                        .reduce((a, b) => a + b.count, 0) || 0}
                    </div>
                  </div>
                </div>

                {/* 图表区 - 响应式布局 */}
                <div
                  className={`grid gap-3 md:gap-4 ${isMobile ? "grid-cols-1" : "grid-cols-2"}`}
                >
                  <div className="bg-sb-bg-secondary rounded-xl border border-white/10 p-3 md:p-4">
                    <h3 className="text-white font-medium mb-2 md:mb-4 flex items-center gap-2 text-sm md:text-base">
                      <Layers className="w-3 h-3 md:w-4 md:h-4 text-sb-cyan" />
                      层级分布
                    </h3>
                    {stats && (
                      <LayerDistributionChart
                        data={stats.layer_distribution}
                        isMobile={isMobile}
                      />
                    )}
                  </div>

                  <div className="bg-sb-bg-secondary rounded-xl border border-white/10 p-3 md:p-4">
                    <h3 className="text-white font-medium mb-2 md:mb-4 flex items-center gap-2 text-sm md:text-base">
                      <TrendingUp className="w-3 h-3 md:w-4 md:h-4 text-sb-cyan" />
                      增长趋势
                    </h3>
                    {stats && (
                      <GrowthTrendChart
                        data={stats.daily_growth}
                        isMobile={isMobile}
                      />
                    )}
                  </div>
                </div>

                {/* 来源分布 */}
                <div className="bg-sb-bg-secondary rounded-xl border border-white/10 p-3 md:p-4">
                  <h3 className="text-white font-medium mb-3 md:mb-4 flex items-center gap-2 text-sm md:text-base">
                    <Brain className="w-3 h-3 md:w-4 md:h-4 text-sb-cyan" />
                    来源分布
                  </h3>
                  <div
                    className={`grid gap-3 md:gap-4 ${isMobile ? "grid-cols-2" : "grid-cols-4"}`}
                  >
                    {stats &&
                      [
                        {
                          label: "AI生成",
                          value: stats.source_distribution.AI,
                          color: "bg-purple-500",
                        },
                        {
                          label: "系统",
                          value: stats.source_distribution.system,
                          color: "bg-blue-500",
                        },
                        {
                          label: "用户",
                          value: stats.source_distribution.user,
                          color: "bg-green-500",
                        },
                        {
                          label: "工具",
                          value: stats.source_distribution.tool,
                          color: "bg-orange-500",
                        },
                      ].map((item, i) => (
                        <div key={i} className="text-center">
                          <div
                            className={`${item.color} rounded-lg p-2 md:p-3 mb-1 md:mb-2`}
                          >
                            <div className="text-lg md:text-2xl font-bold text-white">
                              {item.value}
                            </div>
                          </div>
                          <div className="text-xs md:text-sm text-white/60">
                            {item.label}
                          </div>
                        </div>
                      ))}
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* ═══════════════════════════════════════════════════════════════════
            右侧面板 - 移动端可收起或全宽
            ═══════════════════════════════════════════════════════════════════ */}
        <div
          className={`${isMobile ? "w-full border-t" : "w-80 border-l"} border-white/10 p-2 md:p-4 space-y-3 md:space-y-4 ${isMobile ? "max-h-48" : ""}`}
        >
          {/* 实时注入监控 */}
          <div className="bg-sb-bg-secondary rounded-xl border border-white/10 p-3 md:p-4">
            <h3 className="text-white font-medium mb-2 md:mb-3 flex items-center gap-2 text-sm">
              <Activity className="w-3 h-3 md:w-4 md:h-4 text-green-400" />
              实时注入监控
              <span className="flex-1" />
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
            </h3>
            <div className={`${isMobile ? "h-24" : "h-64"}`}>
              <RealtimeMonitor updates={realtimeUpdates} isMobile={isMobile} />
            </div>
          </div>

          {/* 选中节点信息 */}
          {selectedNode && activeTab === "graph" && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-sb-bg-secondary rounded-xl border border-white/10 p-3 md:p-4"
            >
              <h3 className="text-white font-medium mb-2 text-sm">节点详情</h3>
              {(() => {
                const node = graphData.nodes.find((n) => n.id === selectedNode);
                if (!node) return null;
                return (
                  <div className="space-y-1 md:space-y-2 text-xs md:text-sm">
                    <div className="flex justify-between">
                      <span className="text-white/60">ID</span>
                      <span className="text-white font-mono">
                        {node.id.slice(0, 8)}...
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-white/60">层级</span>
                      <span className="text-white">{node.layer}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-white/60">类型</span>
                      <span className="text-white">{node.type}</span>
                    </div>
                    <div className="mt-2 p-1.5 md:p-2 bg-white/5 rounded text-white/80">
                      {node.label}
                    </div>
                  </div>
                );
              })()}
            </motion.div>
          )}

          {/* 快速统计 */}
          <div className="bg-sb-bg-secondary rounded-xl border border-white/10 p-3 md:p-4">
            <h3 className="text-white font-medium mb-2 md:mb-3 flex items-center gap-2 text-sm">
              <Clock className="w-3 h-3 md:w-4 md:h-4 text-sb-cyan" />
              快速统计
            </h3>
            <div className="space-y-2 md:space-y-3 text-xs md:text-sm">
              <div className="flex justify-between">
                <span className="text-white/60">新增记忆</span>
                <span className="text-sb-cyan">{flowData.inputs.length}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-white/60">检索次数</span>
                <span className="text-green-400">
                  {flowData.outputs.length}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-white/60">转换/升级</span>
                <span className="text-orange-400">
                  {flowData.transforms.length}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-white/60">图谱节点</span>
                <span className="text-purple-400">
                  {graphData.nodes.length}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-white/60">关联边</span>
                <span className="text-pink-400">{graphData.edges.length}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
