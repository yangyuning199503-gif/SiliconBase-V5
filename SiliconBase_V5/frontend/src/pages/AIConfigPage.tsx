import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Bot, Save, CheckCircle, AlertCircle, 
  Cloud, Server, Settings, TestTube, ChevronDown, ChevronUp,
  Eye, Image, Sparkles
} from 'lucide-react';
import { aiConfigService, AIProviderInfo, AIProviderConfig } from '../services/aiConfig';
import { configAPI, getNestedValue } from '../utils/api/config';

// 提供商分组配置
const PROVIDER_GROUPS = {
  cloud: {
    label: '云端商业API',
    icon: Cloud,
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10',
    borderColor: 'border-blue-500/30'
  },
  local: {
    label: '本地部署方案',
    icon: Server,
    color: 'text-green-400',
    bgColor: 'bg-green-500/10',
    borderColor: 'border-green-500/30'
  },
  other: {
    label: '其他',
    icon: Settings,
    color: 'text-gray-400',
    bgColor: 'bg-gray-500/10',
    borderColor: 'border-gray-500/30'
  }
};

// 内置常用模型列表（当后端未返回时作为兜底）
const BUILTIN_MODELS: Record<string, string[]> = {
  openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'o1-preview', 'o1-mini'],
  anthropic: ['claude-3-5-sonnet-20241022', 'claude-3-opus-20240229', 'claude-3-haiku-20240307'],
  deepseek: ['deepseek-chat', 'deepseek-reasoner'],
};

const getModelOptions = (providerType: string, providerInfo?: AIProviderInfo) => {
  if (providerInfo?.models && providerInfo.models.length > 0) {
    return providerInfo.models;
  }
  return BUILTIN_MODELS[providerType] || [];
};

// 预设模板（预留功能）
// const PRESET_TEMPLATES: Record<string, { model: string; temperature: number; maxTokens: number }> = {
//   'deepseek-chat': { model: 'deepseek-chat', temperature: 0.7, maxTokens: 2048 },
//   'deepseek-coder': { model: 'deepseek-coder', temperature: 0.1, maxTokens: 4096 },
//   'kimi-8k': { model: 'moonshot-v1-8k', temperature: 0.7, maxTokens: 8192 },
//   'kimi-128k': { model: 'moonshot-v1-128k', temperature: 0.7, maxTokens: 128000 },
//   'qwen-turbo': { model: 'qwen-turbo', temperature: 0.7, maxTokens: 2048 },
//   'qwen-max': { model: 'qwen-max', temperature: 0.7, maxTokens: 8192 },
//   'glm-4': { model: 'glm-4', temperature: 0.7, maxTokens: 8192 },
//   'doubao-pro': { model: 'doubao-pro-32k', temperature: 0.7, maxTokens: 32768 },
// };

