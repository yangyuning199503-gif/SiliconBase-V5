/**
 * usePerformance - 性能优化 Hooks
 * Phase 5 Week 9 - 用户体验优化
 * 
 * 包含：
 * - useDebounce: 防抖
 * - useThrottle: 节流
 * - useMemoizedFn: 记忆化函数
 * - useMount: 组件挂载时执行
 * - useUnmount: 组件卸载时执行
 * - useUpdateEffect: 跳过首次执行的useEffect
 * - useInViewport: 元素是否在可视区域
 * - usePrevious: 获取上一次值
 */

import { 
  useState, useEffect, useRef, useCallback, 
  DependencyList, MutableRefObject 
} from 'react';

// ═══════════════════════════════════════════════════════════════════
// useDebounce - 防抖
// ═══════════════════════════════════════════════════════════════════

export function useDebounce<T>(value: T, delay: number = 300): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => clearTimeout(timer);
  }, [value, delay]);

  return debouncedValue;
}

// ═══════════════════════════════════════════════════════════════════
// useThrottle - 节流
// ═══════════════════════════════════════════════════════════════════

export function useThrottle<T>(value: T, interval: number = 200): T {
  const [throttledValue, setThrottledValue] = useState<T>(value);
  const lastUpdated = useRef<number>(Date.now());

  useEffect(() => {
    const now = Date.now();
    const timeElapsed = now - lastUpdated.current;

    if (timeElapsed >= interval) {
      setThrottledValue(value);
      lastUpdated.current = now;
    } else {
      const timer = setTimeout(() => {
        setThrottledValue(value);
        lastUpdated.current = Date.now();
      }, interval - timeElapsed);

      return () => clearTimeout(timer);
    }
  }, [value, interval]);

  return throttledValue;
}

// ═══════════════════════════════════════════════════════════════════
// useMemoizedFn - 记忆化函数（保持引用稳定）
// ═══════════════════════════════════════════════════════════════════

export function useMemoizedFn<T extends (...args: any[]) => any>(fn: T): T {
  const fnRef = useRef<T>(fn);
  
  useEffect(() => {
    fnRef.current = fn;
  }, [fn]);

  const memoizedFn = useCallback((...args: Parameters<T>): ReturnType<T> => {
    return fnRef.current(...args);
  }, []);

  return memoizedFn as T;
}

// ═══════════════════════════════════════════════════════════════════
// useMount - 组件挂载时执行
// ═══════════════════════════════════════════════════════════════════

export function useMount(fn: () => void) {
  useEffect(() => {
    fn();
  }, []);
}

// ═══════════════════════════════════════════════════════════════════
// useUnmount - 组件卸载时执行
// ═══════════════════════════════════════════════════════════════════

export function useUnmount(fn: () => void) {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    return () => {
      fnRef.current();
    };
  }, []);
}

// ═══════════════════════════════════════════════════════════════════
// useUpdateEffect - 跳过首次执行的useEffect
// ═══════════════════════════════════════════════════════════════════

export function useUpdateEffect(effect: () => void | (() => void), deps: DependencyList) {
  const isFirstRender = useRef(true);

  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    return effect();
  }, deps);
}

// ═══════════════════════════════════════════════════════════════════
// useInViewport - 元素是否在可视区域
// ═══════════════════════════════════════════════════════════════════

interface UseInViewportOptions {
  threshold?: number;
  rootMargin?: string;
  triggerOnce?: boolean; // 只触发一次
}

export function useInViewport<T extends HTMLElement>(
  options: UseInViewportOptions = {}
): [MutableRefObject<T | null>, boolean] {
  const { threshold = 0, rootMargin = '0px', triggerOnce = false } = options;
  const ref = useRef<T | null>(null);
  const [inViewport, setInViewport] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        const isIntersecting = entry.isIntersecting;
        setInViewport(isIntersecting);
        
        if (isIntersecting && triggerOnce) {
          observer.disconnect();
        }
      },
      { threshold, rootMargin }
    );

    observer.observe(element);

    return () => observer.disconnect();
  }, [threshold, rootMargin, triggerOnce]);

  return [ref, inViewport];
}

// ═══════════════════════════════════════════════════════════════════
// usePrevious - 获取上一次值
// ═══════════════════════════════════════════════════════════════════

export function usePrevious<T>(value: T): T | undefined {
  const [prev, setPrev] = useState<T | undefined>(undefined);
  const currentRef = useRef<T>(value);

  useEffect(() => {
    setPrev(currentRef.current);
    currentRef.current = value;
  }, [value]);

  return prev;
}

// ═══════════════════════════════════════════════════════════════════
// useLocalStorage - 持久化状态到localStorage
// ═══════════════════════════════════════════════════════════════════

export function useLocalStorage<T>(
  key: string,
  initialValue: T
): [T, (value: T | ((prev: T) => T)) => void] {
  const [storedValue, setStoredValue] = useState<T>(() => {
    try {
      const item = window.localStorage.getItem(key);
      return item ? (JSON.parse(item) as T) : initialValue;
    } catch (error) {
      console.error(`[useLocalStorage] Error reading key "${key}":`, error);
      return initialValue;
    }
  });

  const setValue = useCallback((value: T | ((prev: T) => T)) => {
    try {
      setStoredValue(prev => {
        const valueToStore = value instanceof Function ? value(prev) : value;
        window.localStorage.setItem(key, JSON.stringify(valueToStore));
        return valueToStore;
      });
    } catch (error) {
      console.error(`[useLocalStorage] Error setting key "${key}":`, error);
    }
  }, [key]);

  return [storedValue, setValue];
}

