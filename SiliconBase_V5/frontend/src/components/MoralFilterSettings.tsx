/**
 * 道德过滤设置组件
 * 
 * 功能：
 * - 实时获取道德过滤配置
 * - 热加载修改（无需重启后端）
 * - 测试阶段推荐配置一键应用
 */
import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { 
  Shield, ShieldOff, Save, RotateCcw, AlertTriangle, 
  Info, Sliders, Filter
} from 'lucide-react';
import { useNotifications } from '../hooks/useNotifications';
import { fetchAPI } from '../utils/api';

// 道德过滤配置接口
interface MoralFilterConfig {
  enabled: boolean;
  strict_mode: boolean;
  min_moral_score: number;
  filter_success_exp: boolean;
  filter_failure_exp: boolean;
}

// 默认配置
const defaultConfig: MoralFilterConfig = {
  enabled: true,
  strict_mode: false,
  min_moral_score: 0.5,
  filter_success_exp: false,
  filter_failure_exp: true,
};

// 预设配置
const presets = {
  disabled: {
    name: '完全禁用',
    description: '关闭所有道德过滤，保留所有经验',
    config: {
      enabled: false,
      strict_mode: false,
      min_moral_score: 0.0,
      filter_success_exp: false,
      filter_failure_exp: false,
    } as MoralFilterConfig,
  },
  testing: {
    name: '测试阶段',
    description: '宽松模式，成功经验不过滤',
    config: {
      enabled: true,
      strict_mode: false,
      min_moral_score: 0.1,
      filter_success_exp: false,
      filter_failure_exp: false,
    } as MoralFilterConfig,
  },
  normal: {
    name: '正常模式',
    description: '平衡安全和实用性',
    config: {
      enabled: true,
      strict_mode: false,
      min_moral_score: 0.5,
      filter_success_exp: false,
      filter_failure_exp: true,
    } as MoralFilterConfig,
  },
  strict: {
    name: '严格模式',
    description: '最高安全级别，过滤所有可疑经验',
    config: {
      enabled: true,
      strict_mode: true,
      min_moral_score: 0.8,
      filter_success_exp: true,
      filter_failure_exp: true,
    } as MoralFilterConfig,
  },
};

