/**
 * Cache Utilities - 缓存优化工具
 * Phase 5 Week 9 - 用户体验优化
 * 
 * 包含：
 * - LRUCache: 最近最少使用缓存
 * - Memoize: 函数结果记忆化
 * - CacheManager: 统一缓存管理
 */

// ═══════════════════════════════════════════════════════════════════
// LRU Cache - 最近最少使用缓存
// ═══════════════════════════════════════════════════════════════════

interface LRUCacheOptions {
  maxSize: number;
  ttl?: number; // 过期时间（毫秒）
}

interface CacheEntry<V> {
  value: V;
  timestamp: number;
  key: string;
}

export class LRUCache<K, V> {
  private cache: Map<string, CacheEntry<V>>;
  private maxSize: number;
  private ttl: number | null;

  constructor(options: LRUCacheOptions) {
    this.cache = new Map();
    this.maxSize = options.maxSize;
    this.ttl = options.ttl || null;
  }

  private getKey(key: K): string {
    return JSON.stringify(key);
  }

  get(key: K): V | undefined {
    const stringKey = this.getKey(key);
    const entry = this.cache.get(stringKey);

    if (!entry) {
      return undefined;
    }

    // 检查是否过期
    if (this.ttl && Date.now() - entry.timestamp > this.ttl) {
      this.cache.delete(stringKey);
      return undefined;
    }

    // 更新位置（移到最新）
    this.cache.delete(stringKey);
    this.cache.set(stringKey, { ...entry, timestamp: Date.now() });

    return entry.value;
  }

  set(key: K, value: V): void {
    const stringKey = this.getKey(key);

    // 如果已存在，先删除
    if (this.cache.has(stringKey)) {
      this.cache.delete(stringKey);
    }

    // 如果达到上限，删除最旧的
    if (this.cache.size >= this.maxSize) {
      const firstKey = this.cache.keys().next().value;
      if (firstKey) {
        this.cache.delete(firstKey);
      }
    }

    this.cache.set(stringKey, {
      value,
      timestamp: Date.now(),
      key: stringKey,
    });
  }

  delete(key: K): boolean {
    return this.cache.delete(this.getKey(key));
  }

  has(key: K): boolean {
    const stringKey = this.getKey(key);
    const entry = this.cache.get(stringKey);

    if (!entry) {
      return false;
    }

    // 检查是否过期
    if (this.ttl && Date.now() - entry.timestamp > this.ttl) {
      this.cache.delete(stringKey);
      return false;
    }

    return true;
  }

  clear(): void {
    this.cache.clear();
  }

  size(): number {
    // 清理过期项后返回大小
    if (this.ttl) {
      const now = Date.now();
      for (const [key, entry] of this.cache.entries()) {
        if (now - entry.timestamp > this.ttl) {
          this.cache.delete(key);
        }
      }
    }
    return this.cache.size;
  }

  keys(): K[] {
    const keys: K[] = [];
    for (const entry of this.cache.values()) {
      keys.push(JSON.parse(entry.key));
    }
    return keys;
  }

  values(): V[] {
    const values: V[] = [];
    for (const entry of this.cache.values()) {
      values.push(entry.value);
    }
    return values;
  }
}

// ═══════════════════════════════════════════════════════════════════
// Memoize - 函数结果记忆化
// ═══════════════════════════════════════════════════════════════════

interface MemoizeOptions {
  maxSize?: number;
  ttl?: number;
  resolver?: (...args: any[]) => string; // 自定义缓存键生成
}

export function memoize<T extends (...args: any[]) => any>(
  fn: T,
  options: MemoizeOptions = {}
): T {
  const { maxSize = 100, ttl, resolver } = options;
  const cache = new LRUCache<string, ReturnType<T>>({ maxSize, ttl });

  const memoized = (...args: Parameters<T>): ReturnType<T> => {
    const key = resolver ? resolver(...args) : JSON.stringify(args);
    
    const cached = cache.get(key);
    if (cached !== undefined) {
      return cached;
    }

    const result = fn(...args);
    cache.set(key, result);
    return result;
  };

  // 添加缓存操作方法
  (memoized as any).cache = cache;
  (memoized as any).clear = () => cache.clear();

  return memoized as T;
}

// ═══════════════════════════════════════════════════════════════════
// Cache Manager - 统一缓存管理
// ═══════════════════════════════════════════════════════════════════

type CacheType = 'memory' | 'session' | 'local';

interface CacheItem<T> {
  data: T;
  timestamp: number;
  ttl: number;
}

class CacheManager {
  private memoryCache: Map<string, CacheItem<any>>;

  constructor() {
    this.memoryCache = new Map();
  }

  // 获取缓存
  get<T>(key: string, type: CacheType = 'memory'): T | null {
    switch (type) {
      case 'memory':
        return this.getFromMemory<T>(key);
      case 'session':
        return this.getFromSessionStorage<T>(key);
      case 'local':
        return this.getFromLocalStorage<T>(key);
      default:
        return null;
    }
  }

  // 设置缓存
  set<T>(key: string, data: T, ttl: number = 300000, type: CacheType = 'memory'): void {
    switch (type) {
      case 'memory':
        this.setToMemory(key, data, ttl);
        break;
      case 'session':
        this.setToSessionStorage(key, data, ttl);
        break;
      case 'local':
        this.setToLocalStorage(key, data, ttl);
        break;
    }
  }

  // 删除缓存
  remove(key: string, type: CacheType = 'memory'): void {
    switch (type) {
      case 'memory':
        this.memoryCache.delete(key);
        break;
      case 'session':
        sessionStorage.removeItem(key);
        break;
      case 'local':
        localStorage.removeItem(key);
        break;
    }
  }

