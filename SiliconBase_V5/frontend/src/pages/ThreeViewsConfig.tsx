/**
 * 三观配置页面
 * 支持一键模板选择和高级自定义
 */
import React, { useState, useEffect } from "react";
import {
  Shield,
  Compass,
  Scale,
  Cpu,
  Heart,
  Save,
  RotateCcw,
  ChevronDown,
  ChevronUp,
  Info,
} from "lucide-react";
import { fetchAPI } from "../utils/api";

// 模板定义
interface Template {
  key: string;
  name: string;
  description: string;
  icon: React.ReactNode;
  color: string;
}

const TEMPLATES: Template[] = [
  {
    key: "guardian",
    name: "守护者",
    description: "安全敏感型，优先保护用户和系统",
    icon: <Shield className="w-6 h-6" />,
    color: "bg-blue-500",
  },
  {
    key: "explorer",
    name: "探索者",
    description: "好奇心旺盛，追求知识和成长",
    icon: <Compass className="w-6 h-6" />,
    color: "bg-green-500",
  },
  {
    key: "balanced",
    name: "平衡型",
    description: "大多数用户的默认选择，平衡各方面",
    icon: <Scale className="w-6 h-6" />,
    color: "bg-purple-500",
  },
  {
    key: "geek",
    name: "极客型",
    description: "开发者偏好，逻辑至上",
    icon: <Cpu className="w-6 h-6" />,
    color: "bg-gray-700",
  },
  {
    key: "caring",
    name: "关怀型",
    description: "感性用户，注重情感连接",
    icon: <Heart className="w-6 h-6" />,
    color: "bg-pink-500",
  },
];

// 六维权重接口
interface ValueWeights {
  emotional_temperature: number;
  ethical_safety: number;
  self_growth: number;
  execution_quality: number;
  survival_security: number;
  creative_insight: number;
}

// 配置接口
interface ThreeViewsConfig {
  template_name: string;
  world_view: {
    auto_perception: boolean;
    history_prediction: boolean;
    custom_description: string;
  };
  life_view: {
    energy_threshold: number;
    curiosity_level: number;
    custom_description: string;
  };
  value_system: {
    weights: ValueWeights;
    rules: {
      forbid_high_risk: boolean;
      protect_core: boolean;
    };
    custom_description: string;
  };
}

const DEFAULT_CONFIG: ThreeViewsConfig = {
  template_name: "balanced",
  world_view: {
    auto_perception: true,
    history_prediction: true,
    custom_description: "",
  },
  life_view: {
    energy_threshold: 3,
    curiosity_level: 5,
    custom_description: "",
  },
  value_system: {
    weights: {
      emotional_temperature: 20,
      ethical_safety: 25,
      self_growth: 20,
      execution_quality: 15,
      survival_security: 15,
      creative_insight: 5,
    },
    rules: {
      forbid_high_risk: true,
      protect_core: true,
    },
    custom_description: "",
  },
};

