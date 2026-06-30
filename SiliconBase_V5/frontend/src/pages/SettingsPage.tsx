/**
 * 设置页面 - 配置管理（支持global.yaml热加载）
 *
 * 2026-02-27 更新：
 * - 新增直接操作global.yaml功能
 * - 支持表单模式和YAML编辑器模式
 * - 保存后自动触发热重载
 * - 新增备份管理功能
 */
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Settings,
  Save,
  RotateCcw,
  CheckCircle,
  AlertCircle,
  Server,
  WifiOff,
  FileCode,
  FormInput,
  RefreshCw,
  Eye,
  EyeOff,
  Archive,
  History,
  RotateCcw as RestoreIcon,
  ExternalLink,
  Cpu,
  Volume2,
} from "lucide-react";
import {
  configAPI,
  ConfigData,
  ConfigSchema,
  BackupInfo,
} from "../utils/api/config";
import { authFetch } from "../utils/api";
import { useNotifications } from "../hooks/useNotifications";
import { useSystemStatus } from "../hooks/useSystemStatus";
// 注意：所有API请求都通过 configAPI 统一处理，包括认证头
import YAML from "yaml";
import { MoralFilterSettings } from "../components/MoralFilterSettings";
import { ExchangeConfigPanel } from "../components/ExchangeConfigPanel";
import { MCPConfigPanel } from "../components/MCPConfigPanel";
import { VoiceAnnounceConfigPanel } from "../components/VoiceAnnounceConfigPanel";
import { useModeStore, ModeType } from "../stores/modeStore";

// 默认配置数据（当后端不可用时使用）
const defaultConfig: ConfigData = {
  work_mode: "focus", // 与 modeStore 默认值保持一致
  voice_wake_word: "硅基",
  model_name: "qwen3:8b",
  vision_model: "",
  temperature: 0.7,
  max_tokens: 2048,
  tool_whitelist: [],
  enable_voice: true,
  think_interval: 5,
  voice_tts_engine: "piper",
  voice_tts_speed: 1.0,
  voice_tts_volume: 80,
  voice_wake_mode: "wake_word",
  voice_input_device: "",
  voice_output_device: "",
  voice_asr_engine: "vosk",
};

// 默认 Schema（当后端不可用时使用）
const defaultSchema: ConfigSchema = {
  work_mode: {
    type: "select",
    label: "工作模式",
    description:
      "选择AI的工作模式：日常模式允许AI主动思考和触发任务，专注模式减少AI主动干扰",
    options: [
      { value: "daily", label: "日常模式" },
      { value: "focus", label: "专注模式" },
    ],
  },
  voice_wake_word: {
    type: "string",
    label: "语音唤醒词",
    description: "语音唤醒AI的触发词，说出此词可唤醒AI进行语音对话",
    placeholder: "硅基",
  },
  voice_tts_engine: {
    type: "select",
    label: "TTS 引擎",
    description: "选择语音合成引擎，Piper为本地离线，EdgeTTS为在线云端",
    options: [
      { value: "piper", label: "Piper (本地)" },
      { value: "edge_tts", label: "Edge TTS (云端)" },
    ],
  },
  voice_tts_speed: {
    type: "number",
    label: "TTS 语速",
    description: "语音合成语速倍率，1.0为正常速度",
    min: 0.5,
    max: 2.0,
    step: 0.1,
  },
  voice_tts_volume: {
    type: "number",
    label: "TTS 音量",
    description: "语音合成输出音量百分比",
    min: 0,
    max: 100,
    step: 5,
  },
  voice_wake_mode: {
    type: "select",
    label: "语音唤醒模式",
    description:
      "选择语音交互方式：唤醒词模式（说唤醒词激活）、按住说话模式（按住按钮说话）、或两者同时启用",
    options: [
      { value: "wake_word", label: "唤醒词模式" },
      { value: "push_to_talk", label: "按住说话" },
      { value: "both", label: "两者同时启用" },
    ],
  },
  voice_input_device: {
    type: "string",
    label: "输入设备",
    description: "麦克风设备名称或索引，留空使用系统默认",
    placeholder: "留空使用默认设备",
  },
  voice_output_device: {
    type: "string",
    label: "输出设备",
    description: "扬声器设备名称或索引，留空使用系统默认",
    placeholder: "留空使用默认设备",
  },
  voice_asr_engine: {
    type: "select",
    label: "ASR 引擎",
    description: "选择语音识别引擎",
    options: [
      { value: "vosk", label: "Vosk (本地)" },
      { value: "whisper", label: "Whisper (云端)" },
    ],
  },
  // model_name 已移至 AIConfigPage 统一管理，此处仅作显示
  // model_name: {
  //   type: 'string',
  //   label: 'AI 模型',
  //   description: '选择使用的AI模型，支持Ollama本地模型或云端API模型',
  //   placeholder: '输入模型名称，如: qwen3:8b, llama3.1:8b, mistral, gpt-4 等',
  // },
  temperature: {
    type: "number",
    label: "温度参数",
    description:
      "控制AI回复的创造性，较低值(0.0-0.5)回复更确定，较高值(1.0-2.0)回复更随机",
    min: 0,
    max: 2,
    step: 0.1,
  },
  max_tokens: {
    type: "integer",
    label: "最大 Token",
    description: "限制AI回复的最大长度，0表示不限制",
    placeholder: "2048",
    min: 256,
    max: 8192,
  },
  enable_voice: {
    type: "boolean",
    label: "启用语音",
    description: "开启后AI将使用语音播报回复内容",
  },
  think_interval: {
    type: "integer",
    label: "思考间隔",
    description: "日常模式下AI主动思考的间隔时间(秒)",
    placeholder: "30",
    min: 1,
    max: 60,
  },
};

