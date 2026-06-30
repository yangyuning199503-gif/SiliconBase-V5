/**
 * ReflectionPanel - 反思系统面板
 *
 * 【设计意图】
 * 展示AI在任务执行过程中的反思和学习记录。
 * 反思系统帮助AI从经验中学习，不断改进决策质量。
 *
 * 【功能】
 * 1. 启用/禁用反思系统
 * 2. 显示反思记录列表
 * 3. 显示反思置信度和学习到的教训
 * 4. 支持对反思进行评分和反馈
 * 5. 实时更新反思状态
 */

import React, { useState, useEffect, useCallback } from "react";
import {
  Card,
  Switch,
  List,
  Rate,
  Tag,
  Button,
  Empty,
  Typography,
  Space,
  Badge,
  Tooltip,
  Modal,
  Form,
  Input,
  message,
  Spin,
  Statistic,
  Row,
  Col,
  Divider,
  Timeline,
  Alert,
} from "antd";
import {
  BulbOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  SyncOutlined,
  SettingOutlined,
  HistoryOutlined,
  StarOutlined,
  BarChartOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  EyeInvisibleOutlined,
} from "@ant-design/icons";
import { fetchAPI } from "../utils/api";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;
// Panel from Collapse not used

// 反思类型
export type ReflectionType = "success" | "failure" | "optimization" | "insight";

// 反思记录接口
export interface Reflection {
  id: string;
  type: ReflectionType;
  task_id?: string;
  session_id?: string;
  lesson: string;
  confidence: number;
  context?: Record<string, any>;
  user_rating?: number;
  user_feedback?: string;
  applied_count: number;
  created_at: string;
  updated_at?: string;
  tags?: string[];
  is_archived?: boolean;
}

// 反思统计接口
export interface ReflectionStats {
  total: number;
  by_type: Record<ReflectionType, number>;
  avg_confidence: number;
  avg_user_rating: number;
  recent_count: number;
}

// 组件属性接口
export interface ReflectionPanelProps {
  taskId?: string;
  sessionId?: string;
  showStats?: boolean;
  className?: string;
  style?: React.CSSProperties;
}

// 反思类型配置
const reflectionTypeConfig: Record<
  ReflectionType,
  { label: string; color: string; icon: React.ReactNode }
> = {
  success: {
    label: "成功经验",
    color: "success",
    icon: <CheckCircleOutlined />,
  },
  failure: { label: "失败教训", color: "error", icon: <CloseCircleOutlined /> },
  optimization: {
    label: "优化建议",
    color: "processing",
    icon: <ExperimentOutlined />,
  },
  insight: { label: "深度洞察", color: "warning", icon: <BulbOutlined /> },
};

