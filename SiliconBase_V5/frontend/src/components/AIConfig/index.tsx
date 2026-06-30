import React, { useState, useEffect } from 'react';
import { aiConfigService, AIProviderInfo, AIProviderConfig } from '../../services/aiConfig';

export const AIConfig: React.FC = () => {
  const [providers, setProviders] = useState<AIProviderInfo[]>([]);
  const [currentProvider, setCurrentProvider] = useState<string>('ollama');
  const [config, setConfig] = useState<AIProviderConfig>({});
  const [isLoading, setIsLoading] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [saveApiKey, setSaveApiKey] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [providersData, currentData] = await Promise.all([
        aiConfigService.getProviders(),
        aiConfigService.getCurrentConfig()
      ]);
      setProviders(providersData);
      setCurrentProvider(currentData.provider);
      setConfig(currentData.config);
    } catch (error) {
      console.error('加载失败:', error);
    }
  };

  const handleProviderChange = (provider: string) => {
    setCurrentProvider(provider);
    setConfig({});
    setTestResult(null);
    setAvailableModels([]);
  };

  const loadAvailableModels = async () => {
    // 支持所有Provider的模型列表获取
    setIsLoadingModels(true);
    try {
      const models = await aiConfigService.getModels(currentProvider);
      setAvailableModels(models);
    } catch (error) {
      console.error('加载模型列表失败:', error);
      // 加载失败时清空列表，允许用户手动输入
      setAvailableModels([]);
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
      setTestResult({ success: false, message: '测试失败' });
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    setIsLoading(true);
    try {
      const result = await aiConfigService.updateConfig(currentProvider, config, {
        persist: true,
        saveApiKey
      });
      if (result.success) {
        setSaveStatus('success');
        setTimeout(() => setSaveStatus('idle'), 3000);
      } else {
        setSaveStatus('error');
      }
    } catch (error) {
      setSaveStatus('error');
    } finally {
      setIsLoading(false);
    }
  };

  const renderConfigForm = () => {
    const providerInfo = providers.find(p => p.type === currentProvider);
    if (!providerInfo) return null;

    const renderField = (field: string, isRequired: boolean) => {
      const value = config[field as keyof AIProviderConfig] || '';
      
      if (field === 'api_key') {
        return (
          <div key={field} className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              API Key {isRequired && <span className="text-red-500">*</span>}
            </label>
            <input
              type="password"
              value={value as string}
              onChange={(e) => setConfig({ ...config, [field]: e.target.value })}
              className="w-full px-3 py-2 border rounded-md"
              placeholder="sk-..."
            />
          </div>
        );
      }

      if (field === 'model') {
        return (
          <div key={field} className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              模型 {isRequired && <span className="text-red-500">*</span>}
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={value as string}
                onChange={(e) => setConfig({ ...config, [field]: e.target.value })}
                className="flex-1 px-3 py-2 border rounded-md"
                placeholder={
                  currentProvider === 'ollama' ? 'qwen3:8b' : 
                  currentProvider === 'openai' ? 'gpt-4' :
                  currentProvider === 'anthropic' ? 'claude-3-opus' :
                  currentProvider === 'deepseek' ? 'deepseek-chat' :
                  currentProvider === 'kimi' ? 'moonshot-v1-8k' :
                  currentProvider === 'qwen' ? 'qwen-turbo' :
                  '输入模型名称'
                }
                list="available-models"
              />
              <button
                onClick={loadAvailableModels}
                disabled={isLoadingModels}
                className="px-3 py-2 bg-gray-100 border rounded-md hover:bg-gray-200 disabled:opacity-50 text-sm whitespace-nowrap"
                title="获取远程服务上的可用模型列表"
              >
                {isLoadingModels ? '加载中...' : '获取模型列表'}
              </button>
            </div>
            {availableModels.length > 0 && (
              <datalist id="available-models">
                {availableModels.map(m => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            )}
            <div className="mt-1 text-xs text-gray-500">
              {availableModels.length === 0 && !isLoadingModels ? (
                <>提示：点击"获取模型列表"查看可用模型，或直接输入模型名称</>
              ) : availableModels.length > 0 ? (
                <>提示：输入框下拉或点击下方测试结果的模型标签快速选择</>
              ) : null}
            </div>
          </div>
        );
      }

      if (field === 'timeout' || field === 'retry_times') {
        return (
          <div key={field} className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              {field === 'timeout' ? '超时时间(秒)' : '重试次数'}
            </label>
            <input
              type="number"
              value={value as number || ''}
              onChange={(e) => setConfig({ ...config, [field]: parseInt(e.target.value) || 0 })}
              className="w-full px-3 py-2 border rounded-md"
            />
          </div>
        );
      }

      return (
        <div key={field} className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            {field} {isRequired && <span className="text-red-500">*</span>}
          </label>
          <input
            type="text"
            value={value as string}
            onChange={(e) => setConfig({ ...config, [field]: e.target.value })}
            className="w-full px-3 py-2 border rounded-md"
          />
        </div>
      );
    };

    return (
      <div className="bg-gray-50 p-4 rounded-md">
        <h3 className="font-medium mb-4">配置参数</h3>
        {providerInfo.required_config.map(field => renderField(field, true))}
        {providerInfo.optional_config.map(field => renderField(field, false))}
      </div>
    );
  };

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h2 className="text-2xl font-bold mb-6">AI模型配置</h2>
      
      {/* Provider选择 */}
      <div className="mb-6">
        <h3 className="text-lg font-medium mb-3">选择AI后端</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {providers.map(p => (
            <button
              key={p.type}
              onClick={() => handleProviderChange(p.type)}
              className={`p-4 rounded-lg border-2 text-left transition-colors ${
                currentProvider === p.type 
                  ? 'border-blue-500 bg-blue-50' 
                  : 'border-gray-200 hover:border-blue-300'
              }`}
            >
              <div className="font-medium">{p.name}</div>
            </button>
          ))}
        </div>
      </div>

      {/* 配置表单 */}
      {renderConfigForm()}

      {/* API Key选项 */}
      <label className="flex items-center gap-2 mt-4 mb-6">
        <input
          type="checkbox"
          checked={saveApiKey}
          onChange={(e) => setSaveApiKey(e.target.checked)}
          className="rounded"
        />
        <span className="text-sm text-gray-600">
          保存API Key到配置文件（不安全，建议从环境变量读取）
        </span>
      </label>

      {/* 操作按钮 */}
      <div className="flex gap-4">
        <button
          onClick={handleTest}
          disabled={isLoading}
          className="px-6 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700 disabled:opacity-50"
        >
          {isLoading ? '测试中...' : '测试连接'}
        </button>
        <button
          onClick={handleSave}
          disabled={isLoading}
          className="px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {isLoading ? '保存中...' : '保存配置'}
        </button>
      </div>

      {/* 测试结果 */}
      {testResult && (
        <div className={`mt-4 p-4 rounded-md ${testResult.success ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'}`}>
          <div className="font-medium">{testResult.success ? '✓ 测试成功' : '✗ 测试失败'}</div>
          <div className="text-sm mt-1 whitespace-pre-wrap">{testResult.message}</div>
          {testResult.available_models && testResult.available_models.length > 0 && (
            <div className="mt-2">
              <div className="text-xs text-gray-500 mb-1">可用模型:</div>
              <div className="flex flex-wrap gap-1">
                {testResult.available_models.slice(0, 20).map((m: string) => (
                  <button
                    key={m}
                    onClick={() => setConfig({ ...config, model: m })}
                    className="px-2 py-1 text-xs bg-white border rounded hover:bg-blue-50 hover:border-blue-300"
                    title="点击使用此模型"
                  >
                    {m}
                  </button>
                ))}
                {testResult.available_models.length > 20 && (
                  <span className="text-xs text-gray-500 px-2 py-1">
                    等共 {testResult.available_models.length} 个模型
                  </span>
                )}
              </div>
            </div>
          )}
          {testResult.response_preview && (
            <div className="mt-2 p-2 bg-white rounded text-sm font-mono">
              {testResult.response_preview}
            </div>
          )}
        </div>
      )}

      {/* 保存状态 */}
      {saveStatus === 'success' && (
        <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-md">
          ✓ 配置已保存并热加载
        </div>
      )}
      {saveStatus === 'error' && (
        <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-md">
          ✗ 保存失败
        </div>
      )}
    </div>
  );
};
