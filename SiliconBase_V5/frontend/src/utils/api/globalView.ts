/**
 * GlobalView API - 磁盘文件扫描可视化接口
 * 
 * 提供文件扫描状态、文件树、搜索等功能
 * 【路径修正】所有端点统一使用 /api/global-view 前缀，与后端 router 对齐
 */
import { fetchAPI, handleAPIError } from './core';

export interface FileNode {
  id: string;
  name: string;
  path: string;
  type: 'file' | 'folder';
  size?: number;
  modified_time?: string;
  file_type?: string;
  is_executable?: boolean;
  children?: FileNode[];
  scanned_at?: string;
}

export interface FileTreeResponse {
  drives: FileNode[];
  total_files: number;
  total_size: number;
  last_scan?: string;
}

export interface ScanStatus {
  is_scanning: boolean;
  progress: number;
  current_drive?: string;
  scanned_files: number;
  total_files: number;
  message?: string;
  last_scan_completed?: string;
}

export interface SearchResult {
  results: FileNode[];
  total: number;
  keyword: string;
}

export interface FileStats {
  total_files: number;
  total_folders: number;
  total_size: number;
  by_type: Record<string, number>;
  by_drive: Record<string, number>;
  last_scan?: string;
}

export interface MessageResponse {
  success: boolean;
  message: string;
}

/**
 * 获取扫描状态
 */
export async function getScanStatus(): Promise<ScanStatus> {
  try {
    return await fetchAPI<ScanStatus>('/api/global-view/status');
  } catch (error) {
    throw handleAPIError(error, '获取扫描状态失败');
  }
}

/**
 * 获取文件树
 */
export async function getFileTree(
  drive?: string,
  maxDepth: number = 3
): Promise<FileTreeResponse> {
  try {
    const params = new URLSearchParams();
    if (drive) params.append('drive', drive);
    params.append('max_depth', maxDepth.toString());
    return await fetchAPI<FileTreeResponse>(`/api/global-view/tree?${params.toString()}`);
  } catch (error) {
    throw handleAPIError(error, '获取文件树失败');
  }
}

/**
 * 搜索文件
 */
export async function searchFiles(
  keyword: string,
  fileType?: string,
  limit: number = 20
): Promise<SearchResult> {
  try {
    const params = new URLSearchParams();
    params.append('keyword', keyword);
    if (fileType) params.append('file_type', fileType);
    params.append('limit', limit.toString());
    return await fetchAPI<SearchResult>(`/api/global-view/search?${params.toString()}`);
  } catch (error) {
    throw handleAPIError(error, '搜索文件失败');
  }
}

/**
 * 开始扫描
 */
export async function startScan(drives?: string[]): Promise<MessageResponse> {
  try {
    return await fetchAPI<MessageResponse>('/api/global-view/scan/start', {
      method: 'POST',
      body: { drives },
    });
  } catch (error) {
    throw handleAPIError(error, '启动扫描失败');
  }
}

/**
 * 停止扫描
 */
export async function stopScan(): Promise<MessageResponse> {
  try {
    return await fetchAPI<MessageResponse>('/api/global-view/scan/stop', {
      method: 'POST',
    });
  } catch (error) {
    throw handleAPIError(error, '停止扫描失败');
  }
}

/**
 * 清空扫描数据
 */
export async function clearAllData(): Promise<MessageResponse> {
  try {
    return await fetchAPI<MessageResponse>('/api/global-view/clear', {
      method: 'DELETE',
    });
  } catch (error) {
    throw handleAPIError(error, '清空数据失败');
  }
}

/**
 * 获取统计信息
 */
export async function getStats(): Promise<FileStats> {
  try {
    return await fetchAPI<FileStats>('/api/global-view/stats');
  } catch (error) {
    throw handleAPIError(error, '获取统计信息失败');
  }
}

// 导出所有API的命名空间
export const globalViewAPI = {
  getScanStatus,
  getFileTree,
  searchFiles,
  startScan,
  stopScan,
  clearAllData,
  getStats,
};
