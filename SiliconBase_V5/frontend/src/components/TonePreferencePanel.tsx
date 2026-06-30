/**
 * TonePreferencePanel - 语气偏好设置面板
 *
 * 【设计意图】
 * 允许用户自定义AI的回复语气和风格。
 * 通过调整语气类型和正式程度，让AI回复更符合用户偏好。
 *
 * 【功能】
 * 1. 选择语气类型（正式、随意、幽默、专业等）
 * 2. 调整正式程度滑块
 * 3. 自定义语气参数
 * 4. 实时预览效果
 * 5. 保存用户偏好设置
 */

import React, { useState, useEffect, useCallback } from "react";
import {
  Card,
  Radio,
  Slider,
  Input,
  Button,
  Space,
  Tag,
  Typography,
  Divider,
  message,
  Spin,
  Badge,
  Tooltip,
  Switch,
  Form,
  Alert,
  Modal,
} from "antd";
import {
  MessageOutlined,
  SmileOutlined,
  MehOutlined,
  RocketOutlined,
  BookOutlined,
  ExperimentOutlined,
  SoundOutlined,
  SaveOutlined,
  ReloadOutlined,
  EyeOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
import { fetchAPI } from "../utils/api";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

// 语气类型
export type ToneType =
  | "formal"
  | "casual"
  | "humorous"
  | "professional"
  | "friendly"
  | "concise"
  | "detailed";

// 语气配置接口
export interface ToneConfig {
  type: ToneType;
  formality: number; // 0-100
  enthusiasm: number; // 0-100
  empathy: number; // 0-100
  technicality: number; // 0-100
  custom_prompt?: string;
  enabled: boolean;
}

// 语气预设
export interface TonePreset {
  id: string;
  name: string;
  description: string;
  config: ToneConfig;
  is_builtin: boolean;
}

// 组件属性接口
export interface TonePreferencePanelProps {
  userId?: string;
  showPreview?: boolean;
  className?: string;
  style?: React.CSSProperties;
  onChange?: (config: ToneConfig) => void;
}

// 语气类型配置
const toneTypeConfig: Record<
  ToneType,
  { label: string; icon: React.ReactNode; color: string; description: string }
> = {
  formal: {
    label: "正式",
    icon: <BookOutlined />,
    color: "#1890ff",
    description: "严肃、规范的表达方式，适合商务场合",
  },
  casual: {
    label: "随意",
    icon: <SmileOutlined />,
    color: "#52c41a",
    description: "轻松、自然的对话风格，像朋友聊天",
  },
  humorous: {
    label: "幽默",
    icon: <ExperimentOutlined />,
    color: "#faad14",
    description: "风趣、有趣的表达方式，带有一些俏皮",
  },
  professional: {
    label: "专业",
    icon: <RocketOutlined />,
    color: "#722ed1",
    description: "权威、精准的表达，注重专业性",
  },
  friendly: {
    label: "友善",
    icon: <MehOutlined />,
    color: "#eb2f96",
    description: "温暖、体贴的沟通风格",
  },
  concise: {
    label: "简洁",
    icon: <SoundOutlined />,
    color: "#13c2c2",
    description: "直接、精简的回答，不拖泥带水",
  },
  detailed: {
    label: "详细",
    icon: <InfoCircleOutlined />,
    color: "#2f54eb",
    description: "全面、详尽的解释，包含更多背景信息",
  },
};

// 默认配置
const defaultConfig: ToneConfig = {
  type: "casual",
  formality: 50,
  enthusiasm: 70,
  empathy: 80,
  technicality: 50,
  enabled: true,
};

export const TonePreferencePanel: React.FC<TonePreferencePanelProps> = ({
  userId = "default",
  className = "",
  style,
  onChange,
}) => {
  const [config, setConfig] = useState<ToneConfig>(defaultConfig);
  const [presets, setPresets] = useState<TonePreset[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewText, setPreviewText] = useState("");
  const [form] = Form.useForm();

  // 获取语气配置
  const fetchToneConfig = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetchAPI<{ success: boolean; data: ToneConfig }>(
        `/api/users/${userId}/tone-preference`,
      );
      if (response.data) {
        setConfig(response.data);
        form.setFieldsValue(response.data);
      }
    } catch (error) {
      console.error("[TonePreferencePanel] 获取语气配置失败:", error);
      // 使用默认配置
      setConfig(defaultConfig);
      form.setFieldsValue(defaultConfig);
    } finally {
      setLoading(false);
    }
  }, [userId, form]);

  // 获取预设列表
  const fetchPresets = useCallback(async () => {
    try {
      const response = await fetchAPI<{ success: boolean; data: TonePreset[] }>(
        "/api/tone-presets",
      );
      setPresets(response.data || []);
    } catch (error) {
      console.error("[TonePreferencePanel] 获取预设失败:", error);
    }
  }, []);

  // 初始加载
  useEffect(() => {
    fetchToneConfig();
    fetchPresets();
  }, [fetchToneConfig, fetchPresets]);

  // 保存配置
  const handleSave = async () => {
    try {
      setSaving(true);
      const values = await form.validateFields();

      await fetchAPI(`/api/users/${userId}/tone-preference`, {
        method: "PUT",
        body: values,
      });

      setConfig(values);
      onChange?.(values);
      message.success("语气偏好已保存");
    } catch (error) {
      console.error("[TonePreferencePanel] 保存失败:", error);
      message.error("保存失败");
    } finally {
      setSaving(false);
    }
  };

  // 重置为默认
  const handleReset = () => {
    form.setFieldsValue(defaultConfig);
    setConfig(defaultConfig);
    message.info("已重置为默认设置");
  };

  // 应用预设
  const applyPreset = (preset: TonePreset) => {
    form.setFieldsValue(preset.config);
    setConfig(preset.config);
    message.success(`已应用预设：${preset.name}`);
  };

  // 生成预览
  const generatePreview = async () => {
    try {
      const values = form.getFieldsValue();
      const response = await fetchAPI<{
        success: boolean;
        data: { preview: string };
      }>("/api/tone-preview", {
        method: "POST",
        body: values,
      });
      setPreviewText(response.data.preview);
      setPreviewVisible(true);
    } catch (error) {
      console.error("[TonePreferencePanel] 生成预览失败:", error);
      message.error("生成预览失败");
    }
  };

  // 渲染语气选择按钮
  const renderToneButtons = () => {
    return (
      <Radio.Group
        value={config.type}
        onChange={(e) => {
          const newType = e.target.value as ToneType;
          form.setFieldValue("type", newType);
          setConfig((prev) => ({ ...prev, type: newType }));
        }}
        className="tone-type-group"
      >
        <Space wrap>
          {(Object.keys(toneTypeConfig) as ToneType[]).map((type) => {
            const cfg = toneTypeConfig[type];
            return (
              <Tooltip title={cfg.description} key={type}>
                <Radio.Button
                  value={type}
                  className="tone-type-button"
                  style={{
                    borderColor: config.type === type ? cfg.color : undefined,
                    background:
                      config.type === type ? `${cfg.color}10` : undefined,
                  }}
                >
                  <Space>
                    <span style={{ color: cfg.color }}>{cfg.icon}</span>
                    <span>{cfg.label}</span>
                  </Space>
                </Radio.Button>
              </Tooltip>
            );
          })}
        </Space>
      </Radio.Group>
    );
  };

  // 渲染预设列表
  const renderPresetList = () => {
    if (presets.length === 0) return null;

    return (
      <div className="tone-presets">
        <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
          快速应用预设：
        </Text>
        <Space wrap>
          {presets.map((preset) => (
            <Tag
              key={preset.id}
              color={preset.is_builtin ? "blue" : "green"}
              style={{ cursor: "pointer" }}
              onClick={() => applyPreset(preset)}
            >
              {preset.name}
            </Tag>
          ))}
        </Space>
      </div>
    );
  };

  return (
    <Card
      title={
        <Space>
          <MessageOutlined />
          <span>语气偏好</span>
          {config.enabled && <Badge status="success" text="已启用" />}
        </Space>
      }
      extra={
        <Space>
          <Tooltip title="预览效果">
            <Button
              icon={<EyeOutlined />}
              size="small"
              onClick={generatePreview}
            >
              预览
            </Button>
          </Tooltip>
          <Button icon={<ReloadOutlined />} size="small" onClick={handleReset}>
            重置
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            size="small"
            loading={saving}
            onClick={handleSave}
          >
            保存
          </Button>
        </Space>
      }
      className={`tone-preference-panel ${className}`}
      style={style}
    >
      <Spin spinning={loading}>
        <Form form={form} layout="vertical" initialValues={defaultConfig}>
          {/* 启用开关 */}
          <Form.Item name="enabled" valuePropName="checked">
            <Switch
              checkedChildren="启用"
              unCheckedChildren="禁用"
              onChange={(checked) =>
                setConfig((prev) => ({ ...prev, enabled: checked }))
              }
            />
          </Form.Item>

          {config.enabled && (
            <>
              <Divider>语气类型</Divider>
              <Form.Item
                name="type"
                rules={[{ required: true, message: "请选择语气类型" }]}
              >
                {renderToneButtons()}
              </Form.Item>

              {renderPresetList()}

              <Divider>参数调整</Divider>

              {/* 正式程度 */}
              <Form.Item
                name="formality"
                label={
                  <Space>
                    <span>正式程度</span>
                    <Tooltip title="控制回复的正式程度，从随意到正式">
                      <InfoCircleOutlined />
                    </Tooltip>
                  </Space>
                }
              >
                <Slider
                  min={0}
                  max={100}
                  marks={{
                    0: "随意",
                    50: "平衡",
                    100: "正式",
                  }}
                  tooltip={{ formatter: (value) => `${value}%` }}
                />
              </Form.Item>

              {/* 热情程度 */}
              <Form.Item
                name="enthusiasm"
                label={
                  <Space>
                    <span>热情程度</span>
                    <Tooltip title="控制回复的热情和活力程度">
                      <InfoCircleOutlined />
                    </Tooltip>
                  </Space>
                }
              >
                <Slider
                  min={0}
                  max={100}
                  marks={{
                    0: "冷淡",
                    50: "适中",
                    100: "热情",
                  }}
                  tooltip={{ formatter: (value) => `${value}%` }}
                />
              </Form.Item>

              {/* 同理心 */}
              <Form.Item
                name="empathy"
                label={
                  <Space>
                    <span>同理心</span>
                    <Tooltip title="控制对用户情感的理解和回应程度">
                      <InfoCircleOutlined />
                    </Tooltip>
                  </Space>
                }
              >
                <Slider
                  min={0}
                  max={100}
                  marks={{
                    0: "直接",
                    50: "平衡",
                    100: "共情",
                  }}
                  tooltip={{ formatter: (value) => `${value}%` }}
                />
              </Form.Item>

              {/* 专业程度 */}
              <Form.Item
                name="technicality"
                label={
                  <Space>
                    <span>专业程度</span>
                    <Tooltip title="控制使用专业术语和详细解释的程度">
                      <InfoCircleOutlined />
                    </Tooltip>
                  </Space>
                }
              >
                <Slider
                  min={0}
                  max={100}
                  marks={{
                    0: "通俗",
                    50: "适中",
                    100: "专业",
                  }}
                  tooltip={{ formatter: (value) => `${value}%` }}
                />
              </Form.Item>

              <Divider>自定义提示词（可选）</Divider>
              <Form.Item name="custom_prompt">
                <TextArea
                  rows={3}
                  placeholder="添加额外的自定义提示词，例如：使用Emoji表情、避免使用某些词汇等..."
                />
              </Form.Item>
            </>
          )}
        </Form>

        {/* 配置说明 */}
        <Alert
          message="提示"
          description="语气偏好设置会实时生效，影响AI的所有回复。您可以根据不同场景切换预设配置。"
          type="info"
          showIcon
          style={{ marginTop: 16 }}
        />
      </Spin>

      {/* 预览模态框 */}
      <Modal
        title="语气预览"
        open={previewVisible}
        onOk={() => setPreviewVisible(false)}
        onCancel={() => setPreviewVisible(false)}
        footer={[
          <Button key="close" onClick={() => setPreviewVisible(false)}>
            关闭
          </Button>,
        ]}
      >
        <Space direction="vertical" className="w-full">
          <Text type="secondary">当前配置下的回复示例：</Text>
          <Card className="preview-card">
            <Paragraph>{previewText || "（点击生成预览查看效果）"}</Paragraph>
          </Card>
          <Text type="secondary" style={{ fontSize: 12 }}>
            提示：实际回复会根据具体问题和上下文有所不同
          </Text>
        </Space>
      </Modal>
    </Card>
  );
};

export default TonePreferencePanel;
