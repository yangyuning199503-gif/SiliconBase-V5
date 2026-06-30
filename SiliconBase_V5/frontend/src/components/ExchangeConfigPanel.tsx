/**
 * 交易所配置面板
 * ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 * 管理交易所API配置，支持OKX和币安
 * 
 * 特性:
 * - 多交易所支持
 * - 模拟盘/实盘切换
 * - 配置验证
 * - 安全存储API密钥
 * 
 * 集成方式:
 * 1. 作为独立页面: <ExchangeConfigPanel />
 * 2. 集成到设置页: 在SettingsPage中引入
 * 3. 集成到AI配置页: 在AIConfigPage底部添加
 */

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Plus,
  Trash2,
  CheckCircle,
  RefreshCw,
  Eye,
  EyeOff,
  Server,
  TestTube,
  Shield,
  Activity,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Wallet
} from 'lucide-react';
import {
  exchangeConfigService,
  ExchangeConfig,
  ExchangeConfigInput,
  ExchangeInfo,
  ExchangeType
} from '../services/exchangeConfig';
import { useNotifications } from '../hooks/useNotifications';

// ═══════════════════════════════════════════════════════════════
// 交易所图标组件
// ═══════════════════════════════════════════════════════════════

const ExchangeIcon: React.FC<{ exchange: ExchangeType; className?: string }> = ({
  exchange,
  className = 'w-6 h-6'
}) => {
  const icons: Record<ExchangeType, React.ReactNode> = {
    okx: (
      <svg className={className} viewBox="0 0 32 32" fill="currentColor">
        <path d="M16 0C7.163 0 0 7.163 0 16s7.163 16 16 16 16-7.163 16-16S24.837 0 16 0zm0 28C9.373 28 4 22.627 4 16S9.373 4 16 4s12 5.373 12 12-5.373 12-12 12z" />
        <path d="M16 8a8 8 0 100 16 8 8 0 000-16z" />
      </svg>
    ),
    binance: (
      <svg className={className} viewBox="0 0 32 32" fill="currentColor">
        <path d="M16 0L12.6 3.4L19.4 10.2L16 13.6L6.4 4L16 0ZM16 32L12.6 28.6L19.4 21.8L16 18.4L25.6 28L16 32ZM6.4 16L9.8 12.6L16 18.8L22.2 12.6L25.6 16L16 25.6L6.4 16Z" />
      </svg>
    )
  };

  return <>{icons[exchange] || <Server className={className} />}</>;
};

// ═══════════════════════════════════════════════════════════════
// 配置卡片组件
// ═══════════════════════════════════════════════════════════════

