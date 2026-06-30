/**
 * LazyImage - 懒加载图片组件
 * Phase 5 Week 9 - 用户体验优化
 * 
 * 功能：
 * - 图片进入可视区域才加载
 * - 加载状态显示
 * - 错误处理
 * - 渐显动画
 * - 占位符支持
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { motion } from 'framer-motion';
import { ImageIcon, Loader2, AlertCircle, RefreshCw } from 'lucide-react';

interface LazyImageProps {
  src: string;
  alt?: string;
  className?: string;
  containerClassName?: string;
  placeholderSrc?: string; // 低质量占位图
  placeholderColor?: string; // 占位背景色
  aspectRatio?: string; // 宽高比，如 "16/9"
  threshold?: number; // 交叉观察阈值
  rootMargin?: string; // 预加载边距
  onLoad?: () => void;
  onError?: (error: Error) => void;
  enableZoom?: boolean; // 是否启用点击放大
  maxHeight?: number; // 最大高度
}

type LoadingState = 'idle' | 'loading' | 'loaded' | 'error';

export default function LazyImage({
  src,
  alt = '',
  className = '',
  containerClassName = '',
  placeholderSrc,
  placeholderColor = '#2a2a3a',
  aspectRatio,
  threshold = 0.1,
  rootMargin = '50px',
  onLoad,
  onError,
  enableZoom = false,
  maxHeight = 400
}: LazyImageProps) {
  const [loadingState, setLoadingState] = useState<LoadingState>('idle');
  const [currentSrc, setCurrentSrc] = useState<string>(placeholderSrc || '');
  const [isZoomed, setIsZoomed] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const hasTriggeredLoad = useRef(false);

  // 使用 Intersection Observer 检测元素是否进入可视区域
  useEffect(() => {
    const container = containerRef.current;
    if (!container || hasTriggeredLoad.current) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && !hasTriggeredLoad.current) {
            hasTriggeredLoad.current = true;
            setLoadingState('loading');
            setCurrentSrc(src);
            observer.disconnect();
          }
        });
      },
      {
        threshold,
        rootMargin,
      }
    );

    observer.observe(container);

    return () => observer.disconnect();
  }, [src, threshold, rootMargin]);

  // 处理图片加载完成
  const handleLoad = useCallback(() => {
    setLoadingState('loaded');
    onLoad?.();
  }, [onLoad]);

  // 处理图片加载错误
  const handleError = useCallback(() => {
    setLoadingState('error');
    onError?.(new Error(`Failed to load image: ${src}`));
  }, [src, onError]);

  // 重试加载
  const handleRetry = useCallback(() => {
    setLoadingState('loading');
    // 添加时间戳避免缓存
    const retrySrc = `${src}${src.includes('?') ? '&' : '?'}_retry=${Date.now()}`;
    setCurrentSrc(retrySrc);
  }, [src]);

  // 点击放大
  const handleClick = useCallback(() => {
    if (enableZoom && loadingState === 'loaded') {
      setIsZoomed(true);
    }
  }, [enableZoom, loadingState]);

  // 关闭放大
  const handleCloseZoom = useCallback(() => {
    setIsZoomed(false);
  }, []);

  const containerStyle: React.CSSProperties = {
    aspectRatio: aspectRatio,
    backgroundColor: loadingState !== 'loaded' ? placeholderColor : 'transparent',
    maxHeight: maxHeight,
  };

  return (
    <>
      <div
        ref={containerRef}
        className={`
          relative overflow-hidden rounded-lg
          ${containerClassName}
        `}
        style={containerStyle}
      >
        {/* 占位符/加载状态 */}
        {loadingState !== 'loaded' && (
          <div className="absolute inset-0 flex items-center justify-center">
            {loadingState === 'idle' && (
              // 等待加载
              <div className="flex flex-col items-center gap-2 text-slate-500">
                <ImageIcon className="w-8 h-8" />
                <span className="text-xs">等待加载...</span>
              </div>
            )}
            
            {loadingState === 'loading' && (
              // 加载中
              <div className="flex flex-col items-center gap-2 text-slate-400">
                <Loader2 className="w-6 h-6 animate-spin" />
                <span className="text-xs">加载中...</span>
              </div>
            )}
            
            {loadingState === 'error' && (
              // 加载失败
              <div className="flex flex-col items-center gap-2 text-red-400">
                <AlertCircle className="w-8 h-8" />
                <span className="text-xs">加载失败</span>
                <button
                  onClick={handleRetry}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-red-500/10 text-red-400 text-xs hover:bg-red-500/20 transition-colors"
                >
                  <RefreshCw className="w-3 h-3" />
                  重试
                </button>
              </div>
            )}
          </div>
        )}

        {/* 实际图片 */}
        {currentSrc && (
          <motion.img
            ref={imgRef}
            src={currentSrc}
            alt={alt}
            className={`
              w-full h-full object-cover transition-opacity duration-300
              ${loadingState === 'loaded' ? 'opacity-100' : 'opacity-0'}
              ${enableZoom && loadingState === 'loaded' ? 'cursor-zoom-in' : ''}
              ${className}
            `}
            onLoad={handleLoad}
            onError={handleError}
            onClick={handleClick}
            initial={{ opacity: 0 }}
            animate={{ opacity: loadingState === 'loaded' ? 1 : 0 }}
            transition={{ duration: 0.3 }}
          />
        )}

        {/* 悬停提示（可放大） */}
        {enableZoom && loadingState === 'loaded' && (
          <div className="absolute inset-0 bg-black/0 hover:bg-black/20 transition-colors flex items-center justify-center opacity-0 hover:opacity-100">
            <span className="text-white text-xs bg-black/50 px-3 py-1.5 rounded-lg">
              点击放大
            </span>
          </div>
        )}
      </div>

      {/* 放大查看模态框 */}
      {isZoomed && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-4"
          onClick={handleCloseZoom}
        >
          <motion.img
            initial={{ scale: 0.9 }}
            animate={{ scale: 1 }}
            exit={{ scale: 0.9 }}
            src={src}
            alt={alt}
            className="max-w-full max-h-full object-contain cursor-zoom-out"
            onClick={(e) => e.stopPropagation()}
          />
          <button
            onClick={handleCloseZoom}
            className="absolute top-4 right-4 p-2 rounded-lg bg-white/10 text-white hover:bg-white/20 transition-colors"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </motion.div>
      )}
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 图片画廊组件（使用懒加载）
// ═══════════════════════════════════════════════════════════════════