  // 清空缓存
  clear(type?: CacheType): void {
    if (!type || type === 'memory') {
      this.memoryCache.clear();
    }
    if (!type || type === 'session') {
      sessionStorage.clear();
    }
    if (!type || type === 'local') {
      localStorage.clear();
    }
  }

  // Memory Cache
  private getFromMemory<T>(key: string): T | null {
    const item = this.memoryCache.get(key);
    if (!item) return null;

    if (Date.now() - item.timestamp > item.ttl) {
      this.memoryCache.delete(key);
      return null;
    }

    return item.data;
  }

  private setToMemory<T>(key: string, data: T, ttl: number): void {
    this.memoryCache.set(key, {
      data,
      timestamp: Date.now(),
      ttl,
    });
  }

  // Session Storage
  private getFromSessionStorage<T>(key: string): T | null {
    try {
      const item = sessionStorage.getItem(key);
      if (!item) return null;

      const parsed: CacheItem<T> = JSON.parse(item);
      if (Date.now() - parsed.timestamp > parsed.ttl) {
        sessionStorage.removeItem(key);
        return null;
      }

      return parsed.data;
    } catch {
      return null;
    }
  }

  private setToSessionStorage<T>(key: string, data: T, ttl: number): void {
    try {
      sessionStorage.setItem(key, JSON.stringify({
        data,
        timestamp: Date.now(),
        ttl,
      }));
    } catch (e) {
      console.error('[CacheManager] SessionStorage error:', e);
    }
  }

  // Local Storage
  private getFromLocalStorage<T>(key: string): T | null {
    try {
      const item = localStorage.getItem(key);
      if (!item) return null;

      const parsed: CacheItem<T> = JSON.parse(item);
      if (Date.now() - parsed.timestamp > parsed.ttl) {
        localStorage.removeItem(key);
        return null;
      }

      return parsed.data;
    } catch {
      return null;
    }
  }

  private setToLocalStorage<T>(key: string, data: T, ttl: number): void {
    try {
      localStorage.setItem(key, JSON.stringify({
        data,
        timestamp: Date.now(),
        ttl,
      }));
    } catch (e) {
      console.error('[CacheManager] LocalStorage error:', e);
    }
  }
}

// 导出单例实例
export const cacheManager = new CacheManager();

// ═══════════════════════════════════════════════════════════════════
// Request Cache - API请求缓存
// ═══════════════════════════════════════════════════════════════════

interface RequestCacheOptions {
  ttl?: number;
  key?: string | ((...args: any[]) => string);
}

export function createRequestCache<T extends (...args: any[]) => Promise<any>>(
  requestFn: T,
  options: RequestCacheOptions = {}
): T {
  const { key } = options;
  const cache = new LRUCache<string, Promise<any>>({ maxSize: 50 });

  const cachedRequest = (...args: Parameters<T>): Promise<ReturnType<T>> => {
    const cacheKey = key 
      ? (typeof key === 'function' ? key(...args) : key)
      : JSON.stringify(args);

    const cached = cache.get(cacheKey);
    if (cached) {
      return cached;
    }

    const promise = requestFn(...args);
    cache.set(cacheKey, promise);

    // 请求完成后设置过期时间
    promise.catch(() => {
      cache.delete(cacheKey);
    });

    return promise;
  };

  (cachedRequest as any).clear = () => cache.clear();
  (cachedRequest as any).invalidate = (key: string) => cache.delete(key);

  return cachedRequest as T;
}

// ═══════════════════════════════════════════════════════════════════
// Debounce Cache - 防抖缓存（用于搜索等场景）
// ═══════════════════════════════════════════════════════════════════

export class DebounceCache<T> {
  private cache: Map<string, { value: T; timer: ReturnType<typeof setTimeout> }>;
  private debounceMs: number;

  constructor(debounceMs: number = 300) {
    this.cache = new Map();
    this.debounceMs = debounceMs;
  }

  get(key: string): T | undefined {
    const entry = this.cache.get(key);
    return entry?.value;
  }

  set(key: string, value: T): void {
    // 清除之前的定时器
    const existing = this.cache.get(key);
    if (existing) {
      clearTimeout(existing.timer);
    }

    // 设置新的定时器，延迟后清除缓存
    const timer = setTimeout(() => {
      this.cache.delete(key);
    }, this.debounceMs);

    this.cache.set(key, { value, timer });
  }

  clear(): void {
    for (const entry of this.cache.values()) {
      clearTimeout(entry.timer);
    }
    this.cache.clear();
  }
}

// ═══════════════════════════════════════════════════════════════════
// 实用函数
// ═══════════════════════════════════════════════════════════════════

// 生成缓存键
export function generateCacheKey(prefix: string, params: Record<string, any>): string {
  const sortedParams = Object.keys(params)
    .sort()
    .map(key => `${key}=${JSON.stringify(params[key])}`)
    .join('&');
  return `${prefix}:${sortedParams}`;
}

// 计算缓存命中率（用于监控）
export function calculateCacheHitRate(hits: number, misses: number): number {
  const total = hits + misses;
  return total === 0 ? 0 : Math.round((hits / total) * 100);
}

// 缓存装饰器（用于类方法）
export function Cacheable(options: MemoizeOptions = {}) {
  return function (
    _target: any,
    _propertyKey: string,
    descriptor: PropertyDescriptor
  ) {
    const originalMethod = descriptor.value;
    const memoizedMethod = memoize(originalMethod, options);
    descriptor.value = memoizedMethod;
    return descriptor;
  };
}