export function MoralFilterSettings() {
  const [config, setConfig] = useState<MoralFilterConfig>(defaultConfig);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { showNotification } = useNotifications();

  // 加载配置
  const loadConfig = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      const result = await fetchAPI<{ success: boolean; data: MoralFilterConfig; error?: string }>('/api/config/moral-filter');
      
      if (result.success && result.data) {
        setConfig(result.data);
      } else {
        throw new Error(result.error || '获取配置失败');
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : '加载配置失败';
      setError(errorMsg);
      showNotification({
        type: 'error',
        title: '加载失败',
        message: errorMsg,
        duration: 3000,
      });
    } finally {
      setLoading(false);
    }
  }, [showNotification]);

  // 保存配置
  const saveConfig = async () => {
    try {
      setSaving(true);
      setError(null);
      
      const result = await fetchAPI<{ success: boolean; message: string; error?: string }>(
        '/api/config/moral-filter',
        {
          method: 'PUT',
          body: config,
        }
      );
      
      if (result.success) {
        showNotification({
          type: 'success',
          title: '保存成功',
          message: '道德过滤配置已更新并生效（热加载）',
          duration: 3000,
        });
      } else {
        throw new Error(result.error || '保存失败');
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : '保存配置失败';
      setError(errorMsg);
      showNotification({
        type: 'error',
        title: '保存失败',
        message: errorMsg,
        duration: 3000,
      });
    } finally {
      setSaving(false);
    }
  };

  // 重置配置
  const resetConfig = async () => {
    try {
      setSaving(true);
      setError(null);
      
      const result = await fetchAPI<{ success: boolean; data: MoralFilterConfig; error?: string }>(
        '/api/config/moral-filter/reset',
        {
          method: 'POST',
        }
      );
      
      if (result.success && result.data) {
        setConfig(result.data);
        showNotification({
          type: 'success',
          title: '重置成功',
          message: '道德过滤配置已恢复默认值',
          duration: 3000,
        });
      } else {
        throw new Error(result.error || '重置失败');
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : '重置配置失败';
      setError(errorMsg);
      showNotification({
        type: 'error',
        title: '重置失败',
        message: errorMsg,
        duration: 3000,
      });
    } finally {
      setSaving(false);
    }
  };

  // 应用预设
  const applyPreset = (presetConfig: MoralFilterConfig) => {
    setConfig(presetConfig);
    showNotification({
      type: 'info',
      title: '预设已应用',
      message: '点击保存按钮使配置生效',
      duration: 2000,
    });
  };

  // 组件加载时获取配置
  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  // 开关组件
  const Toggle = ({ 
    label, 
    description, 
    checked, 
    onChange,
    icon: Icon
  }: { 
    label: string;
    description?: string;
    checked: boolean;
    onChange: (checked: boolean) => void;
    icon?: React.ElementType;
  }) => (
    <div className="flex items-center justify-between p-4 bg-white/5 rounded-lg">
      <div className="flex items-center gap-3">
        {Icon && <Icon className="w-5 h-5 text-blue-400" />}
        <div>
          <div className="font-medium text-white">{label}</div>
          {description && (
            <div className="text-sm text-gray-400">{description}</div>
          )}
        </div>
      </div>
      <button
        onClick={() => onChange(!checked)}
        className={`relative w-14 h-7 rounded-full transition-colors ${
          checked ? 'bg-green-500' : 'bg-gray-600'
        }`}
      >
        <motion.div
          className="absolute top-1 w-5 h-5 bg-white rounded-full"
          animate={{ left: checked ? '32px' : '4px' }}
          transition={{ type: 'spring', stiffness: 500, damping: 30 }}
        />
      </button>
    </div>
  );

  // 滑块组件
  const Slider = ({ 
    label, 
    description, 
    value, 
    onChange,
    min = 0,
    max = 1,
    step = 0.1,
  }: { 
    label: string;
    description?: string;
    value: number;
    onChange: (value: number) => void;
    min?: number;
    max?: number;
    step?: number;
  }) => (
    <div className="p-4 bg-white/5 rounded-lg">
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="font-medium text-white">{label}</div>
          {description && (
            <div className="text-sm text-gray-400">{description}</div>
          )}
        </div>
        <span className="px-2 py-1 bg-blue-500/20 text-blue-400 rounded text-sm font-mono">
          {value.toFixed(1)}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
      />
      <div className="flex justify-between text-xs text-gray-500 mt-1">
        <span>宽松 ({min})</span>
        <span>严格 ({max})</span>
      </div>
    </div>
  );

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-6"
    >
      {/* 标题 */}
      <div className="flex items-center gap-3 pb-4 border-b border-white/10">
        <Shield className="w-6 h-6 text-blue-400" />
        <div>
          <h2 className="text-xl font-bold text-white">道德过滤设置</h2>
          <p className="text-sm text-gray-400">
            控制经验过滤的严格程度，支持热加载（无需重启）
          </p>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          className="p-4 bg-red-500/20 border border-red-500/30 rounded-lg flex items-center gap-3"
        >
          <AlertTriangle className="w-5 h-5 text-red-400" />
          <span className="text-red-200">{error}</span>
        </motion.div>
      )}

      {/* 预设配置 */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
          <Sliders className="w-4 h-4" />
          快速预设
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Object.entries(presets).map(([key, preset]) => (
            <button
              key={key}
              onClick={() => applyPreset(preset.config)}
              className="p-3 bg-white/5 hover:bg-white/10 border border-white/10 hover:border-blue-500/30 rounded-lg text-left transition-all"
            >
              <div className="font-medium text-white text-sm">{preset.name}</div>
              <div className="text-xs text-gray-400 mt-1">{preset.description}</div>
            </button>
          ))}
        </div>
      </div>

      {/* 主开关 */}
      <Toggle
        label="启用道德过滤"
        description="关闭后将保留所有经验，包括可能包含危险操作的经验"
        checked={config.enabled}
        onChange={(checked) => setConfig({ ...config, enabled: checked })}
        icon={config.enabled ? Shield : ShieldOff}
      />

      {/* 详细设置 */}
      {config.enabled && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          className="space-y-4"
        >
          <h3 className="text-sm font-medium text-gray-300 flex items-center gap-2">
            <Filter className="w-4 h-4" />
            详细设置
          </h3>

          <Toggle
            label="严格模式"
            description="实时检查经验内容，可能降低系统性能"
            checked={config.strict_mode}
            onChange={(checked) => setConfig({ ...config, strict_mode: checked })}
          />

          <Slider
            label="最低道德分数"
            description="分数越低，保留的经验越多（0-1）"
            value={config.min_moral_score}
            onChange={(value) => setConfig({ ...config, min_moral_score: value })}
            min={0}
            max={1}
            step={0.1}
          />

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Toggle
              label="过滤成功经验"
              description="测试阶段建议关闭，保留成功操作经验"
              checked={config.filter_success_exp}
              onChange={(checked) => setConfig({ ...config, filter_success_exp: checked })}
            />

            <Toggle
              label="过滤失败经验"
              description="建议开启，避免AI学习错误操作"
              checked={config.filter_failure_exp}
              onChange={(checked) => setConfig({ ...config, filter_failure_exp: checked })}
            />
          </div>
        </motion.div>
      )}

      {/* 操作按钮 */}
      <div className="flex items-center justify-end gap-3 pt-4 border-t border-white/10">
        <button
          onClick={resetConfig}
          disabled={saving || loading}
          className="flex items-center gap-2 px-4 py-2 text-gray-400 hover:text-white disabled:opacity-50 transition-colors"
        >
          <RotateCcw className="w-4 h-4" />
          重置默认
        </button>
        <button
          onClick={loadConfig}
          disabled={saving || loading}
          className="flex items-center gap-2 px-4 py-2 text-gray-400 hover:text-white disabled:opacity-50 transition-colors"
        >
          <Info className="w-4 h-4" />
          刷新
        </button>
        <button
          onClick={saveConfig}
          disabled={saving || loading}
          className="flex items-center gap-2 px-6 py-2 bg-blue-500 hover:bg-blue-600 disabled:bg-gray-600 text-white rounded-lg transition-colors"
        >
          {saving ? (
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
            >
              <Save className="w-4 h-4" />
            </motion.div>
          ) : (
            <Save className="w-4 h-4" />
          )}
          {saving ? '保存中...' : '保存配置'}
        </button>
      </div>

      {/* 提示信息 */}
      <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-lg">
        <div className="flex items-start gap-3">
          <Info className="w-5 h-5 text-blue-400 mt-0.5" />
          <div className="text-sm text-gray-300 space-y-1">
            <p>
              <span className="text-blue-400 font-medium">热加载：</span>
              配置修改后立即生效，无需重启后端服务
            </p>
            <p>
              <span className="text-blue-400 font-medium">测试阶段建议：</span>
              使用"测试阶段"预设，保留所有成功经验
            </p>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

export default MoralFilterSettings;