// 配置项到YAML路径的映射
// 注意：model_name 已移至 AIConfigPage 统一管理，此处不再包含
const configMapping: Record<string, string> = {
  work_mode: "work_mode",
  voice_wake_word: "voice.wake_words",
  // 'model_name': 'ai.default_model',  // 已移至 AIConfigPage
  vision_model: "ai.vision_model", // 视觉模型配置
  temperature: "ai.temperature",
  max_tokens: "ai.max_tokens",
  tool_whitelist: "tools.whitelist",
  enable_voice: "voice.enabled",
  think_interval: "mode.daily.interval",
  voice_tts_engine: "voice.tts_engine",
  voice_tts_speed: "voice.tts_speed",
  voice_tts_volume: "voice.tts_volume",
  voice_wake_mode: "voice.wake_mode",
  voice_input_device: "voice.input_device_index",
  voice_output_device: "voice.output_device_index",
  voice_asr_engine: "voice.asr_engine",
};

// 配置项到YAML路径的映射说明：
// 表单字段 -> YAML路径
// work_mode -> work_mode
// voice_wake_word -> wake_word
// model_name -> ai.default_model
// temperature -> ai.temperature
// max_tokens -> ai.max_tokens
// tool_whitelist -> tools.whitelist
// enable_voice -> voice.enabled
// think_interval -> mode.daily.interval

type ViewMode = "form" | "yaml" | "backups";