// ═══════════════════════════════════════════════════════════════════
// useSessionStorage - 持久化状态到sessionStorage
// ═══════════════════════════════════════════════════════════════════

export function useSessionStorage<T>(
  key: string,
  initialValue: T
): [T, (value: T | ((prev: T) => T)) => void] {
  const [storedValue, setStoredValue] = useState<T>(() => {
    try {
      const item = window.sessionStorage.getItem(key);
      return item ? (JSON.parse(item) as T) : initialValue;
    } catch (error) {
      console.error(`[useSessionStorage] Error reading key "${key}":`, error);
      return initialValue;
    }
  });

  const setValue = useCallback((value: T | ((prev: T) => T)) => {
    try {
      setStoredValue(prev => {
        const valueToStore = value instanceof Function ? value(prev) : value;
        window.sessionStorage.setItem(key, JSON.stringify(valueToStore));
        return valueToStore;
      });
    } catch (error) {
      console.error(`[useSessionStorage] Error setting key "${key}":`, error);
    }
  }, [key]);

  return [storedValue, setValue];
}

// ═══════════════════════════════════════════════════════════════════
// useWindowSize - 监听窗口大小
// ═══════════════════════════════════════════════════════════════════

interface WindowSize {
  width: number;
  height: number;
}

export function useWindowSize(): WindowSize {
  const [windowSize, setWindowSize] = useState<WindowSize>({
    width: window.innerWidth,
    height: window.innerHeight,
  });

  useEffect(() => {
    const handleResize = () => {
      setWindowSize({
        width: window.innerWidth,
        height: window.innerHeight,
      });
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return windowSize;
}

// ═══════════════════════════════════════════════════════════════════
// useMediaQuery - 响应式媒体查询
// ═══════════════════════════════════════════════════════════════════

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const mediaQuery = window.matchMedia(query);
    
    const handleChange = (event: MediaQueryListEvent) => {
      setMatches(event.matches);
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, [query]);

  return matches;
}

// ═══════════════════════════════════════════════════════════════════
// useIdleTimer - 空闲计时器
// ═══════════════════════════════════════════════════════════════════

interface UseIdleTimerOptions {
  timeout: number; // 空闲时间（毫秒）
  onIdle?: () => void;
  onActive?: () => void;
}

export function useIdleTimer(options: UseIdleTimerOptions) {
  const { timeout, onIdle, onActive } = options;
  const [isIdle, setIsIdle] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const resetTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
    
    if (isIdle) {
      setIsIdle(false);
      onActive?.();
    }

    timerRef.current = setTimeout(() => {
      setIsIdle(true);
      onIdle?.();
    }, timeout);
  }, [timeout, isIdle, onIdle, onActive]);

  useEffect(() => {
    const events = ['mousedown', 'mousemove', 'keydown', 'touchstart', 'wheel'];
    
    events.forEach(event => {
      document.addEventListener(event, resetTimer);
    });

    resetTimer();

    return () => {
      events.forEach(event => {
        document.removeEventListener(event, resetTimer);
      });
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [resetTimer]);

  return { isIdle, resetTimer };
}

// ═══════════════════════════════════════════════════════════════════
// useRequestAnimationFrame - 使用requestAnimationFrame
// ═══════════════════════════════════════════════════════════════════

export function useRequestAnimationFrame(callback: (time: number) => void) {
  const requestRef = useRef<number>();
  const callbackRef = useRef(callback);

  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(() => {
    const animate = (time: number) => {
      callbackRef.current(time);
      requestRef.current = requestAnimationFrame(animate);
    };

    requestRef.current = requestAnimationFrame(animate);
    return () => {
      if (requestRef.current) {
        cancelAnimationFrame(requestRef.current);
      }
    };
  }, []);
}

// ═══════════════════════════════════════════════════════════════════
// useLongPress - 长按检测
// ═══════════════════════════════════════════════════════════════════

interface UseLongPressOptions {
  onLongPress: () => void;
  onClick?: () => void;
  ms?: number;
}

export function useLongPress(options: UseLongPressOptions) {
  const { onLongPress, onClick, ms = 500 } = options;
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const isLongPress = useRef(false);

  const start = useCallback(() => {
    isLongPress.current = false;
    timerRef.current = setTimeout(() => {
      isLongPress.current = true;
      onLongPress();
    }, ms);
  }, [onLongPress, ms]);

  const stop = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
  }, []);

  const handleClick = useCallback(() => {
    if (!isLongPress.current && onClick) {
      onClick();
    }
  }, [onClick]);

  return {
    onMouseDown: start,
    onMouseUp: stop,
    onMouseLeave: stop,
    onTouchStart: start,
    onTouchEnd: stop,
    onClick: handleClick,
  };
}

// ═══════════════════════════════════════════════════════════════════
// useFps - FPS监测
// ═══════════════════════════════════════════════════════════════════

export function useFps(): number {
  const [fps, setFps] = useState(60);
  const frameCount = useRef(0);
  const lastTime = useRef(performance.now());

  useEffect(() => {
    let animationId: number;

    const updateFps = () => {
      const now = performance.now();
      frameCount.current++;

      if (now >= lastTime.current + 1000) {
        setFps(frameCount.current);
        frameCount.current = 0;
        lastTime.current = now;
      }

      animationId = requestAnimationFrame(updateFps);
    };

    animationId = requestAnimationFrame(updateFps);
    return () => cancelAnimationFrame(animationId);
  }, []);

  return fps;
}