interface ImageGalleryProps {
  images: Array<{
    src: string;
    alt?: string;
    thumbnail?: string;
  }>;
  className?: string;
  columns?: number; // 列数
  gap?: number; // 间距
}

export function ImageGallery({
  images,
  className = '',
  columns = 3,
  gap = 8
}: ImageGalleryProps) {
  if (!images || images.length === 0) return null;

  return (
    <div 
      className={`grid ${className}`}
      style={{
        gridTemplateColumns: `repeat(${Math.min(columns, images.length)}, 1fr)`,
        gap: `${gap}px`
      }}
    >
      {images.map((image, index) => (
        <LazyImage
          key={index}
          src={image.src}
          alt={image.alt}
          placeholderSrc={image.thumbnail}
          enableZoom
          aspectRatio="1/1"
          className="rounded-lg"
        />
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 带缓存的图片组件
// ═══════════════════════════════════════════════════════════════════

const imageCache = new Map<string, HTMLImageElement>();

interface CachedImageProps extends Omit<LazyImageProps, 'onLoad'> {
  cacheKey?: string;
}

export function CachedImage({
  cacheKey,
  ...props
}: CachedImageProps) {
  const [, setIsCached] = useState(false);
  const key = cacheKey || props.src;

  useEffect(() => {
    if (imageCache.has(key)) {
      setIsCached(true);
    }
  }, [key]);

  const handleLoad = useCallback(() => {
    if (!imageCache.has(key)) {
      const img = new Image();
      img.src = props.src;
      imageCache.set(key, img);
    }
    setIsCached(true);
  }, [key, props.src]);

  return (
    <LazyImage
      {...props}
      onLoad={handleLoad}
    />
  );
}

// 清空图片缓存
export function clearImageCache() {
  imageCache.clear();
}

// 预加载图片
export function preloadImage(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (imageCache.has(src)) {
      resolve();
      return;
    }

    const img = new Image();
    img.onload = () => {
      imageCache.set(src, img);
      resolve();
    };
    img.onerror = reject;
    img.src = src;
  });
}

// 批量预加载
export function preloadImages(srcs: string[]): Promise<void> {
  return Promise.all(srcs.map(preloadImage)).then(() => undefined);
}