export const ThreeViewsConfig: React.FC = () => {
  const [selectedTemplate, setSelectedTemplate] = useState("balanced");
  const [config, setConfig] = useState<ThreeViewsConfig>(DEFAULT_CONFIG);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [preview, setPreview] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string>("");

  // 加载用户配置
  useEffect(() => {
    loadConfig();
  }, []);

  // 选择模板时更新配置
  useEffect(() => {
    if (selectedTemplate) {
      loadTemplatePreview(selectedTemplate);
    }
  }, [selectedTemplate]);

  const loadConfig = async () => {
    try {
      const response: any = await fetchAPI("/api/three-views/config");
      if (response.success) {
        setSelectedTemplate(response.config.template_name);
        setConfig(response.config);
      }
    } catch (error) {
      console.error("加载配置失败:", error);
    }
  };

  const loadTemplatePreview = async (templateName: string) => {
    try {
      const response: any = await fetchAPI(
        `/api/three-views/preview?template_name=${templateName}`,
      );
      if (response.success) {
        setPreview(response.full_prompt);
      }
    } catch (error) {
      console.error("加载预览失败:", error);
      // 如果API不可用，显示模拟预览
      setPreview(generateMockPreview(templateName));
    }
  };

  // 生成模拟预览（当API不可用时）
  const generateMockPreview = (templateName: string): string => {
    const template = TEMPLATES.find((t) => t.key === templateName);
    return `【${template?.name || "平衡型"}人格模式】

世界观：
- 自动感知环境：${config.world_view.auto_perception ? "是" : "否"}
- 历史经验预测：${config.world_view.history_prediction ? "是" : "否"}

生命观：
- 能量警戒线：${config.life_view.energy_threshold}/10
- 好奇心水平：${config.life_view.curiosity_level}/10

价值观六维权重：
- 情感温度：${config.value_system.weights.emotional_temperature}%
- 伦理安全：${config.value_system.weights.ethical_safety}%
- 自我成长：${config.value_system.weights.self_growth}%
- 执行成效：${config.value_system.weights.execution_quality}%
- 存续保障：${config.value_system.weights.survival_security}%
- 灵感创新：${config.value_system.weights.creative_insight}%

安全规则：
- 禁止高危操作：${config.value_system.rules.forbid_high_risk ? "是" : "否"}
- 优先保护核心：${config.value_system.rules.protect_core ? "是" : "否"}`;
  };

  const handleTemplateSelect = (templateKey: string) => {
    setSelectedTemplate(templateKey);
    setConfig((prev) => ({ ...prev, template_name: templateKey }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const response: any = await fetchAPI("/api/three-views/config", {
        method: "POST",
        body: config,
      });
      if (response.success) {
        setMessage("三观配置已保存");
        setTimeout(() => setMessage(""), 3000);
      }
    } catch (error) {
      console.error("保存失败:", error);
      setMessage(
        "保存失败: " + (error instanceof Error ? error.message : "网络错误"),
      );
      setTimeout(() => setMessage(""), 5000);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setSelectedTemplate("balanced");
    setConfig(DEFAULT_CONFIG);
    setMessage("已重置为默认配置");
    setTimeout(() => setMessage(""), 3000);
  };

  const updateWeight = (key: keyof ValueWeights, value: number) => {
    setConfig((prev) => ({
      ...prev,
      value_system: {
        ...prev.value_system,
        weights: {
          ...prev.value_system.weights,
          [key]: value,
        },
      },
    }));
  };

  const weightLabels: Record<keyof ValueWeights, string> = {
    emotional_temperature: "情感温度",
    ethical_safety: "伦理安全",
    self_growth: "自我成长",
    execution_quality: "执行成效",
    survival_security: "存续保障",
    creative_insight: "灵感创新",
  };

  return (
    <div className="h-full w-full bg-sb-bg-primary text-slate-100 p-6 overflow-auto">
      <div className="max-w-4xl mx-auto">
        {/* 标题 */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold mb-2">三观配置</h1>
          <p className="text-slate-400">
            配置AI的道德观、价值观、世界观，塑造独特的个性
          </p>
        </div>

        {/* 消息提示 */}
        {message && (
          <div className="mb-4 p-3 bg-emerald-500/20 border border-emerald-500/30 rounded-lg text-emerald-400">
            {message}
          </div>
        )}

        {/* 一键模板选择 */}
        <div className="mb-8">
          <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <Info className="w-5 h-5 text-blue-400" />
            选择风格模板
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {TEMPLATES.map((template) => (
              <button
                key={template.key}
                onClick={() => handleTemplateSelect(template.key)}
                className={`p-4 rounded-xl border-2 transition-all ${
                  selectedTemplate === template.key
                    ? "border-sb-cyan bg-sb-cyan/10"
                    : "border-white/10 bg-sb-bg-secondary hover:border-white/20"
                }`}
              >
                <div
                  className={`${template.color} w-12 h-12 rounded-lg flex items-center justify-center mb-3 mx-auto text-white`}
                >
                  {template.icon}
                </div>
                <h3 className="font-semibold mb-1">{template.name}</h3>
                <p className="text-xs text-slate-400">{template.description}</p>
              </button>
            ))}
          </div>
        </div>

        {/* 预览区域 */}
        <div className="mb-8 p-4 bg-sb-bg-secondary rounded-xl border border-white/10">
          <h3 className="font-semibold mb-3">当前三观提示词预览</h3>
          <pre className="text-sm text-slate-300 whitespace-pre-wrap font-mono bg-sb-bg-primary p-4 rounded-lg overflow-auto max-h-60">
            {preview || "加载中..."}
          </pre>
        </div>

        {/* 高级自定义折叠面板 */}
        <div className="mb-8">
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="w-full flex items-center justify-between p-4 bg-sb-bg-secondary rounded-xl border border-white/10 hover:border-white/20 transition-colors"
          >
            <span className="font-semibold">高级自定义</span>
            {showAdvanced ? (
              <ChevronUp className="w-5 h-5" />
            ) : (
              <ChevronDown className="w-5 h-5" />
            )}
          </button>

          {showAdvanced && (
            <div className="mt-4 space-y-6 p-4 bg-sb-bg-secondary/50 rounded-xl border border-white/5">
              {/* 世界观配置 */}
              <div>
                <h3 className="font-semibold mb-3 text-lg">世界观</h3>
                <div className="space-y-3">
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={config.world_view.auto_perception}
                      onChange={(e) =>
                        setConfig((prev) => ({
                          ...prev,
                          world_view: {
                            ...prev.world_view,
                            auto_perception: e.target.checked,
                          },
                        }))
                      }
                      className="w-4 h-4 rounded border-white/20 bg-sb-bg-primary accent-sb-cyan"
                    />
                    <span>启用自动感知环境</span>
                  </label>
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={config.world_view.history_prediction}
                      onChange={(e) =>
                        setConfig((prev) => ({
                          ...prev,
                          world_view: {
                            ...prev.world_view,
                            history_prediction: e.target.checked,
                          },
                        }))
                      }
                      className="w-4 h-4 rounded border-white/20 bg-sb-bg-primary accent-sb-cyan"
                    />
                    <span>依据历史经验预测结果</span>
                  </label>
                  <div>
                    <label className="block text-sm text-slate-400 mb-2">
                      自定义世界观描述
                    </label>
                    <textarea
                      value={config.world_view.custom_description}
                      onChange={(e) =>
                        setConfig((prev) => ({
                          ...prev,
                          world_view: {
                            ...prev.world_view,
                            custom_description: e.target.value,
                          },
                        }))
                      }
                      placeholder="例如：世界由数据和逻辑构成..."
                      className="w-full p-3 bg-sb-bg-primary border border-white/10 rounded-lg text-sm focus:outline-none focus:border-sb-cyan"
                      rows={2}
                    />
                  </div>
                </div>
              </div>

              {/* 生命观配置 */}
              <div>
                <h3 className="font-semibold mb-3 text-lg">生命观</h3>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm text-slate-400 mb-2">
                      能量警戒线: {config.life_view.energy_threshold}/10
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="10"
                      value={config.life_view.energy_threshold}
                      onChange={(e) =>
                        setConfig((prev) => ({
                          ...prev,
                          life_view: {
                            ...prev.life_view,
                            energy_threshold: parseInt(e.target.value),
                          },
                        }))
                      }
                      className="w-full accent-sb-cyan"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-slate-400 mb-2">
                      好奇心水平: {config.life_view.curiosity_level}/10
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="10"
                      value={config.life_view.curiosity_level}
                      onChange={(e) =>
                        setConfig((prev) => ({
                          ...prev,
                          life_view: {
                            ...prev.life_view,
                            curiosity_level: parseInt(e.target.value),
                          },
                        }))
                      }
                      className="w-full accent-sb-cyan"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-slate-400 mb-2">
                      自定义生命观描述
                    </label>
                    <textarea
                      value={config.life_view.custom_description}
                      onChange={(e) =>
                        setConfig((prev) => ({
                          ...prev,
                          life_view: {
                            ...prev.life_view,
                            custom_description: e.target.value,
                          },
                        }))
                      }
                      placeholder="例如：我的存在意义是..."
                      className="w-full p-3 bg-sb-bg-primary border border-white/10 rounded-lg text-sm focus:outline-none focus:border-sb-cyan"
                      rows={2}
                    />
                  </div>
                </div>
              </div>

              {/* 价值观配置 - 六维权重 */}
              <div>
                <h3 className="font-semibold mb-3 text-lg">
                  价值观 - 六维权重
                </h3>
                <div className="space-y-4">
                  {(
                    Object.keys(config.value_system.weights) as Array<
                      keyof ValueWeights
                    >
                  ).map((key) => (
                    <div key={key}>
                      <label className="block text-sm text-slate-400 mb-2">
                        {weightLabels[key]}: {config.value_system.weights[key]}%
                      </label>
                      <input
                        type="range"
                        min="0"
                        max="100"
                        value={config.value_system.weights[key]}
                        onChange={(e) =>
                          updateWeight(key, parseInt(e.target.value))
                        }
                        className="w-full accent-sb-cyan"
                      />
                    </div>
                  ))}
                </div>

                {/* 安全规则 */}
                <div className="mt-4 space-y-3">
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={config.value_system.rules.forbid_high_risk}
                      onChange={(e) =>
                        setConfig((prev) => ({
                          ...prev,
                          value_system: {
                            ...prev.value_system,
                            rules: {
                              ...prev.value_system.rules,
                              forbid_high_risk: e.target.checked,
                            },
                          },
                        }))
                      }
                      className="w-4 h-4 rounded border-white/20 bg-sb-bg-primary accent-sb-cyan"
                    />
                    <span>禁止高危操作</span>
                  </label>
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={config.value_system.rules.protect_core}
                      onChange={(e) =>
                        setConfig((prev) => ({
                          ...prev,
                          value_system: {
                            ...prev.value_system,
                            rules: {
                              ...prev.value_system.rules,
                              protect_core: e.target.checked,
                            },
                          },
                        }))
                      }
                      className="w-4 h-4 rounded border-white/20 bg-sb-bg-primary accent-sb-cyan"
                    />
                    <span>优先保护系统核心</span>
                  </label>
                </div>

                <div className="mt-4">
                  <label className="block text-sm text-slate-400 mb-2">
                    自定义价值观描述
                  </label>
                  <textarea
                    value={config.value_system.custom_description}
                    onChange={(e) =>
                      setConfig((prev) => ({
                        ...prev,
                        value_system: {
                          ...prev.value_system,
                          custom_description: e.target.value,
                        },
                      }))
                    }
                    placeholder="例如：对我而言最重要的是..."
                    className="w-full p-3 bg-sb-bg-primary border border-white/10 rounded-lg text-sm focus:outline-none focus:border-sb-cyan"
                    rows={2}
                  />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* 操作按钮 */}
        <div className="flex gap-4">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-6 py-3 bg-sb-cyan hover:bg-sb-cyan/80 disabled:opacity-50 rounded-lg font-semibold transition-colors text-sb-bg-primary"
          >
            <Save className="w-5 h-5" />
            {saving ? "保存中..." : "保存配置"}
          </button>
          <button
            onClick={handleReset}
            className="flex items-center gap-2 px-6 py-3 bg-sb-bg-secondary hover:bg-white/10 border border-white/10 rounded-lg font-semibold transition-colors"
          >
            <RotateCcw className="w-5 h-5" />
            重置默认
          </button>
        </div>
      </div>
    </div>
  );
};

export default ThreeViewsConfig;