export const AIConfigPage: React.FC = () => {
  // 主AI配置状态
  const [providers, setProviders] = useState<AIProviderInfo[]>([]);
  const [currentProvider, setCurrentProvider] = useState<string>('ollama');
  const [config, setConfig] = useState<AIProviderConfig>({});
  const [isLoading, setIsLoading] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [saveErrorMsg, setSaveErrorMsg] = useState<string | null>(null);
  const [saveApiKey, setSaveApiKey] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);
  const [pageLoading, setPageLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mainModelManual, setMainModelManual] = useState(false);
  const [visionModelManual, setVisionModelManual] = useState(false);

  // 视觉模型配置状态
  const [visionProvider, setVisionProvider] = useState<string>('ollama');
  const [visionConfig, setVisionConfig] = useState<AIProviderConfig>({
    model: '',
    api_key: '',
    base_url: ''
  });
  const [saveVisionStatus, setSaveVisionStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [saveVisionErrorMsg, setSaveVisionErrorMsg] = useState<string | null>(null);
  const [isSavingVision, setIsSavingVision] = useState(false);
  const [visionSaveApiKey, setVisionSaveApiKey] = useState(false);
  const [visionEnabled, setVisionEnabled] = useState(true);
  const [visionLearningEnabled, setVisionLearningEnabled] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  // 当providers加载完成后，默认展开第一个分组
  useEffect(() => {
    if (providers.length > 0 && expandedGroup === null) {
      const firstCategory = getFirstNonEmptyCategory();
      if (firstCategory) {
        setExpandedGroup(firstCategory);
      }
    }
  }, [providers]);

  const loadData = async () => {
    try {
      setPageLoading(true);
      setLoadError(null);
      const [providersData, currentData, visionData, yamlConfig] = await Promise.all([
        aiConfigService.getProviders(),
        aiConfigService.getCurrentConfig(),
        aiConfigService.getVisionConfig(),
        configAPI.getYamlConfig().catch(() => ({ content: '', parsed: {} }))
      ]);
      
      // 确保数据有效
      if (!Array.isArray(providersData)) {
        throw new Error('提供商数据格式错误');
      }
      
      setProviders(providersData);
      
      // 设置当前提供商，确保它是有效的
      const validProvider = providersData.find(p => p.type === currentData.provider);
      if (validProvider) {
        setCurrentProvider(currentData.provider);
      } else if (providersData.length > 0) {
        setCurrentProvider(providersData[0].type);
      }
      
      // 设置配置，确保是对象
      setConfig(currentData.config || {});

      // 加载视觉配置（从独立的视觉配置端点获取）
      if (visionData && visionData.configured !== false) {
        // 后端格式: { default_backend, backends: { [name]: {...} } }
        const defaultBackend = visionData.default_backend;
        const backends = visionData.backends || {};
        
        if (defaultBackend && backends[defaultBackend]) {
          const backendConfig = backends[defaultBackend];
          // 设置视觉提供商
          if (backendConfig.provider) {
            const validVisionProvider = providersData.find(p => p.type === backendConfig.provider);
            if (validVisionProvider) {
              setVisionProvider(backendConfig.provider);
            }
          }
          // 设置视觉配置
          setVisionConfig({
            model: backendConfig.model || '',
            api_key: backendConfig.api_key || '',
            base_url: backendConfig.base_url || ''
          });
        }
        // 兼容旧格式: { provider, config }
        else if ((visionData as any).provider) {
          const legacyData = visionData as any;
          const validVisionProvider = providersData.find(p => p.type === legacyData.provider);
          if (validVisionProvider) {
            setVisionProvider(legacyData.provider);
          }
          if (legacyData.config) {
            setVisionConfig({
              model: legacyData.config.model || '',
              api_key: legacyData.config.api_key || '',
              base_url: legacyData.config.base_url || ''
            });
          }
        }
      }

      // 加载感知/学习开关（从global.yaml读取）
      if (yamlConfig?.parsed) {
        setVisionEnabled(getNestedValue(yamlConfig.parsed, 'perception.vision_enabled') ?? true);
        setVisionLearningEnabled(getNestedValue(yamlConfig.parsed, 'perception.learning_enabled') ?? false);
      }
    } catch (error) {
      console.error('加载失败:', error);
      setLoadError(error instanceof Error ? error.message : '加载配置失败');
    } finally {
      setPageLoading(false);
    }
  };

  const handleProviderChange = (provider: string) => {
    setCurrentProvider(provider);
    // 不要完全清空配置，保留 base_url 和 model 的默认值
    const providerInfo = providers.find(p => p.type === provider);
    setConfig({
      model: providerInfo?.default_model || '',
      timeout: 30,
      temperature: 0.7
    });
    setTestResult(null);
    setAvailableModels([]);
    setMainModelManual(false);
  };

  // 预设模板功能预留
  // const handleApplyPreset = (presetKey: string) => {
  //   const preset = PRESET_TEMPLATES[presetKey];
  //   if (preset) {
  //     setConfig(prev => ({
  //       ...prev,
  //       model: preset.model,
  //       temperature: preset.temperature,
  //       max_tokens: preset.maxTokens
  //     }));
  //   }
  // };

  const loadAvailableModels = async () => {
    if (currentProvider !== 'ollama') return;
    setIsLoadingModels(true);
    try {
      const models = await aiConfigService.getModels(currentProvider);
      setAvailableModels(models);
    } catch (error) {
      console.error('加载模型列表失败:', error);
    } finally {
      setIsLoadingModels(false);
    }
  };

  const handleTest = async () => {
    setIsLoading(true);
    setTestResult(null);
    try {
      const result = await aiConfigService.testConfig(currentProvider, config);
      setTestResult(result);
    } catch (error) {
      setTestResult({ 
        success: false, 
        message: error instanceof Error ? error.message : '测试失败',
        error: error instanceof Error ? error.message : String(error)
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    setIsLoading(true);
    setSaveErrorMsg(null);
    try {
      const result = await aiConfigService.updateConfig(currentProvider, config, {
        persist: true,
        saveApiKey
      });
      if (result.success) {
        setSaveStatus('success');
        // 保存成功后重新加载配置，确保显示最新状态
        await loadData();
        setTimeout(() => setSaveStatus('idle'), 3000);
      } else {
        setSaveStatus('error');
        setSaveErrorMsg(result.message || '保存失败，请检查配置');
      }
    } catch (error) {
      setSaveStatus('error');
      setSaveErrorMsg(error instanceof Error ? error.message : '保存失败，请检查配置');
    } finally {
      setIsLoading(false);
    }
  };

  // 保存视觉配置
  const handleSaveVision = async () => {
    setIsSavingVision(true);
    setSaveVisionStatus('idle');
    setSaveVisionErrorMsg(null);
    try {
      // 构建后端期望的格式: { default_backend, backends: {} }
      const backendName = `${visionProvider}-vision`;
      const visionBackendConfig = {
        default_backend: backendName,
        backends: {
          [backendName]: {
            name: `${visionProvider} Vision`,
            model: visionConfig.model || '',
            provider: visionProvider,
            base_url: visionConfig.base_url || '',
            api_key: visionConfig.api_key || '',
            capabilities: ['description', 'qa', 'ocr', 'gui_action'],
            supports_vision: true
          }
        }
      };

      const result = await aiConfigService.updateConfig(currentProvider, config, {
        persist: true,
        saveApiKey: visionSaveApiKey,
        vision: visionBackendConfig
      });

      // 【P0修复】同步保存视觉感知/学习开关（已解耦）
      await configAPI.updateConfig({
        'perception.vision_enabled': visionEnabled,
        'perception.learning_enabled': visionLearningEnabled
      } as any);

      if (result.success) {
        setSaveVisionStatus('success');
        setTimeout(() => setSaveVisionStatus('idle'), 3000);
      } else {
        setSaveVisionStatus('error');
        setSaveVisionErrorMsg(result.message || '保存视觉配置失败');
      }
    } catch (error) {
      console.error('保存视觉配置失败:', error);
      setSaveVisionStatus('error');
      setSaveVisionErrorMsg(error instanceof Error ? error.message : '保存视觉配置失败');
    } finally {
      setIsSavingVision(false);
    }
  };

  // 统一保存所有配置
  const handleSaveAll = async () => {
    await handleSave();
    await handleSaveVision();
  };

  // 按分组组织提供商
  const groupedProviders = providers.reduce((acc, provider) => {
    const category = provider.category || 'other';
    if (!acc[category]) acc[category] = [];
    acc[category].push(provider);
    return acc;
  }, {} as Record<string, AIProviderInfo[]>);

  // 获取第一个非空分组的类别
  const getFirstNonEmptyCategory = () => {
    for (const [category, groupProviders] of Object.entries(groupedProviders)) {
      if (groupProviders.length > 0) return category;
    }
    return null;
  };

  // 获取提供商信息
  const getProviderInfo = (providerType: string) => {
    return providers.find(p => p.type === providerType);
  };

  const renderConfigForm = () => {
    const providerInfo = providers.find(p => p.type === currentProvider);
    if (!providerInfo) return null;

    return (
      <div className="space-y-4">
        {/* 预设模板快速选择 */}
        {providerInfo.models && providerInfo.models.length > 0 && (
          <div className="bg-sb-bg-secondary/50 p-4 rounded-lg border border-white/5">
            <label className="block text-sm font-medium text-sb-text-primary mb-2">
              快速选择模型
            </label>
            <div className="flex flex-wrap gap-2">
              {providerInfo.models.map(model => (
                <button
                  key={model}
                  onClick={() => setConfig(prev => ({ ...prev, model }))}
                  className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                    config.model === model
                      ? 'bg-sb-cyan/20 text-sb-cyan border border-sb-cyan/50'
                      : 'bg-sb-bg-secondary/50 text-sb-text-primary border border-transparent hover:bg-sb-bg-secondary'
                  }`}
                >
                  {model}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* API Key */}
        {providerInfo.required_config?.includes('api_key') && (
          <div>
            <label className="block text-sm font-medium text-sb-text-primary mb-2">
              API Key <span className="text-red-400">*</span>
            </label>
            <input
              type="password"
              value={config.api_key || ''}
              onChange={(e) => setConfig({ ...config, api_key: e.target.value })}
              className="w-full px-4 py-2 bg-sb-bg-secondary border border-sb-border/30 rounded-lg text-white 
                         placeholder-sb-text-secondary focus:outline-none focus:border-sb-cyan/50"
              placeholder="sk-..."
            />
          </div>
        )}

        {/* Base URL */}
        <div>
          <label className="block text-sm font-medium text-sb-text-primary mb-2">
            API 地址 {providerInfo.required_config?.includes('base_url') && <span className="text-red-400">*</span>}
          </label>
          <input
            type="text"
            value={config.base_url || ''}
            onChange={(e) => setConfig({ ...config, base_url: e.target.value })}
            className="w-full px-4 py-2 bg-sb-bg-secondary border border-sb-border/30 rounded-lg text-white 
                       placeholder-sb-text-secondary focus:outline-none focus:border-sb-cyan/50"
            placeholder={
              currentProvider === 'ollama' 
                ? 'http://localhost:11434' 
                : currentProvider === 'vllm' 
                  ? 'http://localhost:8000/v1'
                  : currentProvider === 'llamacpp'
                    ? 'http://localhost:8080/v1'
                    : 'https://api.example.com/v1'
            }
          />
        </div>

        {/* Model */}
        <div>
          <label className="block text-sm font-medium text-sb-text-primary mb-2">
            模型 <span className="text-red-400">*</span>
          </label>
          <div className="flex gap-2 items-center">
            {mainModelManual ? (
              <input
                type="text"
                value={config.model || ''}
                onChange={(e) => setConfig({ ...config, model: e.target.value })}
                className="flex-1 px-4 py-2 bg-sb-bg-secondary border border-sb-border/30 rounded-lg text-white
                           placeholder-sb-text-secondary focus:outline-none focus:border-sb-cyan/50"
                placeholder={providerInfo.default_model || 'gpt-4'}
                list="available-models"
              />
            ) : (
              <select
                value={config.model || ''}
                onChange={(e) => setConfig({ ...config, model: e.target.value })}
                className="flex-1 px-4 py-2 bg-sb-bg-secondary border border-sb-border/30 rounded-lg text-white
                           focus:outline-none focus:border-sb-cyan/50 appearance-none cursor-pointer"
              >
                <option value="">请选择模型</option>
                {getModelOptions(currentProvider, providerInfo).map((model) => (
                  <option key={model} value={model}>{model}</option>
                ))}
                {availableModels.map((model) => (
                  <option key={model} value={model}>{model}</option>
                ))}
              </select>
            )}
            <label className="flex items-center gap-1.5 text-xs text-sb-text-secondary cursor-pointer whitespace-nowrap select-none">
              <input
                type="checkbox"
                checked={mainModelManual}
                onChange={(e) => setMainModelManual(e.target.checked)}
                className="rounded border-white/20 bg-sb-bg-secondary text-sb-cyan focus:ring-sb-cyan"
              />
              手动输入
            </label>
            {currentProvider === 'ollama' && (
              <button
                onClick={loadAvailableModels}
                disabled={isLoadingModels}
                className="px-4 py-2 bg-sb-bg-secondary text-sb-text-secondary rounded-lg hover:bg-sb-bg-secondary/80
                           disabled:opacity-50 transition-colors text-sm"
              >
                {isLoadingModels ? '加载中...' : '获取列表'}
              </button>
            )}
          </div>
          <datalist id="available-models">
            {availableModels.map((model) => (
              <option key={model} value={model} />
            ))}
          </datalist>
        </div>

        {/* 高级参数 */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-sb-text-primary mb-2">
              Temperature
            </label>
            <input
              type="number"
              min="0"
              max="2"
              step="0.1"
              value={config.temperature || 0.7}
              onChange={(e) => setConfig({ ...config, temperature: parseFloat(e.target.value) })}
              className="w-full px-4 py-2 bg-sb-bg-secondary border border-sb-border/30 rounded-lg text-white
                         focus:outline-none focus:border-sb-cyan/50"
            />
            <p className="text-xs text-sb-text-secondary mt-1.5">
              控制AI回复的创造性。较低值(0.1-0.3)回复更确定，较高值(0.7-1.0)回复更随机。
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-sb-text-primary mb-2">
              Max Tokens
            </label>
            <input
              type="number"
              min="256"
              max="8192"
              step="1"
              value={config.max_tokens || 2048}
              onChange={(e) => setConfig({ ...config, max_tokens: parseInt(e.target.value) })}
              placeholder="2048"
              className="w-full px-4 py-2 bg-sb-bg-secondary border border-sb-border/30 rounded-lg text-white
                         focus:outline-none focus:border-sb-cyan/50"
            />
            <p className="text-xs text-sb-text-secondary mt-1.5">
              限制AI回复的最大Token数量，0表示不限制。
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-sb-text-primary mb-2">
              超时时间(秒)
            </label>
            <input
              type="number"
              min="1"
              max="300"
              value={config.timeout || 30}
              onChange={(e) => setConfig({ ...config, timeout: parseInt(e.target.value) })}
              className="w-full px-4 py-2 bg-sb-bg-secondary border border-sb-border/30 rounded-lg text-white
                         focus:outline-none focus:border-sb-cyan/50"
            />
          </div>
        </div>
      </div>
    );
  };

  // 渲染视觉配置表单
  const renderVisionConfigForm = () => {
    const providerInfo = getProviderInfo(visionProvider);
    const needsApiKey = providerInfo?.required_config?.includes('api_key') ?? false;

    return (
      <div className="space-y-4">
        {/* 视觉感知开关：决策时看屏幕 */}
        <div className="flex items-start gap-3 p-3 rounded-lg bg-sb-bg-secondary/50 border border-sb-border/20">
          <input
            id="vision-perception-enabled"
            type="checkbox"
            checked={visionEnabled}
            onChange={(e) => setVisionEnabled(e.target.checked)}
            className="mt-0.5 w-5 h-5 rounded border-white/20 bg-sb-bg-secondary text-sb-cyan focus:ring-sb-cyan cursor-pointer"
          />
          <div className="flex-1">
            <label htmlFor="vision-perception-enabled" className="block text-sm font-medium text-sb-text-primary cursor-pointer">
              启用视觉感知
            </label>
            <p className="text-xs text-sb-text-secondary mt-0.5">
              决策前自动截图并用视觉模型理解屏幕，让AI能“看到”当前界面并正确操作。
            </p>
          </div>
        </div>

        {/* 视觉学习开关：后台标注/训练 */}
        <div className="flex items-start gap-3 p-3 rounded-lg bg-sb-bg-secondary/50 border border-sb-border/20">
          <input
            id="vision-learning-enabled"
            type="checkbox"
            checked={visionLearningEnabled}
            onChange={(e) => setVisionLearningEnabled(e.target.checked)}
            className="mt-0.5 w-5 h-5 rounded border-white/20 bg-sb-bg-secondary text-sb-cyan focus:ring-sb-cyan cursor-pointer"
          />
          <div className="flex-1">
            <label htmlFor="vision-learning-enabled" className="block text-sm font-medium text-sb-text-primary cursor-pointer">
              启用视觉学习
            </label>
            <p className="text-xs text-sb-text-secondary mt-0.5">
              后台自动标注未知UI元素并积累训练样本，会增加视觉模型调用和GPU占用。
            </p>
          </div>
        </div>

        {/* Provider选择 - 下拉框 */}
        <div>
          <label className="block text-sm font-medium text-sb-text-primary mb-2">
            Provider <span className="text-red-400">*</span>
          </label>
          <select
            value={visionProvider}
            onChange={(e) => {
              const newProvider = e.target.value;
              setVisionProvider(newProvider);
              // 切换到新provider时，保留现有配置但清空model
              const newProviderInfo = getProviderInfo(newProvider);
              setVisionConfig(prev => ({
                ...prev,
                model: newProviderInfo?.default_model || '',
                base_url: ''
              }));
              setVisionModelManual(false);
            }}
            className="w-full px-4 py-2 bg-sb-bg-secondary border border-sb-border/30 rounded-lg text-white 
                       focus:outline-none focus:border-sb-cyan/50 appearance-none cursor-pointer"
          >
            {providers.map(p => (
              <option key={p.type} value={p.type}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {/* 模型名称 */}
        <div>
          <label className="block text-sm font-medium text-sb-text-primary mb-2">
            模型名称 <span className="text-red-400">*</span>
          </label>
          <div className="flex gap-2 items-center">
            {visionModelManual ? (
              <input
                type="text"
                value={visionConfig.model || ''}
                onChange={(e) => setVisionConfig({ ...visionConfig, model: e.target.value })}
                className="flex-1 px-4 py-2 bg-sb-bg-secondary border border-sb-border/30 rounded-lg text-white
                           placeholder-sb-text-secondary focus:outline-none focus:border-sb-cyan/50"
                placeholder="如: gpt-4o, claude-3-opus, llava"
              />
            ) : (
              <select
                value={visionConfig.model || ''}
                onChange={(e) => setVisionConfig({ ...visionConfig, model: e.target.value })}
                className="flex-1 px-4 py-2 bg-sb-bg-secondary border border-sb-border/30 rounded-lg text-white
                           focus:outline-none focus:border-sb-cyan/50 appearance-none cursor-pointer"
              >
                <option value="">请选择模型</option>
                {getModelOptions(visionProvider, providerInfo).map((model) => (
                  <option key={model} value={model}>{model}</option>
                ))}
              </select>
            )}
            <label className="flex items-center gap-1.5 text-xs text-sb-text-secondary cursor-pointer whitespace-nowrap select-none">
              <input
                type="checkbox"
                checked={visionModelManual}
                onChange={(e) => setVisionModelManual(e.target.checked)}
                className="rounded border-white/20 bg-sb-bg-secondary text-sb-cyan focus:ring-sb-cyan"
              />
              手动输入
            </label>
          </div>
          {providerInfo?.models && providerInfo.models.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-2">
              {providerInfo.models.slice(0, 5).map(model => (
                <button
                  key={model}
                  onClick={() => setVisionConfig(prev => ({ ...prev, model }))}
                  className={`px-2 py-1 text-xs rounded transition-colors ${
                    visionConfig.model === model
                      ? 'bg-purple-500/20 text-purple-400 border border-purple-500/50'
                      : 'bg-sb-bg-secondary/50 text-sb-text-secondary border border-transparent hover:bg-sb-bg-secondary/80'
                  }`}
                >
                  {model}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* API Key - 条件显示 */}
        {needsApiKey && (
          <div>
            <label className="block text-sm font-medium text-sb-text-primary mb-2">
              API Key {needsApiKey && <span className="text-red-400">*</span>}
            </label>
            <input
              type="password"
              value={visionConfig.api_key || ''}
              onChange={(e) => setVisionConfig({ ...visionConfig, api_key: e.target.value })}
              className="w-full px-4 py-2 bg-sb-bg-secondary border border-sb-border/30 rounded-lg text-white 
                         placeholder-sb-text-secondary focus:outline-none focus:border-sb-cyan/50"
              placeholder="sk-..."
            />
          </div>
        )}

        {/* Base URL - 可选 */}
        <div>
          <label className="block text-sm font-medium text-sb-text-primary mb-2">
            Base URL <span className="text-sb-text-secondary">(可选)</span>
          </label>
          <input
            type="text"
            value={visionConfig.base_url || ''}
            onChange={(e) => setVisionConfig({ ...visionConfig, base_url: e.target.value })}
            className="w-full px-4 py-2 bg-sb-bg-secondary border border-sb-border/30 rounded-lg text-white 
                       placeholder-sb-text-secondary focus:outline-none focus:border-sb-cyan/50"
            placeholder={
              visionProvider === 'ollama' 
                ? 'http://localhost:11434' 
                : visionProvider === 'openai'
                  ? 'https://api.openai.com/v1'
                  : 'https://api.example.com/v1'
            }
          />
        </div>
      </div>
    );
  };

  // 加载中状态
  if (pageLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
          className="w-8 h-8 border-2 border-sb-cyan border-t-transparent rounded-full"
        />
      </div>
    );
  }

  // 错误状态
  if (loadError) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-6">
        <AlertCircle className="w-12 h-12 text-red-400 mb-4" />
        <h2 className="text-xl font-bold text-white mb-2">加载失败</h2>
        <p className="text-sb-text-secondary mb-4">{loadError}</p>
        <button
          onClick={loadData}
          className="px-4 py-2 bg-sb-cyan text-white rounded-lg hover:bg-sb-cyan/80 transition-colors"
        >
          重试
        </button>
      </div>
    );
  }

  // 无数据状态
  if (providers.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-6">
        <AlertCircle className="w-12 h-12 text-yellow-400 mb-4" />
        <h2 className="text-xl font-bold text-white mb-2">无可用提供商</h2>
        <p className="text-sb-text-secondary">后端未返回任何 AI 提供商配置</p>
      </div>
    );
  }

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="h-full overflow-auto p-6 max-w-4xl mx-auto pb-24"
    >
      <div className="flex items-center gap-3 mb-8">
        <div className="p-3 bg-gradient-to-br from-sb-cyan/20 to-sb-purple/20 rounded-xl">
          <Bot className="w-6 h-6 text-sb-cyan" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">AI 模型配置</h1>
          <p className="text-sb-text-secondary text-sm">配置您的 AI 后端，支持云端和本地部署方案</p>
        </div>
      </div>
      
      {/* Provider 分组选择 */}
      <div className="space-y-4 mb-8">
        {Object.entries(PROVIDER_GROUPS).map(([category, groupConfig]) => {
          const groupProviders = groupedProviders[category] || [];
          if (groupProviders.length === 0) return null;
          
          const Icon = groupConfig.icon;
          const isExpanded = expandedGroup === category;
          
          return (
            <div key={category} className={`rounded-xl border ${groupConfig.borderColor} overflow-hidden`}>
              <button
                onClick={() => setExpandedGroup(isExpanded ? null : category)}
                className={`w-full px-4 py-3 flex items-center justify-between ${groupConfig.bgColor}`}
              >
                <div className="flex items-center gap-3">
                  <Icon className={`w-5 h-5 ${groupConfig.color}`} />
                  <span className={`font-medium ${groupConfig.color}`}>{groupConfig.label}</span>
                  <span className="text-sb-text-secondary text-sm">({groupProviders.length})</span>
                </div>
                {isExpanded ? <ChevronUp className="w-5 h-5 text-sb-text-secondary" /> : <ChevronDown className="w-5 h-5 text-sb-text-secondary" />}
              </button>
              
              <AnimatePresence>
                {isExpanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.3, ease: 'easeInOut' }}
                    className="overflow-hidden"
                  >
                    <div className="p-4 bg-sb-bg-primary/50">
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                        {groupProviders.map(p => (
                          <button
                            key={p.type}
                            onClick={() => handleProviderChange(p.type)}
                            className={`p-4 rounded-lg border text-left transition-all ${
                              currentProvider === p.type 
                                ? 'border-sb-cyan bg-sb-cyan/10' 
                                : 'border-sb-border/30 bg-sb-bg-secondary/50 hover:border-sb-border/50'
                            }`}
                          >
                            <div className="font-medium text-white">{p.name}</div>
                            {p.description && (
                              <div className="text-xs text-sb-text-secondary mt-1 line-clamp-2">{p.description}</div>
                            )}
                          </button>
                        ))}
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>

      {/* 主配置表单 */}
      <div className="bg-gradient-to-br from-sb-cyan/10 to-sb-bg-primary/50 rounded-xl border border-sb-cyan/20 p-6 mb-8">
        {/* API Key 安全提示 */}
        <label className="flex items-center gap-3 mb-4 p-3 bg-yellow-500/10 rounded-lg border border-yellow-500/20">
          <input
            type="checkbox"
            checked={saveApiKey}
            onChange={(e) => setSaveApiKey(e.target.checked)}
            className="w-4 h-4 rounded border-sb-border/50 bg-sb-bg-secondary text-sb-cyan focus:ring-sb-cyan/50"
          />
          <div>
            <div className="text-sm text-yellow-200">保存 API Key 到配置文件</div>
            <div className="text-xs text-yellow-200/60">⚠️ 不建议，存在安全风险，推荐从环境变量读取</div>
          </div>
        </label>

        <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <Settings className="w-5 h-5 text-sb-cyan" />
          配置参数
        </h3>
        {renderConfigForm()}

        {/* 主配置保存按钮 */}
        <div className="flex gap-3 mt-6">
          <button
            onClick={handleTest}
            disabled={isLoading}
            className="flex items-center gap-2 px-4 py-2 bg-sb-bg-secondary text-white rounded-lg
                       hover:bg-sb-bg-secondary/80 disabled:opacity-50 transition-colors text-sm"
          >
            <TestTube className="w-4 h-4" />
            {isLoading ? '测试中...' : '测试连接'}
          </button>
          <button
            onClick={handleSave}
            disabled={isLoading}
            className="flex items-center gap-2 px-4 py-2 bg-sb-cyan text-sb-bg-primary rounded-lg
                       hover:bg-sb-cyan-hover disabled:opacity-50 transition-colors text-sm"
          >
            <Save className="w-4 h-4" />
            {isLoading ? '保存中...' : '保存配置'}
          </button>
        </div>

        {/* 测试结果 */}
        {testResult && (
          <div className={`mt-4 p-4 rounded-lg border ${
            testResult.success
              ? 'bg-green-500/10 border-green-500/30 text-green-400'
              : 'bg-red-500/10 border-red-500/30 text-red-400'
          }`}>
            <div className="flex items-center gap-2 font-medium">
              {testResult.success ? <CheckCircle className="w-5 h-5" /> : <AlertCircle className="w-5 h-5" />}
              {testResult.success ? '测试成功' : '测试失败'}
            </div>
            <div className="mt-2 text-sm whitespace-pre-wrap">{testResult.message}</div>
            {testResult.available_models && testResult.available_models.length > 0 && (
              <div className="mt-3">
                <div className="text-xs text-sb-text-secondary mb-2">可用模型:</div>
                <div className="flex flex-wrap gap-2">
                  {testResult.available_models.slice(0, 10).map((m: string) => (
                    <button
                      key={m}
                      onClick={() => setConfig(prev => ({ ...prev, model: m }))}
                      className="px-2 py-1 text-xs bg-sb-bg-secondary rounded hover:bg-sb-bg-secondary/80 transition-colors"
                    >
                      {m}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* 主配置保存状态 */}
        {saveStatus === 'success' && (
          <div className="mt-4 p-3 bg-green-500/10 border border-green-500/30 rounded-lg text-green-400 flex items-center gap-2 text-sm">
            <CheckCircle className="w-4 h-4" />
            配置已保存并热加载
          </div>
        )}
        {saveStatus === 'error' && (
          <div className="mt-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 flex items-center gap-2 text-sm">
            <AlertCircle className="w-4 h-4" />
            保存失败：{saveErrorMsg}
          </div>
        )}
      </div>

      {/* 视觉模型配置 Card */}
      <div className="bg-gradient-to-br from-purple-900/30 to-sb-bg-primary/50 rounded-xl border border-purple-500/20 p-6 mb-8">
        {/* 视觉配置 - API Key 安全提示 */}
        <label className="flex items-center gap-3 mb-4 p-3 bg-yellow-500/10 rounded-lg border border-yellow-500/20">
          <input
            type="checkbox"
            checked={visionSaveApiKey}
            onChange={(e) => setVisionSaveApiKey(e.target.checked)}
            className="w-4 h-4 rounded border-sb-border/50 bg-sb-bg-secondary text-sb-cyan focus:ring-sb-cyan/50"
          />
          <div>
            <div className="text-sm text-yellow-200">保存 API Key 到配置文件</div>
            <div className="text-xs text-yellow-200/60">⚠️ 不建议，存在安全风险，推荐从环境变量读取</div>
          </div>
        </label>

        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 bg-purple-500/20 rounded-lg">
            <Eye className="w-5 h-5 text-purple-400" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white flex items-center gap-2">
              视觉模型配置
              <span className="px-2 py-0.5 text-xs bg-purple-500/20 text-purple-400 rounded-full border border-purple-500/30">
                Beta
              </span>
            </h3>
            <p className="text-sb-text-secondary text-sm">配置视觉理解能力（图像分析、GUI自动化等）</p>
          </div>
        </div>

        {/* 功能标签 */}
        <div className="flex flex-wrap gap-2 mb-6">
          <span className="flex items-center gap-1 px-2 py-1 text-xs bg-sb-bg-secondary text-sb-text-secondary rounded border border-sb-border/30">
            <Image className="w-3 h-3" />
            图像分析
          </span>
          <span className="flex items-center gap-1 px-2 py-1 text-xs bg-sb-bg-secondary text-sb-text-secondary rounded border border-sb-border/30">
            <Sparkles className="w-3 h-3" />
            GUI自动化
          </span>
          <span className="flex items-center gap-1 px-2 py-1 text-xs bg-sb-bg-secondary text-sb-text-secondary rounded border border-sb-border/30">
            <Eye className="w-3 h-3" />
            视觉理解
          </span>
        </div>

        {renderVisionConfigForm()}

        {/* 保存视觉配置按钮 */}
        <div className="flex gap-3 mt-6">
          <button
            onClick={handleSaveVision}
            disabled={isSavingVision}
            className="flex items-center gap-2 px-4 py-2 bg-purple-500 text-white rounded-lg
                       hover:bg-purple-600 disabled:opacity-50 transition-colors text-sm"
          >
            <Save className="w-4 h-4" />
            {isSavingVision ? '保存中...' : '保存视觉配置'}
          </button>
        </div>

        {/* 视觉配置保存状态 */}
        {saveVisionStatus === 'success' && (
          <div className="mt-4 p-3 bg-green-500/10 border border-green-500/30 rounded-lg text-green-400 flex items-center gap-2 text-sm">
            <CheckCircle className="w-4 h-4" />
            视觉配置已保存
          </div>
        )}
        {saveVisionStatus === 'error' && (
          <div className="mt-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 flex items-center gap-2 text-sm">
            <AlertCircle className="w-4 h-4" />
            保存失败：{saveVisionErrorMsg}
          </div>
        )}
      </div>

      {/* 统一保存按钮 */}
      <div className="flex items-center justify-between p-4 bg-sb-bg-primary/50 rounded-xl border border-white/10">
        <div className="text-sm text-sb-text-secondary">
          同时保存主配置和视觉配置
        </div>
        <button
          onClick={handleSaveAll}
          disabled={isLoading || isSavingVision}
          className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-sb-cyan to-sb-purple
                     text-white rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity font-medium"
        >
          <Save className="w-5 h-5" />
          {isLoading || isSavingVision ? '保存中...' : '保存所有配置'}
        </button>
      </div>
    </motion.div>
  );
};