export const ReflectionPanel: React.FC<ReflectionPanelProps> = ({
  taskId,
  sessionId,
  showStats = true,
  className = "",
  style,
}) => {
  const [enabled, setEnabled] = useState(true);
  const [reflections, setReflections] = useState<Reflection[]>([]);
  const [stats, setStats] = useState<ReflectionStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [settingsVisible, setSettingsVisible] = useState(false);
  const [selectedReflection, setSelectedReflection] =
    useState<Reflection | null>(null);
  const [feedbackForm] = Form.useForm();

  // 获取反思系统状态
  const fetchReflectionStatus = useCallback(async () => {
    try {
      const response = await fetchAPI<{
        success: boolean;
        data: { enabled: boolean };
      }>("/api/reflection/status");
      setEnabled(response.data.enabled);
    } catch (error) {
      console.error("[ReflectionPanel] 获取反思状态失败:", error);
    }
  }, []);

  // 获取反思记录列表
  const fetchReflections = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (taskId) params.set("task_id", taskId);
      if (sessionId) params.set("session_id", sessionId);

      const response = await fetchAPI<{
        success: boolean;
        data: Reflection[] | { reflections: Reflection[]; total?: number };
      }>(`/api/reflections?${params.toString()}`);
      const listData = response.data;
      const reflectionsArray = Array.isArray(listData)
        ? listData
        : listData?.reflections || [];
      setReflections(reflectionsArray);
    } catch (error) {
      console.error("[ReflectionPanel] 获取反思记录失败:", error);
      message.error("获取反思记录失败");
    } finally {
      setLoading(false);
    }
  }, [taskId, sessionId]);

  // 获取反思统计
  const fetchStats = useCallback(async () => {
    if (!showStats) return;

    try {
      const response = await fetchAPI<{
        success: boolean;
        data: ReflectionStats;
      }>("/api/reflections/stats");
      setStats(response.data);
    } catch (error) {
      console.error("[ReflectionPanel] 获取反思统计失败:", error);
    }
  }, [showStats]);

  // 初始加载
  useEffect(() => {
    fetchReflectionStatus();
    fetchReflections();
    fetchStats();

    // 定时刷新
    const interval = setInterval(() => {
      fetchReflections();
      fetchStats();
    }, 10000);

    return () => clearInterval(interval);
  }, [fetchReflectionStatus, fetchReflections, fetchStats]);

  // 切换反思系统开关
  const handleToggleEnabled = async (checked: boolean) => {
    try {
      await fetchAPI("/api/reflection/status", {
        method: "PUT",
        body: { enabled: checked },
      });
      setEnabled(checked);
      message.success(checked ? "反思系统已启用" : "反思系统已禁用");
    } catch (error) {
      console.error("[ReflectionPanel] 切换反思状态失败:", error);
      message.error("操作失败");
    }
  };

  // 提交用户反馈
  const handleSubmitFeedback = async (values: {
    rating: number;
    feedback: string;
  }) => {
    if (!selectedReflection) return;

    try {
      await fetchAPI(`/api/reflections/${selectedReflection.id}/feedback`, {
        method: "POST",
        body: {
          rating: values.rating,
          feedback: values.feedback,
        },
      });
      message.success("反馈提交成功");
      setSelectedReflection(null);
      feedbackForm.resetFields();
      fetchReflections();
      fetchStats();
    } catch (error) {
      console.error("[ReflectionPanel] 提交反馈失败:", error);
      message.error("提交反馈失败");
    }
  };

  // 归档反思
  const handleArchiveReflection = async (reflectionId: string) => {
    try {
      await fetchAPI(`/api/reflections/${reflectionId}/archive`, {
        method: "POST",
      });
      message.success("已归档");
      fetchReflections();
    } catch (error) {
      console.error("[ReflectionPanel] 归档失败:", error);
      message.error("归档失败");
    }
  };

  // 渲染反思类型标签
  const renderTypeTag = (type: ReflectionType) => {
    const config = reflectionTypeConfig[type];
    return (
      <Tag color={config.color} icon={config.icon}>
        {config.label}
      </Tag>
    );
  };

  // 渲染反思项
  const renderReflectionItem = (reflection: Reflection) => {
    return (
      <List.Item
        key={reflection.id}
        className="reflection-item"
        actions={[
          <Tooltip title="提供反馈" key="feedback">
            <Button
              icon={<StarOutlined />}
              size="small"
              onClick={() => {
                setSelectedReflection(reflection);
                feedbackForm.setFieldsValue({
                  rating: reflection.user_rating || 3,
                });
              }}
            >
              反馈
            </Button>
          </Tooltip>,
          <Tooltip title="归档" key="archive">
            <Button
              icon={<EyeInvisibleOutlined />}
              size="small"
              onClick={() => handleArchiveReflection(reflection.id)}
            >
              归档
            </Button>
          </Tooltip>,
        ]}
      >
        <List.Item.Meta
          avatar={
            <div className="reflection-avatar">
              {renderTypeTag(reflection.type)}
            </div>
          }
          title={
            <Space>
              <Rate
                disabled
                value={reflection.confidence}
                count={5}
                style={{ fontSize: 14 }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                置信度: {(reflection.confidence * 20).toFixed(0)}%
              </Text>
              {reflection.user_rating && (
                <Tag color="gold">
                  <StarOutlined /> {reflection.user_rating}/5
                </Tag>
              )}
            </Space>
          }
          description={
            <Space direction="vertical" size="small" className="w-full">
              <Paragraph ellipsis={{ rows: 2, expandable: true }}>
                {reflection.lesson}
              </Paragraph>
              <Space size="small">
                <HistoryOutlined />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {new Date(reflection.created_at).toLocaleString()}
                </Text>
                {reflection.applied_count > 0 && (
                  <Tag color="blue">已应用 {reflection.applied_count} 次</Tag>
                )}
                {reflection.tags?.map((tag) => (
                  <Tag key={tag}>{tag}</Tag>
                ))}
              </Space>
            </Space>
          }
        />
      </List.Item>
    );
  };

  return (
    <Card
      title={
        <Space>
          <BulbOutlined />
          <span>反思系统</span>
          {enabled && <Badge status="processing" />}
          {/* Title is used above */}
        </Space>
      }
      extra={
        <Space>
          <Tooltip title="设置">
            <Button
              icon={<SettingOutlined />}
              size="small"
              onClick={() => setSettingsVisible(true)}
            />
          </Tooltip>
          <Tooltip title="刷新">
            <Button
              icon={<SyncOutlined spin={loading} />}
              size="small"
              onClick={() => {
                fetchReflections();
                fetchStats();
              }}
            />
          </Tooltip>
          <Switch
            checked={enabled}
            onChange={handleToggleEnabled}
            checkedChildren="启用"
            unCheckedChildren="禁用"
          />
        </Space>
      }
      className={`reflection-panel ${className}`}
      style={style}
    >
      {/* 统计信息 */}
      {showStats && stats && (
        <>
          <Row gutter={16} className="reflection-stats">
            <Col span={6}>
              <Statistic
                title="反思总数"
                value={stats.total}
                prefix={<FileTextOutlined />}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="平均置信度"
                value={(stats.avg_confidence * 100).toFixed(1)}
                suffix="%"
                prefix={<BarChartOutlined />}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="用户评分"
                value={stats.avg_user_rating.toFixed(1)}
                suffix="/5"
                prefix={<StarOutlined />}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="近期新增"
                value={stats.recent_count}
                prefix={<HistoryOutlined />}
              />
            </Col>
          </Row>
          <Divider />
        </>
      )}

      {/* 反思列表 */}
      <Spin spinning={loading}>
        {reflections.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={enabled ? "暂无反思记录" : "反思系统已禁用"}
          />
        ) : (
          <List
            itemLayout="vertical"
            dataSource={reflections}
            renderItem={renderReflectionItem}
            pagination={{
              pageSize: 5,
              size: "small",
              showTotal: (total) => `共 ${total} 条`,
            }}
          />
        )}
      </Spin>

      {/* 反馈模态框 */}
      <Modal
        title="对反思进行评分"
        open={!!selectedReflection}
        onOk={() => feedbackForm.submit()}
        onCancel={() => {
          setSelectedReflection(null);
          feedbackForm.resetFields();
        }}
        okText="提交"
        cancelText="取消"
      >
        {selectedReflection && (
          <Form
            form={feedbackForm}
            layout="vertical"
            onFinish={handleSubmitFeedback}
          >
            <Alert
              message="反思内容"
              description={selectedReflection.lesson}
              type="info"
              style={{ marginBottom: 16 }}
            />
            <Form.Item
              name="rating"
              label="评分"
              rules={[{ required: true, message: "请给出评分" }]}
            >
              <Rate count={5} />
            </Form.Item>
            <Form.Item name="feedback" label="补充反馈（可选）">
              <TextArea
                rows={3}
                placeholder="您认为这个反思准确吗？有什么补充建议？"
              />
            </Form.Item>
          </Form>
        )}
      </Modal>

      {/* 设置模态框 */}
      <Modal
        title="反思系统设置"
        open={settingsVisible}
        onOk={() => setSettingsVisible(false)}
        onCancel={() => setSettingsVisible(false)}
        footer={[
          <Button key="close" onClick={() => setSettingsVisible(false)}>
            关闭
          </Button>,
        ]}
      >
        <Space direction="vertical" className="w-full">
          <Alert
            message="关于反思系统"
            description="反思系统会在AI完成任务后自动分析执行过程，总结经验教训。这些反思将用于改进未来的决策质量。"
            type="info"
            showIcon
          />
          <Divider />
          <Text strong>反思类型说明：</Text>
          <Timeline>
            <Timeline.Item color="green">
              <Text>成功经验 - 记录有效的执行策略</Text>
            </Timeline.Item>
            <Timeline.Item color="red">
              <Text>失败教训 - 分析错误原因和避免方法</Text>
            </Timeline.Item>
            <Timeline.Item color="blue">
              <Text>优化建议 - 提出改进执行效率的方法</Text>
            </Timeline.Item>
            <Timeline.Item color="orange">
              <Text>深度洞察 - 发现隐藏的模式和规律</Text>
            </Timeline.Item>
          </Timeline>
        </Space>
      </Modal>
    </Card>
  );
};

export default ReflectionPanel;
