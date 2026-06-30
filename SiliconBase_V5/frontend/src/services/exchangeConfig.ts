/**
 * 交易所配置服务
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 管理交易所API配置的增删改查
 * 
 * 类似 aiConfig.ts 的设计，提供统一的配置管理接口
 */

import { fetchAPI } from '@/utils/api';

// ═══════════════════════════════════════════════════════════════
// 类型定义
// ═══════════════════════════════════════════════════════════════

export type ExchangeType = 'okx' | 'binance';
export type TradingMode = 'demo' | 'live';

export interface ExchangeConfig {
  id: string;
  name: string;
  exchange: ExchangeType;
  mode: TradingMode;
  is_active: boolean;
  is_validated: boolean;
  testnet: boolean;
  created_at: number;
  updated_at: number;
}

export interface ExchangeConfigInput {
  exchange: ExchangeType;
  name: string;
  mode: TradingMode;
  api_key: string;
  api_secret: string;
  passphrase?: string;
  testnet?: boolean;
}

export interface TradingModeInfo {
  mode: TradingMode;
  available_modes: TradingMode[];
  has_live_config: boolean;
  message: string;
}

export interface ExchangeInfo {
  id: ExchangeType;
  name: string;
  logo: string;
  features: string[];
  requires_passphrase: boolean;
  testnet_available: boolean;
}

export interface ValidationResult {
  valid: boolean;
  message: string;
}

// ═══════════════════════════════════════════════════════════════
// API 服务
// ═══════════════════════════════════════════════════════════════

const API_BASE = '/api/exchange';

class ExchangeConfigService {
  /**
   * 获取用户所有交易所配置
   */
  async getConfigs(): Promise<ExchangeConfig[]> {
    try {
      const response = await fetchAPI<ExchangeConfig[]>(`${API_BASE}/configs`);
      return response;
    } catch (error) {
      console.error('[ExchangeConfigService] 获取配置列表失败:', error);
      throw error;
    }
  }

  /**
   * 创建新配置
   */
  async createConfig(config: ExchangeConfigInput): Promise<ExchangeConfig> {
    try {
      const response = await fetchAPI<ExchangeConfig>(`${API_BASE}/configs`, {
        method: 'POST',
        body: config,
      });
      return response;
    } catch (error) {
      console.error('[ExchangeConfigService] 创建配置失败:', error);
      throw error;
    }
  }

  /**
   * 更新配置
   */
  async updateConfig(
    configId: string,
    updates: Partial<ExchangeConfigInput>
  ): Promise<ExchangeConfig> {
    try {
      const response = await fetchAPI<ExchangeConfig>(
        `${API_BASE}/configs/${configId}`,
        {
          method: 'PUT',
          body: updates,
        }
      );
      return response;
    } catch (error) {
      console.error('[ExchangeConfigService] 更新配置失败:', error);
      throw error;
    }
  }

  /**
   * 删除配置
   */
  async deleteConfig(configId: string): Promise<void> {
    try {
      await fetchAPI<{ success: boolean; message: string }>(
        `${API_BASE}/configs/${configId}`,
        {
          method: 'DELETE',
        }
      );
    } catch (error) {
      console.error('[ExchangeConfigService] 删除配置失败:', error);
      throw error;
    }
  }

  /**
   * 验证配置
   */
  async validateConfig(configId: string): Promise<ValidationResult> {
    try {
      const response = await fetchAPI<ValidationResult>(
        `${API_BASE}/configs/${configId}/validate`,
        {
          method: 'POST',
        }
      );
      return response;
    } catch (error) {
      console.error('[ExchangeConfigService] 验证配置失败:', error);
      throw error;
    }
  }

  /**
   * 激活配置
   * 调用后端 POST /activate 端点激活指定配置
   */
  async activateConfig(configId: string): Promise<void> {
    try {
      await fetchAPI<{ success: boolean; message: string }>(
        `${API_BASE}/configs/${configId}/activate`,
        {
          method: 'POST',
        }
      );
    } catch (error) {
      console.error('[ExchangeConfigService] 激活配置失败:', error);
      throw error;
    }
  }

  /**
   * 获取当前交易模式
   */
  async getTradingMode(): Promise<TradingModeInfo> {
    try {
      const response = await fetchAPI<TradingModeInfo>(`${API_BASE}/mode`);
      return response;
    } catch (error) {
      console.error('[ExchangeConfigService] 获取交易模式失败:', error);
      throw error;
    }
  }

  /**
   * 获取支持的交易所列表
   */
  async getSupportedExchanges(): Promise<ExchangeInfo[]> {
    try {
      const response = await fetchAPI<{ exchanges: ExchangeInfo[] }>(
        `${API_BASE}/exchanges`
      );
      return response.exchanges;
    } catch (error) {
      console.error('[ExchangeConfigService] 获取交易所列表失败:', error);
      throw error;
    }
  }

  /**
   * 快速测试配置（创建+验证+可选删除）
   */
  async testConfig(
    config: ExchangeConfigInput,
    deleteAfter: boolean = false
  ): Promise<ValidationResult> {
    // 创建临时配置
    const created = await this.createConfig({
      ...config,
      name: `测试_${Date.now()}`,
    });

    try {
      // 验证配置
      const result = await this.validateConfig(created.id);

      if (result.valid && !deleteAfter) {
        // 验证成功且不需要删除，保留配置
        return result;
      }

      // 删除临时配置
      await this.deleteConfig(created.id);
      return result;
    } catch (error) {
      // 出错也要删除
      try {
        await this.deleteConfig(created.id);
      } catch {
        // 忽略删除错误
      }
      throw error;
    }
  }
}

// ═══════════════════════════════════════════════════════════════
// 导出
// ═══════════════════════════════════════════════════════════════

export const exchangeConfigService = new ExchangeConfigService();

// 便捷函数
export const getExchangeConfigs = () => exchangeConfigService.getConfigs();
export const createExchangeConfig = (config: ExchangeConfigInput) =>
  exchangeConfigService.createConfig(config);
export const updateExchangeConfig = (
  id: string,
  updates: Partial<ExchangeConfigInput>
) => exchangeConfigService.updateConfig(id, updates);
export const deleteExchangeConfig = (id: string) =>
  exchangeConfigService.deleteConfig(id);
export const validateExchangeConfig = (id: string) =>
  exchangeConfigService.validateConfig(id);
export const getTradingMode = () => exchangeConfigService.getTradingMode();
