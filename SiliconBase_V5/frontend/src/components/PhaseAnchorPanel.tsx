/**
 * PhaseAnchorPanel - 阶段锚点面板
 *
 * 【设计意图】
 * 用于展示和管理任务执行过程中的关键阶段锚点。
 * 锚点帮助AI在任务执行过程中记住关键状态点，
 * 便于在失败时回滚或在需要时从特定阶段继续。
 *
 * 【功能】
 * 1. 显示任务的阶段锚点列表
 * 2. 添加/编辑/删除锚点
 * 3. 跳转到特定锚点继续执行
 * 4. 实时更新锚点状态
 */

import React, { useState, useEffect, useCallback } from "react";
import {
  Card,
  List,
  Tag,
  Button,
  Input,
  Modal,
  Form,
  Select,
  Space,
  message,
  Empty,
  Tooltip,
  Popconfirm,
  Badge,
  Timeline,
  Typography,
  Spin,
} from "antd";
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  FlagOutlined,
  ClockCircleOutlined,
  CheckCircleOutlined,
  RollbackOutlined,
  PaperClipOutlined,
} from "@ant-design/icons";
// PaperClipOutlined used as anchor icon
import { fetchAPI } from "../utils/api";
import { phaseAnchorAPI } from "../utils/api/phaseAnchor";

const { TextArea } = Input;
const { Text } = Typography;

// 阶段锚点状态类型
export type AnchorStatus = "active" | "completed" | "failed" | "rolled_back";

// 阶段锚点接口
export interface PhaseAnchor {
  id: string;
  task_id: string;
  phase: string;
  description: string;
  status: AnchorStatus;
  checkpoint_data?: Record<string, any>;
  created_at: string;
  updated_at?: string;
  sequence: number;
  tags?: string[];
}

// 组件属性接口
export interface PhaseAnchorPanelProps {
  taskId: string;
  readOnly?: boolean;
  onAnchorSelect?: (anchor: PhaseAnchor) => void;
  onContinueFromAnchor?: (anchorId: string) => void;
  className?: string;
  style?: React.CSSProperties;
}

// 状态颜色映射
const statusColors: Record<AnchorStatus, string> = {
  active: "blue",
  completed: "green",
  failed: "red",
  rolled_back: "orange",
};

// 状态文本映射
const statusLabels: Record<AnchorStatus, string> = {
  active: "进行中",
  completed: "已完成",
  failed: "失败",
  rolled_back: "已回滚",
};