export function SettingsPage() {
  const navigate = useNavigate();

  // 模式状态 - 使用 modeStore 统一管理
  const { mode, switchMode, fetchCurrentMode } = useModeStore();

  // 表单模式状态
  const [config, setConfig] = useState<ConfigData>(defaultConfig);
  const [schema, setSchema] = useState<ConfigSchema>(defaultSchema);

  // YAML模式状态
  const [yamlContent, setYamlContent] = useState<string>("");
  const [yamlParsed, setYamlParsed] = useState<Record<string, any>>({});

  // 备份管理状态
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [loadingBackups, setLoadingBackups] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [maxBackups, setMaxBackups] = useState(10);

  // 通用状态
  const [viewMode, setViewMode] = useState<ViewMode>("form");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [backendUnavailable, setBackendUnavailable] = useState(false);
  const [yamlError, setYamlError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState<Record<string, boolean>>({});
  const [yamlAdvancedMode, setYamlAdvancedMode] = useState(false);
  const [availableTools, setAvailableTools] = useState<string[]>([]);
  const [toolManualMode, setToolManualMode] = useState(false);

  const { showNotification } = useNotifications();
  const { isBackendConnected } = useSystemStatus({ pollInterval: 0 });

  // 加载配置（表单模式）
  const loadConfig = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setBackendUnavailable(false);

      const [configData, schemaData, toolsData] = await Promise.all([
        configAPI.getConfig(),
        configAPI.getConfigSchema(),
        authFetch("/api/tools/")
          .then((r) => (r.ok ? r.json() : { data: { tools: [] } }))
          .catch(() => ({ data: { tools: [] } })),
      ]);

      setConfig(configData || defaultConfig);
      setSchema(schemaData || defaultSchema);
      const tools = toolsData?.data?.tools || [];
      setAvailableTools(tools.map((t: any) => t.name || t.id).filter(Boolean));
      showNotification({
        type: "success",
        title: "配置加载成功",
        message: "已获取最新配置",
        duration: 2000,
      });
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "加载配置失败";
      setError(errorMsg);
      setBackendUnavailable(true);

      showNotification({
        type: "warning",
        title: "后端连接失败",
        message: "使用默认配置，保存将在连接恢复后同步",
        duration: 5000,
      });
    } finally {
      setLoading(false);
    }
  }, [showNotification]);

  // 加载YAML（YAML模式）
  const loadYaml = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setYamlError(null);

      // 使用统一的 configAPI，自动处理认证和401错误
      const result = await configAPI.getYamlConfig();

      setYamlContent(result.content);
      setYamlParsed(result.parsed || {});

      // 同步到表单状态
      syncYamlToForm(result.parsed || {});

      showNotification({
        type: "success",
        title: "YAML加载成功",
        message: "已获取global.yaml内容",
        duration: 2000,
      });
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "加载YAML失败";
      setError(errorMsg);
      setBackendUnavailable(true);

      // 401错误已由 fetchAPI 拦截器统一处理，这里只需显示用户友好的提示
      showNotification({
        type: "error",
        title: "YAML加载失败",
        message: errorMsg,
        duration: 5000,
      });
    } finally {
      setLoading(false);
    }
  }, [showNotification]);

  // 加载备份列表
  const loadBackups = useCallback(async () => {
    try {
      setLoadingBackups(true);
      const result = await configAPI.getBackupList();
      setBackups(result.backups);
      setMaxBackups(result.max_backups);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "加载备份列表失败";
      showNotification({
        type: "error",
        title: "备份列表加载失败",
        message: errorMsg,
        duration: 3000,
      });
    } finally {
      setLoadingBackups(false);
    }
  }, [showNotification]);

  // 恢复备份
  const handleRestoreBackup = async (backupFilename: string) => {
    if (
      !confirm(
        `确定要从备份 "${backupFilename}" 恢复配置吗？\n\n当前配置将被自动备份。`,
      )
    ) {
      return;
    }

    try {
      setRestoring(true);
      const result = await configAPI.restoreBackup(backupFilename);

      showNotification({
        type: "success",
        title: "恢复成功",
        message: result.message,
        duration: 3000,
      });

      // 刷新备份列表
      await loadBackups();

      // 如果当前在YAML模式，刷新YAML内容
      if (viewMode === "yaml") {
        await loadYaml();
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "恢复备份失败";
      showNotification({
        type: "error",
        title: "恢复失败",
        message: errorMsg,
        duration: 5000,
      });
    } finally {
      setRestoring(false);
    }
  };

  // 将YAML数据同步到表单
  const syncYamlToForm = (yamlData: Record<string, any>) => {
    const newConfig = { ...config };

    // 使用映射将YAML路径转换为表单字段
    Object.entries(configMapping).forEach(([formKey, yamlPath]) => {
      const value = getNestedValue(yamlData, yamlPath);
      if (value !== undefined) {
        // S-2 Fix: voice_wake_word 在 YAML 中是列表，表单中是字符串
        if (formKey === "voice_wake_word" && Array.isArray(value)) {
          (newConfig as any)[formKey] = value[0] || "";
        } else {
          (newConfig as any)[formKey] = value;
        }
      }
    });

    // 单独处理AI模型和视觉模型（已移至AIConfigPage，但仍需显示）
    const aiModel =
      getNestedValue(yamlData, "ai.default_model") ||
      getNestedValue(yamlData, "ai.config.model");
    if (aiModel !== undefined) {
      newConfig.model_name = aiModel;
    }

    const visionModel = getNestedValue(yamlData, "ai.vision_model");
    if (visionModel !== undefined) {
      newConfig.vision_model = visionModel;
    }

    setConfig(newConfig);
  };

  // 将表单数据同步到YAML
  const syncFormToYaml = (formData: ConfigData): Record<string, any> => {
    const newYaml = { ...yamlParsed };

    Object.entries(configMapping).forEach(([formKey, yamlPath]) => {
      const value = formData[formKey as keyof ConfigData];
      if (value !== undefined) {
        // S-2 Fix: voice_wake_word 在表单中是字符串，YAML 中需要是列表
        if (formKey === "voice_wake_word" && typeof value === "string") {
          setNestedValue(newYaml, yamlPath, [value]);
        } else {
          setNestedValue(newYaml, yamlPath, value);
        }
      }
    });

    return newYaml;
  };

  // 获取嵌套值
  const getNestedValue = (obj: any, path: string): any => {
    return path.split(".").reduce((acc, key) => acc?.[key], obj);
  };

  // 设置嵌套值
  const setNestedValue = (obj: any, path: string, value: any) => {
    const keys = path.split(".");
    const lastKey = keys.pop()!;
    const target = keys.reduce((acc, key) => {
      if (!acc[key]) acc[key] = {};
      return acc[key];
    }, obj);
    target[lastKey] = value;
  };

  // 初始加载
  useEffect(() => {
    if (viewMode === "form") {
      loadConfig();
    } else if (viewMode === "yaml") {
      loadYaml();
    } else if (viewMode === "backups") {
      loadBackups();
    }
  }, [viewMode, loadConfig, loadYaml, loadBackups]);

  // 页面加载时从后端获取当前模式
  useEffect(() => {
    fetchCurrentMode();
  }, [fetchCurrentMode]);

  // 监听 modeStore 变化，同步到表单配置
  useEffect(() => {
    // modeStore 的 mode 已经是 'daily' | 'focus'，与 ConfigData.work_mode 类型一致
    setConfig((prev) => ({
      ...prev,
      work_mode: mode,
    }));
  }, [mode]);

  // 当后端连接状态改变时刷新
  useEffect(() => {
    if (isBackendConnected && backendUnavailable) {
      if (viewMode === "form") {
        loadConfig();
      } else {
        loadYaml();
      }
    }
  }, [isBackendConnected, backendUnavailable, viewMode, loadConfig, loadYaml]);

  // 验证YAML
  const validateYaml = (
    content: string,
  ): { valid: boolean; error?: string; parsed?: any } => {
    try {
      const parsed = YAML.parse(content);
      return { valid: true, parsed };
    } catch (e) {
      return {
        valid: false,
        error: e instanceof Error ? e.message : "YAML解析错误",
      };
    }
  };

  // 处理YAML变化
  const handleYamlChange = (content: string) => {
    setYamlContent(content);
    const validation = validateYaml(content);

    if (!validation.valid) {
      setYamlError(validation.error || "YAML格式错误");
    } else {
      setYamlError(null);
      setYamlParsed(validation.parsed || {});
    }
  };

  // 在YAML模式下通过结构化表单修改配置，同步回YAML内容
  const handleYamlFieldChange = (key: keyof ConfigData, value: any) => {
    const newConfig = { ...config, [key]: value };
    setConfig(newConfig);
    if (key === "work_mode") {
      const newMode = value as ModeType;
      switchMode(newMode);
    }
    const newYamlData = syncFormToYaml(newConfig);
    setYamlParsed(newYamlData);
    setYamlContent(YAML.stringify(newYamlData, { indent: 2 }));
  };

  // 保存表单配置
  const handleSaveForm = async () => {
    if (!config) return;

    if (!isBackendConnected) {
      showNotification({
        type: "error",
        title: "无法保存",
        message: "后端服务未连接，请启动后端后再试",
        duration: 5000,
      });
      return;
    }

    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      // 排除 model_name，因为它已在 AIConfigPage 统一管理
      const { model_name, ...configWithoutModel } = config;
      const result = await configAPI.updateConfig(configWithoutModel);
      setSuccess(result.message);
      showNotification({
        type: "success",
        title: "保存成功",
        message: result.message,
        duration: 3000,
      });

      // 同步到YAML
      const newYamlData = syncFormToYaml(config);
      setYamlParsed(newYamlData);

      // 同步更新 modeStore（如果工作模式变更）
      if (config.work_mode === "daily" || config.work_mode === "focus") {
        const { switchMode } = useModeStore.getState();
        await switchMode(config.work_mode);
      }

      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "保存配置失败";
      setError(errorMsg);
      showNotification({
        type: "error",
        title: "保存失败",
        message: errorMsg,
        duration: 5000,
      });
    } finally {
      setSaving(false);
    }
  };

  // 保存YAML配置
  const handleSaveYaml = async () => {
    if (!isBackendConnected) {
      showNotification({
        type: "error",
        title: "无法保存",
        message: "后端服务未连接，请启动后端后再试",
        duration: 5000,
      });
      return;
    }

    // 验证YAML
    const validation = validateYaml(yamlContent);
    if (!validation.valid) {
      setYamlError(validation.error || "YAML格式错误");
      showNotification({
        type: "error",
        title: "YAML格式错误",
        message: validation.error || "请检查YAML格式",
        duration: 5000,
      });
      return;
    }

    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      // 使用统一的 configAPI，自动处理认证和401错误
      const result = await configAPI.saveYamlConfig(yamlContent);

      setSuccess(result.message);
      setYamlParsed(result.data?.parsed || validation.parsed || {});

      // 同步到表单
      syncYamlToForm(result.data?.parsed || validation.parsed || {});

      showNotification({
        type: "success",
        title: "保存成功",
        message: result.message,
        duration: 3000,
      });

      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "保存YAML失败";
      setError(errorMsg);
      showNotification({
        type: "error",
        title: "保存失败",
        message: errorMsg,
        duration: 5000,
      });
    } finally {
      setSaving(false);
    }
  };

  // 手动触发热重载
  const handleReload = async () => {
    try {
      setReloading(true);

      // 使用统一的 configAPI，自动处理认证和401错误
      const result = await configAPI.reloadConfig();

      showNotification({
        type: "success",
        title: "热重载成功",
        message: result.message,
        duration: 3000,
      });
      // 刷新显示
      if (viewMode === "form") {
        await loadConfig();
      } else {
        await loadYaml();
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "热重载失败";
      showNotification({
        type: "error",
        title: "热重载失败",
        message: errorMsg,
        duration: 5000,
      });
    } finally {
      setReloading(false);
    }
  };

  // 切换视图模式
  const handleModeSwitch = (newMode: ViewMode) => {
    if (newMode === viewMode) return;

    if (newMode === "yaml") {
      // 切换到YAML模式，同步表单数据
      const newYamlData = syncFormToYaml(config);
      const yamlString = YAML.stringify(newYamlData, { indent: 2 });
      setYamlContent(yamlString);
      setYamlParsed(newYamlData);
    } else if (newMode === "form") {
      // 切换到表单模式，同步YAML数据
      syncYamlToForm(yamlParsed);
    } else if (newMode === "backups") {
      // 切换到备份模式，加载备份列表
      loadBackups();
    }

    setViewMode(newMode);
    setError(null);
    setYamlError(null);
  };

  const handleChange = (key: keyof ConfigData, value: any) => {
    // 如果是工作模式变更，同步到 modeStore
    if (key === "work_mode") {
      const newMode = value as ModeType;
      switchMode(newMode);
    }
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  // 测试语音
  const handleTestVoice = async () => {
    if (!isBackendConnected) {
      showNotification({
        type: "warning",
        title: "后端未连接",
        message: "无法测试语音，请确保后端服务已启动",
        duration: 3000,
      });
      return;
    }
    try {
      const response = await authFetch("/api/voice/test", {
        method: "POST",
        body: JSON.stringify({ text: "你好，我是硅基生命体，语音测试成功" }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      showNotification({
        type: "success",
        title: "语音测试已发送",
        message: "正在播放测试语音",
        duration: 3000,
      });
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "语音测试失败";
      showNotification({
        type: "error",
        title: "语音测试失败",
        message: errorMsg,
        duration: 5000,
      });
    }
  };

  const togglePasswordVisibility = (key: string) => {
    setShowPassword((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const renderField = (
    key: string,
    fieldSchema: ConfigSchema[string],
    onChangeOverride?: (key: keyof ConfigData, value: any) => void,
  ) => {
    if (!config) return null;

    let value = config[key as keyof ConfigData];
    const { type, options, min, max, step, placeholder } = fieldSchema;
    const isPassword =
      key.toLowerCase().includes("key") || key.toLowerCase().includes("secret");
    const disabled = !isBackendConnected;
    const changeHandler = onChangeOverride || handleChange;

    // 确保value不为undefined，防止受控组件变为非受控
    if (value === undefined) {
      switch (type) {
        case "boolean":
          value = false;
          break;
        case "number":
        case "integer":
          value = 0;
          break;
        case "array":
          value = [];
          break;
        case "select":
        case "string":
        default:
          value = "";
          break;
      }
    }

    switch (type) {
      case "select": {
        // 处理选项格式：字符串数组或对象数组 {value, label}
        const normalizedOptions = options?.map((opt) => {
          if (typeof opt === "string") {
            return { value: opt, label: opt };
          }
          return opt;
        });
        // 确保value在options中，如果不在则使用第一个选项
        const currentValue = (value as string) || "";
        const validValue = normalizedOptions?.some(
          (opt) => opt.value === currentValue,
        )
          ? currentValue
          : normalizedOptions?.[0]?.value || "";
        return (
          <select
            value={validValue}
            onChange={(e) =>
              changeHandler(key as keyof ConfigData, e.target.value)
            }
            disabled={disabled}
            className="w-full bg-sb-bg-secondary border border-white/10 rounded-lg px-4 py-2 text-white focus:border-sb-cyan outline-none disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {normalizedOptions?.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        );
      }

      case "boolean": {
        // 确保checked始终是布尔值
        const checkedValue = Boolean(value);
        return (
          <label
            className={`flex items-center gap-3 cursor-pointer ${disabled ? "opacity-50" : ""}`}
          >
            <input
              type="checkbox"
              checked={checkedValue}
              onChange={(e) =>
                changeHandler(key as keyof ConfigData, e.target.checked)
              }
              disabled={disabled}
              className="w-5 h-5 rounded border-white/20 bg-sb-bg-secondary text-sb-cyan focus:ring-sb-cyan disabled:cursor-not-allowed"
            />
            <span className="text-sb-text-secondary">
              {checkedValue ? "已启用" : "已禁用"}
            </span>
          </label>
        );
      }

      case "number": {
        // 确保number是有效数字
        const numValue = typeof value === "number" ? value : 0;
        return (
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={min}
              max={max}
              step={step}
              value={numValue}
              onChange={(e) =>
                changeHandler(
                  key as keyof ConfigData,
                  parseFloat(e.target.value),
                )
              }
              disabled={disabled}
              className="flex-1 h-2 bg-sb-bg-secondary rounded-lg appearance-none cursor-pointer accent-sb-cyan disabled:opacity-50 disabled:cursor-not-allowed"
            />
            <span className="text-sb-cyan w-16 text-right">
              {numValue.toFixed(1)}
            </span>
          </div>
        );
      }

      case "integer": {
        // 确保integer是有效整数
        const intValue = typeof value === "number" ? Math.floor(value) : 0;
        return (
          <input
            type="number"
            min={min}
            max={max}
            value={intValue}
            onChange={(e) =>
              changeHandler(
                key as keyof ConfigData,
                parseInt(e.target.value) || 0,
              )
            }
            placeholder={placeholder}
            disabled={disabled}
            className="w-full bg-sb-bg-secondary border border-white/10 rounded-lg px-4 py-2 text-white focus:border-sb-cyan outline-none disabled:opacity-50 disabled:cursor-not-allowed"
          />
        );
      }

      case "array": {
        // 确保array是有效数组
        const arrValue = Array.isArray(value) ? value : [];
        // Tool Whitelist 使用多选下拉框（支持手动输入切换）
        if (
          key === "tool_whitelist" &&
          availableTools.length > 0 &&
          !toolManualMode
        ) {
          return (
            <div className="space-y-2">
              <div className="flex flex-wrap gap-2">
                {availableTools.map((tool) => {
                  const isSelected = arrValue.includes(tool);
                  return (
                    <button
                      key={tool}
                      type="button"
                      onClick={() => {
                        const newValue = isSelected
                          ? arrValue.filter((v: string) => v !== tool)
                          : [...arrValue, tool];
                        changeHandler(key as keyof ConfigData, newValue);
                      }}
                      disabled={disabled}
                      className={`px-2 py-1 text-xs rounded border transition-colors ${
                        isSelected
                          ? "bg-sb-cyan/20 text-sb-cyan border-sb-cyan/50"
                          : "bg-sb-bg-secondary/50 text-sb-text-secondary border-transparent hover:bg-sb-bg-secondary"
                      } disabled:opacity-50`}
                    >
                      {isSelected ? "✓ " : ""}
                      {tool}
                    </button>
                  );
                })}
              </div>
              <button
                type="button"
                onClick={() => setToolManualMode(true)}
                className="text-xs text-sb-cyan hover:text-sb-cyan-hover transition-colors"
              >
                切换到手动输入模式
              </button>
            </div>
          );
        }
        return (
          <div className="space-y-2">
            <textarea
              value={arrValue.join("\n")}
              onChange={(e) =>
                changeHandler(
                  key as keyof ConfigData,
                  e.target.value.split("\n").filter(Boolean),
                )
              }
              placeholder="每行一个项目"
              rows={4}
              disabled={disabled}
              className="w-full bg-sb-bg-secondary border border-white/10 rounded-lg px-4 py-2 text-white focus:border-sb-cyan outline-none resize-none disabled:opacity-50 disabled:cursor-not-allowed"
            />
            <p className="text-xs text-sb-text-secondary">每行输入一个项目</p>
            {key === "tool_whitelist" && availableTools.length > 0 && (
              <button
                type="button"
                onClick={() => setToolManualMode(false)}
                className="text-xs text-sb-cyan hover:text-sb-cyan-hover transition-colors"
              >
                切换到多选模式
              </button>
            )}
          </div>
        );
      }

      default: {
        // 确保string是有效字符串
        const strValue = String(value ?? "");
        if (isPassword) {
          return (
            <div className="relative">
              <input
                type={showPassword[key] ? "text" : "password"}
                value={strValue}
                onChange={(e) =>
                  changeHandler(key as keyof ConfigData, e.target.value)
                }
                disabled={disabled}
                placeholder={placeholder || "留空表示不保存到配置文件"}
                className="w-full bg-sb-bg-secondary border border-white/10 rounded-lg px-4 py-2 pr-10 text-white focus:border-sb-cyan outline-none disabled:opacity-50 disabled:cursor-not-allowed"
              />
              <button
                type="button"
                onClick={() => togglePasswordVisibility(key)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-sb-text-secondary hover:text-white transition-colors"
              >
                {showPassword[key] ? (
                  <EyeOff className="w-4 h-4" />
                ) : (
                  <Eye className="w-4 h-4" />
                )}
              </button>
            </div>
          );
        }
        return (
          <input
            type="text"
            value={strValue}
            onChange={(e) =>
              changeHandler(key as keyof ConfigData, e.target.value)
            }
            placeholder={placeholder}
            disabled={disabled}
            className="w-full bg-sb-bg-secondary border border-white/10 rounded-lg px-4 py-2 text-white focus:border-sb-cyan outline-none disabled:opacity-50 disabled:cursor-not-allowed"
          />
        );
      }
    }
  };

  return (
    <div className="h-full overflow-auto p-6">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* 标题 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Settings className="w-6 h-6 text-sb-cyan" />
            <h1 className="text-2xl font-bold text-white">系统设置</h1>
            {!isBackendConnected && (
              <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 text-xs border border-red-500/20">
                <WifiOff className="w-3 h-3" />
                离线模式
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {/* 视图切换按钮 */}
            <div className="flex items-center bg-sb-bg-secondary rounded-lg p-1 mr-2">
              <button
                onClick={() => handleModeSwitch("form")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors ${
                  viewMode === "form"
                    ? "bg-sb-cyan text-sb-bg-primary"
                    : "text-sb-text-secondary hover:text-white"
                }`}
              >
                <FormInput className="w-4 h-4" />
                表单
              </button>
              <button
                onClick={() => handleModeSwitch("yaml")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors ${
                  viewMode === "yaml"
                    ? "bg-sb-cyan text-sb-bg-primary"
                    : "text-sb-text-secondary hover:text-white"
                }`}
              >
                <FileCode className="w-4 h-4" />
                YAML
              </button>
              <button
                onClick={() => handleModeSwitch("backups")}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors ${
                  viewMode === "backups"
                    ? "bg-sb-cyan text-sb-bg-primary"
                    : "text-sb-text-secondary hover:text-white"
                }`}
              >
                <Archive className="w-4 h-4" />
                备份
              </button>
            </div>

            {viewMode !== "backups" && (
              <>
                <button
                  onClick={viewMode === "form" ? loadConfig : loadYaml}
                  disabled={loading || !isBackendConnected}
                  className="flex items-center gap-2 px-4 py-2 text-sb-text-secondary hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <RotateCcw
                    className={`w-4 h-4 ${loading ? "animate-spin" : ""}`}
                  />
                  刷新
                </button>

                <button
                  onClick={handleReload}
                  disabled={reloading || !isBackendConnected}
                  className="flex items-center gap-2 px-4 py-2 text-sb-text-secondary hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  title="手动触发热重载"
                >
                  <RefreshCw
                    className={`w-4 h-4 ${reloading ? "animate-spin" : ""}`}
                  />
                  重载
                </button>

                <button
                  onClick={
                    viewMode === "form" ? handleSaveForm : handleSaveYaml
                  }
                  disabled={
                    saving ||
                    !isBackendConnected ||
                    (viewMode === "yaml" && !!yamlError)
                  }
                  className="flex items-center gap-2 px-6 py-2 bg-sb-cyan text-sb-bg-primary rounded-lg hover:bg-sb-cyan-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Save className="w-4 h-4" />
                  {saving ? "保存中..." : "保存"}
                </button>
                {viewMode === "yaml" && yamlError && (
                  <span className="text-xs text-red-400 flex items-center gap-1">
                    <AlertCircle className="w-3.5 h-3.5" />
                    YAML格式错误，请修正后再保存
                  </span>
                )}
              </>
            )}
          </div>
        </div>

        {/* 后端离线提示 */}
        {!isBackendConnected && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-3 p-4 bg-yellow-500/10 border border-yellow-500/30 rounded-lg text-yellow-400"
          >
            <Server className="w-5 h-5" />
            <div className="flex-1">
              <p className="font-medium">后端服务未连接</p>
              <p className="text-sm opacity-80">
                配置已加载默认值，但无法保存。请启动后端服务后再试。
              </p>
            </div>
          </motion.div>
        )}

        {/* 状态提示 */}
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-2 p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400"
          >
            <AlertCircle className="w-5 h-5" />
            {error}
          </motion.div>
        )}

        {success && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-2 p-4 bg-green-500/10 border border-green-500/30 rounded-lg text-green-400"
          >
            <CheckCircle className="w-5 h-5" />
            {success}
          </motion.div>
        )}

        {/* YAML错误提示 */}
        {viewMode === "yaml" && yamlError && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-start gap-2 p-4 bg-orange-500/10 border border-orange-500/30 rounded-lg text-orange-400"
          >
            <AlertCircle className="w-5 h-5 mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <p className="font-medium">YAML格式错误</p>
              <pre className="text-sm opacity-80 mt-1 whitespace-pre-wrap">
                {yamlError}
              </pre>
            </div>
          </motion.div>
        )}

        {/* 内容区域 */}
        <div className="relative">
          <AnimatePresence mode="wait">
            {viewMode === "form" ? (
              <motion.div
                key="form"
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 20 }}
                transition={{ duration: 0.2 }}
                className="grid grid-cols-1 md:grid-cols-2 gap-6"
              >
                {/* AI 模型 - 只读显示，统一到 AIConfigPage 管理 */}
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0 }}
                  className="bg-sb-bg-secondary/50 border border-white/5 rounded-xl p-6 hover:border-sb-cyan/30 transition-colors"
                >
                  <div className="flex items-center justify-between mb-3">
                    <label className="text-sm font-medium text-sb-text-secondary flex items-center gap-2">
                      <Cpu className="w-4 h-4 text-sb-cyan" />
                      AI 模型
                      <span className="text-xs text-sb-text-secondary/50">
                        ai.config.model
                      </span>
                    </label>
                    <button
                      onClick={() => navigate("/aiconfig")}
                      className="flex items-center gap-1 px-2 py-1 text-xs text-sb-cyan hover:text-sb-cyan-hover bg-sb-cyan/10 hover:bg-sb-cyan/20 rounded transition-colors"
                      title="前往 AI 配置页面进行详细设置"
                    >
                      <ExternalLink className="w-3 h-3" />
                      去配置
                    </button>
                  </div>
                  <p className="text-xs text-white/50 mb-3">
                    当前使用的AI模型。点击"去配置"可切换模型提供商、API密钥等详细设置。
                  </p>
                  <div className="w-full bg-sb-bg-secondary border border-white/10 rounded-lg px-4 py-2 text-white flex items-center justify-between">
                    <span className="font-mono text-sm">
                      {config?.model_name || "qwen3:8b"}
                    </span>
                    <span className="text-xs text-white/30">只读</span>
                  </div>
                </motion.div>

                {/* 视觉模型 - 只读显示，统一到 AIConfigPage 管理 */}
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.02 }}
                  className="bg-sb-bg-secondary/50 border border-white/5 rounded-xl p-6 hover:border-purple-500/30 transition-colors"
                >
                  <div className="flex items-center justify-between mb-3">
                    <label className="text-sm font-medium text-sb-text-secondary flex items-center gap-2">
                      <Eye className="w-4 h-4 text-purple-400" />
                      视觉模型
                      <span className="text-xs text-sb-text-secondary/50">
                        ai.vision_model
                      </span>
                    </label>
                    <button
                      onClick={() => navigate("/aiconfig")}
                      className="flex items-center gap-1 px-2 py-1 text-xs text-purple-400 hover:text-purple-300 bg-purple-400/10 hover:bg-purple-400/20 rounded transition-colors"
                      title="前往 AI 配置页面进行详细设置"
                    >
                      <ExternalLink className="w-3 h-3" />
                      去配置
                    </button>
                  </div>
                  <p className="text-xs text-white/50 mb-3">
                    当前使用的视觉识别模型，用于截图分析、UI元素定位等视觉任务。
                  </p>
                  <div className="w-full bg-sb-bg-secondary border border-white/10 rounded-lg px-4 py-2 text-white flex items-center justify-between">
                    <span className="font-mono text-sm">
                      {config?.vision_model || "未配置"}
                    </span>
                    <span className="text-xs text-white/30">只读</span>
                  </div>
                </motion.div>

                {schema &&
                  Object.entries(schema).map(([key, fieldSchema], index) => (
                    <motion.div
                      key={key}
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: (index + 1) * 0.05 }}
                      className="bg-sb-bg-secondary/50 border border-white/5 rounded-xl p-6 hover:border-sb-cyan/30 transition-colors"
                    >
                      <label className="block text-sm font-medium text-sb-text-secondary mb-3">
                        {fieldSchema.label}
                        <span className="ml-2 text-xs text-sb-text-secondary/50">
                          {configMapping[key]}
                        </span>
                      </label>
                      {fieldSchema.description && (
                        <p className="text-xs text-white/50 mb-2">
                          {fieldSchema.description}
                        </p>
                      )}
                      {renderField(key, fieldSchema)}
                      {key === "voice_tts_engine" && (
                        <button
                          onClick={handleTestVoice}
                          disabled={!isBackendConnected}
                          className="mt-3 flex items-center gap-2 px-4 py-2 text-sm text-sb-cyan hover:bg-sb-cyan/10 rounded-lg border border-sb-cyan/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <Volume2 className="w-4 h-4" />
                          测试语音
                        </button>
                      )}
                    </motion.div>
                  ))}

                {/* 交易所配置 */}
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{
                    delay: (Object.entries(schema).length + 1) * 0.05,
                  }}
                  className="bg-sb-bg-secondary/50 border border-white/5 rounded-xl p-6 hover:border-sb-cyan/30 transition-colors md:col-span-2"
                >
                  <ExchangeConfigPanel />
                </motion.div>

                {/* 道德过滤设置 */}
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{
                    delay: (Object.entries(schema).length + 2) * 0.05,
                  }}
                  className="bg-sb-bg-secondary/50 border border-white/5 rounded-xl p-6 hover:border-sb-cyan/30 transition-colors md:col-span-2"
                >
                  <MoralFilterSettings />
                </motion.div>

                {/* MCP 服务开关 */}
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{
                    delay: (Object.entries(schema).length + 3) * 0.05,
                  }}
                  className="bg-sb-bg-secondary/50 border border-white/5 rounded-xl p-6 hover:border-sb-cyan/30 transition-colors md:col-span-2"
                >
                  <MCPConfigPanel />
                </motion.div>

                {/* 语音播报配置 */}
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{
                    delay: (Object.entries(schema).length + 4) * 0.05,
                  }}
                  className="bg-sb-bg-secondary/50 border border-white/5 rounded-xl p-6 hover:border-sb-cyan/30 transition-colors md:col-span-2"
                >
                  <VoiceAnnounceConfigPanel />
                </motion.div>
              </motion.div>
            ) : viewMode === "yaml" ? (
              <motion.div
                key="yaml"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                transition={{ duration: 0.2 }}
                className="bg-sb-bg-secondary/50 border border-white/5 rounded-xl overflow-hidden"
              >
                {/* YAML编辑器头部 */}
                <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-sb-bg-secondary">
                  <div className="flex items-center gap-2">
                    <FileCode className="w-4 h-4 text-sb-cyan" />
                    <span className="text-sm font-medium text-white">
                      config/global.yaml
                    </span>
                    <span className="text-xs text-sb-text-secondary ml-2">
                      直接编辑YAML，保存后自动热重载
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-xs px-2 py-1 rounded ${yamlError ? "bg-red-500/20 text-red-400" : "bg-green-500/20 text-green-400"}`}
                    >
                      {yamlError ? "格式错误" : "格式正确"}
                    </span>
                  </div>
                </div>

                {/* 结构化编辑面板 */}
                <div className="px-4 py-4 border-b border-white/5">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                      <FormInput className="w-4 h-4 text-sb-cyan" />
                      <span className="text-sm font-medium text-white">
                        快速编辑
                      </span>
                      <span className="text-xs text-sb-text-secondary">
                        修改后自动同步到YAML内容
                      </span>
                    </div>
                    <button
                      onClick={() => setYamlAdvancedMode((prev) => !prev)}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-sb-cyan hover:bg-sb-cyan/10 rounded transition-colors"
                    >
                      <FileCode className="w-3.5 h-3.5" />
                      {yamlAdvancedMode ? "收起高级模式" : "展开高级模式"}
                    </button>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {schema &&
                      Object.entries(schema).map(([key, fieldSchema]) => (
                        <div
                          key={key}
                          className={`bg-sb-bg-primary/50 border border-white/5 rounded-lg p-4 ${fieldSchema.type === "array" ? "md:col-span-2" : ""}`}
                        >
                          <label className="block text-sm font-medium text-sb-text-secondary mb-2">
                            {fieldSchema.label}
                            <span className="ml-2 text-xs text-sb-text-secondary/50">
                              {configMapping[key]}
                            </span>
                          </label>
                          {fieldSchema.description && (
                            <p className="text-xs text-white/50 mb-2">
                              {fieldSchema.description}
                            </p>
                          )}
                          {renderField(key, fieldSchema, handleYamlFieldChange)}
                          {key === "voice_tts_engine" && (
                            <button
                              onClick={handleTestVoice}
                              disabled={!isBackendConnected}
                              className="mt-3 flex items-center gap-2 px-4 py-2 text-sm text-sb-cyan hover:bg-sb-cyan/10 rounded-lg border border-sb-cyan/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              <Volume2 className="w-4 h-4" />
                              测试语音
                            </button>
                          )}
                        </div>
                      ))}
                  </div>
                </div>

                {/* 高级模式：YAML编辑器 */}
                {yamlAdvancedMode && (
                  <textarea
                    value={yamlContent}
                    onChange={(e) => handleYamlChange(e.target.value)}
                    disabled={!isBackendConnected}
                    spellCheck={false}
                    className={`w-full h-[400px] bg-[#1e1e1e] text-gray-300 font-mono text-sm p-4 resize-none focus:outline-none disabled:opacity-50 ${
                      yamlError ? "border-2 border-red-500/50" : ""
                    }`}
                    style={{
                      lineHeight: "1.6",
                      tabSize: 2,
                    }}
                  />
                )}

                {/* 底部提示 */}
                <div className="px-4 py-2 border-t border-white/5 bg-sb-bg-secondary text-xs text-sb-text-secondary">
                  <p>
                    提示：
                    {yamlAdvancedMode
                      ? '修改后点击右上角"保存"按钮，系统将自动将YAML写入global.yaml并触发热重载。所有配置变更将立即生效。'
                      : '在"快速编辑"面板中修改配置会自动同步到YAML，点击右上角"保存"即可生效。'}
                  </p>
                </div>
              </motion.div>
            ) : (
              <motion.div
                key="backups"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                transition={{ duration: 0.2 }}
                className="bg-sb-bg-secondary/50 border border-white/5 rounded-xl overflow-hidden"
              >
                {/* 备份管理头部 */}
                <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-sb-bg-secondary">
                  <div className="flex items-center gap-2">
                    <Archive className="w-4 h-4 text-sb-cyan" />
                    <span className="text-sm font-medium text-white">
                      配置备份管理
                    </span>
                    <span className="text-xs text-sb-text-secondary ml-2">
                      自动保留最近 {maxBackups} 个备份
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={loadBackups}
                      disabled={loadingBackups}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-sb-text-secondary hover:text-white transition-colors disabled:opacity-50"
                    >
                      <RotateCcw
                        className={`w-3 h-3 ${loadingBackups ? "animate-spin" : ""}`}
                      />
                      刷新
                    </button>
                  </div>
                </div>

                {/* 备份列表 */}
                <div className="p-4">
                  {loadingBackups ? (
                    <div className="flex items-center justify-center py-12">
                      <RefreshCw className="w-6 h-6 text-sb-cyan animate-spin" />
                      <span className="ml-3 text-sb-text-secondary">
                        加载备份列表...
                      </span>
                    </div>
                  ) : backups.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-12 text-sb-text-secondary">
                      <History className="w-12 h-12 mb-4 opacity-30" />
                      <p>暂无备份</p>
                      <p className="text-xs mt-2 opacity-60">
                        每次保存YAML配置时会自动创建备份
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {backups.map((backup, index) => (
                        <motion.div
                          key={backup.filename}
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: index * 0.05 }}
                          className="flex items-center justify-between p-4 bg-sb-bg-primary rounded-lg border border-white/5 hover:border-sb-cyan/30 transition-colors"
                        >
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-lg bg-sb-cyan/10 flex items-center justify-center">
                              <Archive className="w-5 h-5 text-sb-cyan" />
                            </div>
                            <div>
                              <p className="text-sm font-medium text-white">
                                {backup.filename}
                              </p>
                              <p className="text-xs text-sb-text-secondary">
                                {new Date(backup.created).toLocaleString(
                                  "zh-CN",
                                )}{" "}
                                · {(backup.size / 1024).toFixed(1)} KB
                              </p>
                            </div>
                          </div>
                          <button
                            onClick={() => handleRestoreBackup(backup.filename)}
                            disabled={restoring || !isBackendConnected}
                            className="flex items-center gap-1.5 px-4 py-2 text-sm text-sb-cyan hover:bg-sb-cyan/10 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            <RestoreIcon className="w-4 h-4" />
                            {restoring ? "恢复中..." : "恢复"}
                          </button>
                        </motion.div>
                      ))}
                    </div>
                  )}
                </div>

                {/* 底部提示 */}
                <div className="px-4 py-3 border-t border-white/5 bg-sb-bg-secondary text-xs text-sb-text-secondary">
                  <p>
                    提示：点击"恢复"按钮可以从备份恢复配置。恢复前系统会自动备份当前配置，以防万一。
                  </p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
          {!isBackendConnected && (
            <div className="absolute inset-0 bg-black/20 rounded-lg pointer-events-none z-10" />
          )}
        </div>
      </div>
    </div>
  );
}