const ConfigCard: React.FC<{
  config: ExchangeConfig;
  onDelete: (id: string) => void;
  onValidate: (id: string) => void;
  onActivate: (id: string) => void;
  validating: boolean;
}> = ({ config, onDelete, onValidate, onActivate, validating }) => {
  const [expanded, setExpanded] = useState(false);

  const statusColors = {
    active: 'bg-green-500/20 text-green-400 border-green-500/30',
    inactive: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
    error: 'bg-red-500/20 text-red-400 border-red-500/30'
  };

  const isActive = config.is_active && config.is_validated;

  return (
    <motion.div
      layout
      className={`rounded-xl border p-4 transition-all ${
        isActive
          ? 'bg-green-500/5 border-green-500/30'
          : 'bg-gray-800/50 border-gray-700'
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ExchangeIcon exchange={config.exchange} />
          <div>
            <div className="font-medium text-white">{config.name}</div>
            <div className="text-xs text-gray-400">
              {config.exchange.toUpperCase()} · {config.mode === 'live' ? '实盘' : '模拟盘'}
              {config.testnet && ' · 测试网'}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* 状态标签 */}
          <span
            className={`px-2 py-1 rounded text-xs font-medium border ${
              isActive ? statusColors.active : statusColors.inactive
            }`}
          >
            {isActive ? '已激活' : config.is_validated ? '已验证' : '待验证'}
          </span>

          {/* 展开/收起 */}
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-2 hover:bg-gray-700 rounded-lg transition-colors"
          >
            {expanded ? (
              <ChevronUp className="w-4 h-4 text-gray-400" />
            ) : (
              <ChevronDown className="w-4 h-4 text-gray-400" />
            )}
          </button>
        </div>
      </div>

      {/* 展开详情 */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="mt-4 pt-4 border-t border-gray-700 space-y-3"
          >
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-gray-500">创建时间:</span>
                <span className="ml-2 text-gray-300">
                  {new Date(config.created_at * 1000).toLocaleString()}
                </span>
              </div>
              <div>
                <span className="text-gray-500">更新时间:</span>
                <span className="ml-2 text-gray-300">
                  {new Date(config.updated_at * 1000).toLocaleString()}
                </span>
              </div>
            </div>

            <div className="flex gap-2 pt-2">
              {!config.is_active && config.is_validated && (
                <button
                  onClick={() => onActivate(config.id)}
                  className="flex-1 px-3 py-2 bg-green-600 hover:bg-green-500 rounded-lg 
                           text-white text-sm font-medium transition-colors flex items-center justify-center gap-2"
                >
                  <CheckCircle className="w-4 h-4" />
                  激活配置
                </button>
              )}

              {!config.is_validated && (
                <button
                  onClick={() => onValidate(config.id)}
                  disabled={validating}
                  className="flex-1 px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 
                           rounded-lg text-white text-sm font-medium transition-colors 
                           flex items-center justify-center gap-2"
                >
                  {validating ? (
                    <RefreshCw className="w-4 h-4 animate-spin" />
                  ) : (
                    <TestTube className="w-4 h-4" />
                  )}
                  {validating ? '验证中...' : '验证配置'}
                </button>
              )}

              <button
                onClick={() => onDelete(config.id)}
                className="px-3 py-2 bg-red-600/20 hover:bg-red-600/30 text-red-400 
                         rounded-lg text-sm font-medium transition-colors"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
};

// ═══════════════════════════════════════════════════════════════
// 添加配置弹窗
// ═══════════════════════════════════════════════════════════════

const AddConfigModal: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (config: ExchangeConfigInput) => void;
  exchanges: ExchangeInfo[];
  loading: boolean;
}> = ({ isOpen, onClose, onSubmit, exchanges, loading }) => {
  const [formData, setFormData] = useState<ExchangeConfigInput>({
    exchange: 'okx',
    name: '',
    mode: 'demo',
    api_key: '',
    api_secret: '',
    passphrase: '',
    testnet: true
  });
  const [showSecret, setShowSecret] = useState(false);

  const selectedExchange = exchanges.find((e) => e.id === formData.exchange);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="bg-gray-800 rounded-2xl border border-gray-700 w-full max-w-lg max-h-[90vh] overflow-y-auto"
      >
        <div className="p-6 border-b border-gray-700">
          <h3 className="text-xl font-semibold text-white">添加交易所配置</h3>
          <p className="text-sm text-gray-400 mt-1">
            配置您的交易所API密钥以启用真实交易
          </p>
        </div>

        <div className="p-6 space-y-4">
          {/* 交易所选择 */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              交易所
            </label>
            <div className="grid grid-cols-2 gap-3">
              {exchanges.map((exchange) => (
                <button
                  key={exchange.id}
                  onClick={() => setFormData({ ...formData, exchange: exchange.id })}
                  className={`flex items-center gap-3 p-3 rounded-xl border transition-all ${
                    formData.exchange === exchange.id
                      ? 'bg-blue-500/10 border-blue-500 text-white'
                      : 'bg-gray-700/50 border-gray-600 text-gray-300 hover:border-gray-500'
                  }`}
                >
                  <ExchangeIcon exchange={exchange.id} className="w-6 h-6" />
                  <span>{exchange.name}</span>
                </button>
              ))}
            </div>
          </div>

          {/* 配置名称 */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              配置名称
            </label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder={`我的${selectedExchange?.name}账户`}
              className="w-full px-4 py-2 bg-gray-900 border border-gray-600 rounded-lg 
                       text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
            />
          </div>

          {/* 交易模式 */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              交易模式
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => setFormData({ ...formData, mode: 'demo' })}
                className={`flex items-center gap-2 p-3 rounded-xl border transition-all ${
                  formData.mode === 'demo'
                    ? 'bg-green-500/10 border-green-500 text-white'
                    : 'bg-gray-700/50 border-gray-600 text-gray-300'
                }`}
              >
                <TestTube className="w-5 h-5" />
                <div className="text-left">
                  <div className="font-medium">模拟盘</div>
                  <div className="text-xs opacity-70">零风险测试</div>
                </div>
              </button>
              <button
                onClick={() => setFormData({ ...formData, mode: 'live' })}
                className={`flex items-center gap-2 p-3 rounded-xl border transition-all ${
                  formData.mode === 'live'
                    ? 'bg-yellow-500/10 border-yellow-500 text-white'
                    : 'bg-gray-700/50 border-gray-600 text-gray-300'
                }`}
              >
                <Wallet className="w-5 h-5" />
                <div className="text-left">
                  <div className="font-medium">实盘</div>
                  <div className="text-xs opacity-70">真实资金交易</div>
                </div>
              </button>
            </div>
          </div>

          {/* API Key */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              API Key
            </label>
            <input
              type="text"
              value={formData.api_key}
              onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
              placeholder="输入您的API Key"
              className="w-full px-4 py-2 bg-gray-900 border border-gray-600 rounded-lg 
                       text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 font-mono text-sm"
            />
          </div>

          {/* API Secret */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              API Secret
            </label>
            <div className="relative">
              <input
                type={showSecret ? 'text' : 'password'}
                value={formData.api_secret}
                onChange={(e) => setFormData({ ...formData, api_secret: e.target.value })}
                placeholder="输入您的API Secret"
                className="w-full px-4 py-2 bg-gray-900 border border-gray-600 rounded-lg 
                         text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 
                         font-mono text-sm pr-10"
              />
              <button
                onClick={() => setShowSecret(!showSecret)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white"
              >
                {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {/* Passphrase (OKX only) */}
          {selectedExchange?.requires_passphrase && (
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Passphrase <span className="text-red-400">*</span>
              </label>
              <input
                type="password"
                value={formData.passphrase}
                onChange={(e) => setFormData({ ...formData, passphrase: e.target.value })}
                placeholder="输入您的Passphrase"
                className="w-full px-4 py-2 bg-gray-900 border border-gray-600 rounded-lg 
                         text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 font-mono text-sm"
              />
            </div>
          )}

          {/* 测试网选项 */}
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="testnet"
              checked={formData.testnet}
              onChange={(e) => setFormData({ ...formData, testnet: e.target.checked })}
              className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-500 focus:ring-blue-500"
            />
            <label htmlFor="testnet" className="text-sm text-gray-300">
              使用测试网（推荐首次配置时启用）
            </label>
          </div>

          {/* 帮助链接 */}
          <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3 text-sm">
            <div className="flex items-start gap-2">
              <ExternalLink className="w-4 h-4 text-blue-400 mt-0.5" />
              <div>
                <div className="text-blue-300 font-medium">如何获取API Key?</div>
                <a
                  href={
                    formData.exchange === 'okx'
                      ? 'https://www.okx.com/account/my-api'
                      : 'https://www.binance.com/en/my/settings/api-management'
                  }
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-400 hover:text-blue-300 underline"
                >
                  访问 {selectedExchange?.name} 官网创建API Key
                </a>
              </div>
            </div>
          </div>
        </div>

        <div className="p-6 border-t border-gray-700 flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg 
                     text-white font-medium transition-colors"
          >
            取消
          </button>
          <button
            onClick={() => onSubmit(formData)}
            disabled={
              loading ||
              !formData.name ||
              !formData.api_key ||
              !formData.api_secret ||
              (selectedExchange?.requires_passphrase && !formData.passphrase)
            }
            className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 
                     disabled:cursor-not-allowed rounded-lg text-white font-medium 
                     transition-colors flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                保存中...
              </>
            ) : (
              <>
                <CheckCircle className="w-4 h-4" />
                保存配置
              </>
            )}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════
// 主组件
// ═══════════════════════════════════════════════════════════════

export const ExchangeConfigPanel: React.FC = () => {
  const [configs, setConfigs] = useState<ExchangeConfig[]>([]);
  const [exchanges, setExchanges] = useState<ExchangeInfo[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [validating, setValidating] = useState<string | null>(null);
  const { showNotification } = useNotifications();

  // 加载配置
  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const [configsData, exchangesData] = await Promise.all([
        exchangeConfigService.getConfigs(),
        exchangeConfigService.getSupportedExchanges()
      ]);
      setConfigs(configsData);
      setExchanges(exchangesData);
    } catch (error) {
      showNotification({
        type: 'error',
        title: '加载失败',
        message: '无法加载交易所配置'
      });
    } finally {
      setLoading(false);
    }
  };

  // 添加配置
  const handleAddConfig = async (config: ExchangeConfigInput) => {
    try {
      setSubmitting(true);
      await exchangeConfigService.createConfig(config);
      showNotification({
        type: 'success',
        title: '添加成功',
        message: '交易所配置已保存'
      });
      setIsModalOpen(false);
      loadData();
    } catch (error: any) {
      showNotification({
        type: 'error',
        title: '添加失败',
        message: error.response?.data?.detail || '保存配置失败'
      });
    } finally {
      setSubmitting(false);
    }
  };

  // 删除配置
  const handleDelete = async (id: string) => {
    if (!confirm('确定要删除这个配置吗？')) return;

    try {
      await exchangeConfigService.deleteConfig(id);
      showNotification({
        type: 'success',
        title: '删除成功',
        message: '配置已删除'
      });
      loadData();
    } catch (error) {
      showNotification({
        type: 'error',
        title: '删除失败',
        message: '无法删除配置'
      });
    }
  };

  // 验证配置
  const handleValidate = async (id: string) => {
    try {
      setValidating(id);
      const result = await exchangeConfigService.validateConfig(id);
      if (result.valid) {
        showNotification({
          type: 'success',
          title: '验证成功',
          message: result.message
        });
      } else {
        showNotification({
          type: 'warning',
          title: '验证失败',
          message: result.message
        });
      }
      loadData();
    } catch (error) {
      showNotification({
        type: 'error',
        title: '验证失败',
        message: '无法验证配置'
      });
    } finally {
      setValidating(null);
    }
  };

  // 激活配置
  const handleActivate = async (id: string) => {
    try {
      await exchangeConfigService.activateConfig(id);
      showNotification({
        type: 'success',
        title: '激活成功',
        message: '该配置已设为默认'
      });
      loadData();
    } catch (error) {
      showNotification({
        type: 'error',
        title: '激活失败',
        message: '无法激活配置'
      });
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw className="w-8 h-8 text-blue-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 标题栏 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shield className="w-6 h-6 text-blue-400" />
          <div>
            <h2 className="text-xl font-semibold text-white">交易所配置</h2>
            <p className="text-sm text-gray-400">管理您的交易所API密钥和交易模式</p>
          </div>
        </div>
        <button
          onClick={() => setIsModalOpen(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 
                   rounded-lg text-white font-medium transition-colors"
        >
          <Plus className="w-4 h-4" />
          添加配置
        </button>
      </div>

      {/* 当前模式 */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center gap-2 text-gray-400 text-sm mb-1">
            <Activity className="w-4 h-4" />
            当前模式
          </div>
          <div className="text-2xl font-bold text-white">
            {configs.some((c) => c.mode === 'live' && c.is_active)
              ? '实盘交易'
              : '模拟盘交易'}
          </div>
          <div className="text-sm text-gray-400 mt-1">
            {configs.some((c) => c.mode === 'live' && c.is_active)
              ? '使用真实资金进行交易'
              : '零风险模拟交易环境'}
          </div>
        </div>

        <div className="bg-gray-800 rounded-xl border border-gray-700 p-4">
          <div className="flex items-center gap-2 text-gray-400 text-sm mb-1">
            <Server className="w-4 h-4" />
            已配置交易所
          </div>
          <div className="text-2xl font-bold text-white">{configs.length}</div>
          <div className="text-sm text-gray-400 mt-1">
            {configs.filter((c) => c.is_active).length} 个活跃配置
          </div>
        </div>
      </div>

      {/* 配置列表 */}
      <div className="space-y-3">
        <h3 className="text-lg font-medium text-white">我的配置</h3>

        {configs.length === 0 ? (
          <div className="text-center py-12 bg-gray-800/50 rounded-xl border border-gray-700 border-dashed">
            <Shield className="w-12 h-12 text-gray-600 mx-auto mb-4" />
            <h4 className="text-white font-medium mb-2">暂无交易所配置</h4>
            <p className="text-gray-400 text-sm mb-4">
              添加交易所配置以启用真实交易功能
            </p>
            <button
              onClick={() => setIsModalOpen(true)}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-white text-sm font-medium transition-colors"
            >
              添加第一个配置
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {configs.map((config) => (
              <ConfigCard
                key={config.id}
                config={config}
                onDelete={handleDelete}
                onValidate={handleValidate}
                onActivate={handleActivate}
                validating={validating === config.id}
              />
            ))}
          </div>
        )}
      </div>

      {/* 添加配置弹窗 */}
      <AddConfigModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSubmit={handleAddConfig}
        exchanges={exchanges}
        loading={submitting}
      />
    </div>
  );
};

export default ExchangeConfigPanel;