export const PhaseAnchorPanel: React.FC<PhaseAnchorPanelProps> = ({
  taskId,
  readOnly = false,
  onAnchorSelect,
  onContinueFromAnchor,
  className = "",
  style,
}) => {
  const [anchors, setAnchors] = useState<PhaseAnchor[]>([]);
  const [loading, setLoading] = useState(false);
  const [isModalVisible, setIsModalVisible] = useState(false);
  const [editingAnchor, setEditingAnchor] = useState<PhaseAnchor | null>(null);
  const [form] = Form.useForm();

  // 获取阶段锚点列表
  const fetchPhaseAnchors = useCallback(async () => {
    if (!taskId) return;

    try {
      setLoading(true);
      const response = await fetchAPI<{
        success: boolean;
        data?: { anchors: PhaseAnchor[]; total?: number };
        anchors?: PhaseAnchor[];
        total?: number;
      }>(`/api/tasks/${taskId}/anchors`);
      const listData = response.data || response;
      const anchorsArray = listData.anchors || [];
      setAnchors(anchorsArray);
    } catch (error: any) {
      console.error("[PhaseAnchorPanel] 获取阶段锚点失败:", error);
      // 后端尚未实现该路由，对 404 做静默容错
      if (
        error?.message?.includes("Not Found") ||
        error?.message?.includes("404")
      ) {
        console.warn(
          "[PhaseAnchorPanel] /api/tasks/{id}/anchors 后端未实现，显示空列表",
        );
        setAnchors([]);
      } else {
        message.error("获取阶段锚点失败");
      }
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  // 初始加载和定时刷新
  useEffect(() => {
    fetchPhaseAnchors();
    const interval = setInterval(fetchPhaseAnchors, 5000);
    return () => clearInterval(interval);
  }, [fetchPhaseAnchors]);

  // 创建锚点
  const handleCreateAnchor = async (values: any) => {
    try {
      const response = await fetchAPI<{ success: boolean; data: PhaseAnchor }>(
        `/api/tasks/${taskId}/anchors`,
        {
          method: "POST",
          body: {
            title: values.phase,
            phase: values.phase,
            description: values.description,
            status: "active",
            position: anchors.length,
            metadata: { tags: values.tags || [] },
          },
        },
      );

      if (response.success) {
        message.success("锚点创建成功");
        setIsModalVisible(false);
        form.resetFields();
        fetchPhaseAnchors();
      }
    } catch (error) {
      console.error("[PhaseAnchorPanel] 创建锚点失败:", error);
      message.error("创建锚点失败");
    }
  };

  // 更新锚点
  const handleUpdateAnchor = async (values: any) => {
    if (!editingAnchor) return;

    try {
      const response = await fetchAPI<{ success: boolean; data: PhaseAnchor }>(
        `/api/tasks/${taskId}/anchors/${editingAnchor.id}`,
        {
          method: "PUT",
          body: {
            title: values.phase,
            phase: values.phase,
            description: values.description,
            status: values.status,
            metadata: { tags: values.tags || [] },
          },
        },
      );

      if (response.success) {
        message.success("锚点更新成功");
        setIsModalVisible(false);
        setEditingAnchor(null);
        form.resetFields();
        fetchPhaseAnchors();
      }
    } catch (error) {
      console.error("[PhaseAnchorPanel] 更新锚点失败:", error);
      message.error("更新锚点失败");
    }
  };

  // 删除锚点
  const handleDeleteAnchor = async (anchorId: string) => {
    try {
      await fetchAPI(`/api/tasks/${taskId}/anchors/${anchorId}`, {
        method: "DELETE",
      });
      message.success("锚点删除成功");
      fetchPhaseAnchors();
    } catch (error) {
      console.error("[PhaseAnchorPanel] 删除锚点失败:", error);
      message.error("删除锚点失败");
    }
  };

  // 从锚点继续执行
  const handleContinueFromAnchor = async (anchorId: string) => {
    try {
      const result = await phaseAnchorAPI.continueFromAnchor(taskId, {
        anchor_id: anchorId,
      });
      if (result.success) {
        message.success("已从锚点继续执行");
        fetchPhaseAnchors();
        onContinueFromAnchor?.(anchorId);
      } else {
        message.error(result.message || "继续执行失败");
      }
    } catch (error) {
      console.error("[PhaseAnchorPanel] 从锚点继续执行失败:", error);
      message.error("从锚点继续执行失败");
    }
  };

  // 回滚到锚点
  const handleRollbackToAnchor = async (anchorId: string) => {
    try {
      const result = await phaseAnchorAPI.rollbackToAnchor(taskId, {
        anchor_id: anchorId,
        preserve_state: true,
      });
      if (result.success) {
        message.success("已回滚到指定锚点");
        fetchPhaseAnchors();
      } else {
        message.error(result.message || "回滚失败");
      }
    } catch (error) {
      console.error("[PhaseAnchorPanel] 回滚到锚点失败:", error);
      message.error("回滚到锚点失败");
    }
  };

  // 打开创建模态框
  const openCreateModal = () => {
    setEditingAnchor(null);
    form.resetFields();
    setIsModalVisible(true);
  };

  // 打开编辑模态框
  const openEditModal = (anchor: PhaseAnchor) => {
    setEditingAnchor(anchor);
    form.setFieldsValue({
      phase: anchor.phase,
      description: anchor.description,
      status: anchor.status,
      tags: anchor.tags || [],
    });
    setIsModalVisible(true);
  };

  // 渲染锚点项
  const renderAnchorItem = (anchor: PhaseAnchor) => {
    const isClickable = !readOnly && anchor.status === "active";

    return (
      <List.Item
        key={anchor.id}
        className={`phase-anchor-item ${isClickable ? "cursor-pointer hover:bg-slate-800/50" : ""}`}
        onClick={() => isClickable && onAnchorSelect?.(anchor)}
        actions={
          readOnly
            ? undefined
            : [
                <Tooltip title="编辑" key="edit">
                  <Button
                    icon={<EditOutlined />}
                    size="small"
                    onClick={(e) => {
                      e.stopPropagation();
                      openEditModal(anchor);
                    }}
                  />
                </Tooltip>,
                anchor.status === "active" && (
                  <Tooltip title="从此继续" key="continue">
                    <Button
                      icon={<PlayCircleOutlined />}
                      size="small"
                      type="primary"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleContinueFromAnchor(anchor.id);
                      }}
                    />
                  </Tooltip>
                ),
                anchor.status === "active" && (
                  <Tooltip title="回滚到该锚点" key="rollback">
                    <Button
                      icon={<RollbackOutlined />}
                      size="small"
                      danger
                      onClick={(e) => {
                        e.stopPropagation();
                        handleRollbackToAnchor(anchor.id);
                      }}
                    />
                  </Tooltip>
                ),
                <Popconfirm
                  key="delete"
                  title="确认删除"
                  description="删除后无法恢复，是否继续？"
                  onConfirm={(e) => {
                    e?.stopPropagation();
                    handleDeleteAnchor(anchor.id);
                  }}
                  okText="删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                >
                  <Button
                    icon={<DeleteOutlined />}
                    size="small"
                    danger
                    onClick={(e) => e.stopPropagation()}
                  />
                </Popconfirm>,
              ].filter(Boolean)
        }
      >
        <List.Item.Meta
          avatar={
            <Badge status={statusColors[anchor.status] as any}>
              <PaperClipOutlined
                className="text-lg"
                style={{ color: "#1890ff" }}
              />
            </Badge>
          }
          title={
            <Space>
              <Tag color={statusColors[anchor.status]}>
                {statusLabels[anchor.status]}
              </Tag>
              <Text strong>{anchor.phase}</Text>
            </Space>
          }
          description={
            <Space direction="vertical" size="small" className="w-full">
              <Text type="secondary">{anchor.description}</Text>
              <Space size="small">
                <ClockCircleOutlined />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {new Date(anchor.created_at).toLocaleString()}
                </Text>
                {anchor.tags?.map((tag) => (
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
          <FlagOutlined />
          <span>阶段锚点</span>
          <Badge count={anchors.length} showZero />
        </Space>
      }
      extra={
        !readOnly && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            size="small"
            onClick={openCreateModal}
          >
            添加锚点
          </Button>
        )
      }
      className={`phase-anchor-panel ${className}`}
      style={style}
    >
      <Spin spinning={loading}>
        {anchors.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="暂无阶段锚点"
          />
        ) : (
          <Timeline mode="left">
            {anchors.map((anchor) => (
              <Timeline.Item
                key={anchor.id}
                dot={
                  anchor.status === "completed" ? (
                    <CheckCircleOutlined style={{ color: "#52c41a" }} />
                  ) : anchor.status === "failed" ? (
                    <FlagOutlined style={{ color: "#ff4d4f" }} />
                  ) : (
                    <PaperClipOutlined style={{ color: "#1890ff" }} />
                  )
                }
                color={statusColors[anchor.status]}
              >
                {renderAnchorItem(anchor)}
              </Timeline.Item>
            ))}
          </Timeline>
        )}
      </Spin>

      {/* 创建/编辑锚点模态框 */}
      <Modal
        title={editingAnchor ? "编辑锚点" : "创建锚点"}
        open={isModalVisible}
        onOk={() => form.submit()}
        onCancel={() => {
          setIsModalVisible(false);
          setEditingAnchor(null);
          form.resetFields();
        }}
        okText={editingAnchor ? "更新" : "创建"}
        cancelText="取消"
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={editingAnchor ? handleUpdateAnchor : handleCreateAnchor}
        >
          <Form.Item
            name="phase"
            label="阶段名称"
            rules={[{ required: true, message: "请输入阶段名称" }]}
          >
            <Input placeholder="例如：数据预处理" />
          </Form.Item>

          <Form.Item
            name="description"
            label="阶段描述"
            rules={[{ required: true, message: "请输入阶段描述" }]}
          >
            <TextArea rows={3} placeholder="描述此阶段的具体内容和目标" />
          </Form.Item>

          {editingAnchor && (
            <Form.Item name="status" label="状态">
              <Select>
                <Select.Option value="active">进行中</Select.Option>
                <Select.Option value="completed">已完成</Select.Option>
                <Select.Option value="failed">失败</Select.Option>
                <Select.Option value="rolled_back">已回滚</Select.Option>
              </Select>
            </Form.Item>
          )}

          <Form.Item name="tags" label="标签">
            <Select
              mode="tags"
              placeholder="输入标签后按回车"
              style={{ width: "100%" }}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
};

export default PhaseAnchorPanel;
