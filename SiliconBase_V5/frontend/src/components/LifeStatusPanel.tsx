// frontend/src/components/LifeStatusPanel.tsx
/**
 * 零号机生命状态面板
 *
 * 【设计意图】
 * 这是内驱力与AI决策深度融合方案的前端可视化组件。
 * 它让用户能够实时看到零号机的"生命体征"——能量、好奇心、满足感、压力等，
 * 以及AI的"想法"（自发任务提案），让用户感受到零号机是一个"有生命"的存在。
 *
 * 【功能】
 * 1. 实时显示生命体征（能量、好奇心、满足感、压力）
 * 2. 显示当前心情和状态
 * 3. 展示AI的"想法"（任务提案），用户可以选择允许/稍后/拒绝
 * 4. 显示生命体征历史变化
 * 5. 通过WebSocket实时更新
 */

import React, { useEffect, useState, useCallback, useRef } from "react";
import {
  Card,
  Progress,
  Badge,
  Timeline,
  Statistic,
  Row,
  Col,
  Button,
  List,
  Tag,
  Tooltip,
  Empty,
  message,
  Avatar,
  Typography,
  Space,
  Switch,
} from "antd";
import {
  HeartOutlined,
  FireOutlined,
  SmileOutlined,
  ThunderboltOutlined,
  ExperimentOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  RobotOutlined,
  BulbOutlined,
  HistoryOutlined,
  PoweroffOutlined,
  EyeOutlined,
  RiseOutlined,
  CompassOutlined,
  TrophyOutlined,
  ThunderboltFilled,
} from "@ant-design/icons";

const { Text, Title } = Typography;

// 带认证的请求封装
function authFetch(url: string, options: RequestInit = {}) {
  const token = localStorage.getItem("silicon_token");
  return fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
}

// 生命体征接口
interface VitalSigns {
  energy: number;
  curiosity: number;
  satisfaction: number;
  stress: number;
  mood: string;
  is_hungry: boolean;
  is_tired: boolean;
  is_excited: boolean;
}

// 生命状态接口
interface LifeState {
  vitals: VitalSigns;
  activity_level: number;
  current_interval: number;
  pending_actions: number;
  timestamp: string;
}

// 成长摘要
interface GrowthSummary {
  level: number;
  level_name: string;
  total_xp: number;
  days_alive: number;
  memory_count: number;
  tool_usage_count: number;
}

// 动机状态
interface MotivationState {
  curiosity: number;
  mastery: number;
  autonomy: number;
  purpose: number;
}

// 意识生长统计
interface GrowthStats {
  motivation_state: MotivationState;
  ukf_state: {
    action_will: number;
    reflect_tendency: number;
    explore_tendency: number;
  } | null;
  training_samples_total: number;
  training_samples_memory: number;
  is_running: boolean;
  recent_thoughts: { content: string; mode: string; timestamp: string }[];
}

// 提案接口
interface Proposal {
  type: string;
  task_id: string;
  action_id: string;
  content: string;
  reason: string;
  emotional_tone: string;
  curiosity_level?: number;
  timestamp: number;
  responded: boolean;
}

// 组件属性
interface LifeStatusPanelProps {
  userId?: string;
  visible?: boolean;
  onClose?: () => void;
}

// 心情emoji映射
const MOOD_EMOJIS: Record<string, string> = {
  平静: "😌",
  好奇: "🤔",
  兴奋: "🤩",
  焦虑: "😰",
  愉悦: "😊",
  失落: "😔",
  疲惫: "😴",
  跃跃欲试: "🔥",
  精力充沛: "⚡",
  渴求: "🌟",
  困倦: "💤",
  紧张: "😬",
};

// 获取心情emoji
const getMoodEmoji = (mood: string): string => {
  return MOOD_EMOJIS[mood] || "😐";
};

// 获取心情颜色
const getMoodColor = (mood: string): string => {
  const colorMap: Record<string, string> = {
    平静: "#52c41a",
    好奇: "#722ed1",
    兴奋: "#f5222d",
    焦虑: "#faad14",
    愉悦: "#52c41a",
    失落: "#8c8c8c",
    疲惫: "#bfbfbf",
    跃跃欲试: "#fa541c",
    精力充沛: "#13c2c2",
    渴求: "#eb2f96",
  };
  return colorMap[mood] || "#8c8c8c";
};

export const LifeStatusPanel: React.FC<LifeStatusPanelProps> = ({
  userId = "default",
  visible = true,
  onClose,
}) => {
  // 状态
  const [lifeState, setLifeState] = useState<LifeState | null>(null);
  const [history, setHistory] = useState<VitalSigns[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [loading, setLoading] = useState(false);
  const [authError, setAuthError] = useState(false);

  // 新增：更多生命体征数据
  const [growthSummary, setGrowthSummary] = useState<GrowthSummary | null>(
    null,
  );
  const [growthStats, setGrowthStats] = useState<GrowthStats | null>(null);

  // 【紧急手术】训练与视觉发现总控开关状态
  const [trainingEnabled, setTrainingEnabled] = useState(false);
  const [visionDiscoveryEnabled, setVisionDiscoveryEnabled] = useState(false);
  const [switchLoading, setSwitchLoading] = useState({
    training: false,
    vision: false,
  });

  // WebSocket引用
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );

  // 连接WebSocket
  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const wsToken = localStorage.getItem("silicon_token");
      const wsUrl = `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/life-state?user_id=${userId}${wsToken ? `&token=${wsToken}` : ""}`;
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log("[LifeStatusPanel] WebSocket连接成功");
        setIsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          switch (data.type) {
            case "life_state_update":
              setLifeState(data.payload);
              setHistory((prev) => [...prev.slice(-49), data.payload.vitals]);
              break;

            case "silicon_life_proposal":
              // 新提案到来，添加到列表
              setProposals((prev) => {
                const exists = prev.some(
                  (p) => p.task_id === data.payload.task_id,
                );
                if (exists) return prev;
                return [
                  {
                    ...data.payload,
                    responded: false,
                  },
                  ...prev,
                ].slice(0, 10);
              });
              // 可选：显示通知
              message.info("💭 零号机有一个想法...", 3);
              break;

            case "proposal_response_confirmed":
              // 提案响应确认
              setProposals((prev) =>
                prev.map((p) =>
                  p.task_id === data.payload.task_id
                    ? { ...p, responded: true }
                    : p,
                ),
              );
              break;

            case "error":
              console.error("[LifeStatusPanel] WebSocket错误:", data.message);
              break;
          }
        } catch (error) {
          console.error("[LifeStatusPanel] 解析消息失败:", error);
        }
      };

      ws.onclose = () => {
        console.log("[LifeStatusPanel] WebSocket连接关闭");
        setIsConnected(false);
        // 自动重连
        reconnectTimeoutRef.current = setTimeout(connectWebSocket, 5000);
      };

      ws.onerror = (error) => {
        console.error("[LifeStatusPanel] WebSocket错误:", error);
        setIsConnected(false);
      };

      wsRef.current = ws;
    } catch (error) {
      console.error("[LifeStatusPanel] 连接WebSocket失败:", error);
    }
  }, [userId]);

  // 断开WebSocket
  const disconnectWebSocket = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  // 获取生命状态（HTTP备用）
  const fetchLifeState = useCallback(async () => {
    try {
      setLoading(true);
      setAuthError(false);
      const response = await authFetch(
        `/api/consciousness/status?user_id=${userId}`,
      );
      if (response.status === 401) {
        setAuthError(true);
        return;
      }
      if (response.ok) {
        const data = await response.json();
        setLifeState(data);
      }
    } catch (error) {
      console.error("[LifeStatusPanel] 获取生命状态失败:", error);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  // 获取成长摘要与意识统计
  const fetchGrowthData = useCallback(async () => {
    try {
      const [summaryRes, statsRes] = await Promise.all([
        authFetch("/api/life/summary"),
        authFetch("/api/consciousness/growth-stats"),
      ]);
      if (summaryRes.ok) {
        const json = await summaryRes.json();
        if (json.success) setGrowthSummary(json.data);
      }
      if (statsRes.ok) {
        const json = await statsRes.json();
        setGrowthStats(json);
      }
    } catch (error) {
      console.error("[LifeStatusPanel] 获取成长数据失败:", error);
    }
  }, []);

  // 响应提案（后端对应路由暂未实现，仅做前端提示）
  const respondToProposal = async (
    _taskId: string,
    response: "allow" | "later" | "reject",
  ) => {
    const messages: Record<string, string> = {
      allow: "已接受零号机的建议（待后端实现后同步）",
      later: "已暂存，稍后可以重新激活（待后端实现后同步）",
      reject: "已拒绝，零号机会记住您的偏好（待后端实现后同步）",
    };
    message.warning(messages[response]);
    // TODO: 后端实现 /api/consciousness/proposals/{taskId}/respond 后恢复实际调用
  };

  // 获取开关状态
  const fetchSwitchStates = useCallback(async () => {
    try {
      const [trainingStatus, visionStatus] = await Promise.all([
        authFetch("/api/consciousness/training/status").then((r) =>
          r.ok ? r.json() : { training_enabled: false },
        ),
        authFetch("/api/consciousness/vision-discovery/status").then((r) =>
          r.ok ? r.json() : { vision_discovery_enabled: false },
        ),
      ]);
      setTrainingEnabled(trainingStatus.training_enabled ?? false);
      setVisionDiscoveryEnabled(visionStatus.vision_discovery_enabled ?? false);
    } catch (error) {
      console.error("[LifeStatusPanel] 获取开关状态失败:", error);
    }
  }, []);

  // 切换训练开关
  const toggleTraining = async (checked: boolean) => {
    setSwitchLoading((prev) => ({ ...prev, training: true }));
    try {
      const endpoint = checked
        ? "/api/consciousness/training/start"
        : "/api/consciousness/training/stop";
      const res = await authFetch(endpoint, { method: "POST" });
      if (res.ok) {
        setTrainingEnabled(checked);
        message.success(checked ? "训练模式已开启" : "训练模式已关闭");
      } else {
        message.error("操作失败");
      }
    } catch (error) {
      message.error("网络错误");
    } finally {
      setSwitchLoading((prev) => ({ ...prev, training: false }));
    }
  };

  // 切换视觉发现开关
  const toggleVisionDiscovery = async (checked: boolean) => {
    setSwitchLoading((prev) => ({ ...prev, vision: true }));
    try {
      const endpoint = checked
        ? "/api/consciousness/vision-discovery/start"
        : "/api/consciousness/vision-discovery/stop";
      const res = await authFetch(endpoint, { method: "POST" });
      if (res.ok) {
        setVisionDiscoveryEnabled(checked);
        message.success(
          checked ? "视觉未知元素发现已开启" : "视觉未知元素发现已关闭",
        );
      } else {
        message.error("操作失败");
      }
    } catch (error) {
      message.error("网络错误");
    } finally {
      setSwitchLoading((prev) => ({ ...prev, vision: false }));
    }
  };

  // 初始化
  useEffect(() => {
    if (visible) {
      fetchLifeState();
      fetchGrowthData();
      fetchSwitchStates();
      connectWebSocket();

      // 定时刷新（WebSocket备用）
      const interval = setInterval(() => {
        fetchLifeState();
        fetchGrowthData();
      }, 10000);

      return () => {
        clearInterval(interval);
        disconnectWebSocket();
      };
    }
  }, [
    visible,
    userId,
    fetchLifeState,
    fetchGrowthData,
    fetchSwitchStates,
    connectWebSocket,
    disconnectWebSocket,
  ]);

  // 不可见时不渲染
  if (!visible) return null;

  // 加载中
  if (loading && !lifeState) {
    return (
      <Card
        style={{
          width: 400,
          background: "#1e1e2a",
          borderColor: "rgba(255,255,255,0.1)",
        }}
        loading={true}
      />
    );
  }

  // 认证失败
  if (authError) {
    return (
      <Card
        style={{
          width: 400,
          background: "#1e1e2a",
          borderColor: "rgba(255,255,255,0.1)",
        }}
      >
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <span style={{ color: "rgba(255,255,255,0.6)" }}>
              未登录或登录已过期，请重新登录后查看生命体征
            </span>
          }
        />
      </Card>
    );
  }

  const darkCardStyle: React.CSSProperties = {
    background: "#1e1e2a",
    borderColor: "rgba(255,255,255,0.1)",
  };
  const darkBodyStyle: React.CSSProperties = {
    padding: "16px",
    background: "transparent",
  };

  // 未加载到数据时显示占位（但保留深色主题）
  if (!lifeState) {
    return (
      <Card style={{ width: 400, ...darkCardStyle }} bodyStyle={darkBodyStyle}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <span style={{ color: "rgba(255,255,255,0.5)" }}>
              暂无生命状态数据
            </span>
          }
        />
      </Card>
    );
  }

  const vitals = lifeState!.vitals;

  // 获取状态标签
  const getStatusTags = () => {
    const tags = [];
    if (vitals.is_hungry) {
      tags.push(
        <Tooltip title="渴望交互和探索" key="hungry">
          <Tag color="orange">🍽️ 饥饿</Tag>
        </Tooltip>,
      );
    }
    if (vitals.is_tired) {
      tags.push(
        <Tooltip title="倾向于保守策略" key="tired">
          <Tag color="red">😴 疲倦</Tag>
        </Tooltip>,
      );
    }
    if (vitals.is_excited) {
      tags.push(
        <Tooltip title="学习能力和创造力提升" key="excited">
          <Tag color="green">🎉 兴奋</Tag>
        </Tooltip>,
      );
    }
    return tags;
  };

  // 获取提案类型标签
  const getProposalTypeTag = (type: string) => {
    const typeMap: Record<string, { text: string; color: string }> = {
      intuition_proposal: { text: "💡 直觉", color: "blue" },
      exploration_proposal: { text: "🔍 探索", color: "purple" },
    };
    const config = typeMap[type] || { text: "💭 想法", color: "default" };
    return <Tag color={config.color}>{config.text}</Tag>;
  };

  return (
    <Card
      title={
        <Space>
          <Avatar
            icon={<RobotOutlined />}
            style={{
              backgroundColor: getMoodColor(vitals.mood),
              transition: "background-color 0.5s ease",
            }}
          />
          <span style={{ color: "rgba(255,255,255,0.9)" }}>
            零号机的生命状态
          </span>
          <Badge
            status={isConnected ? "processing" : "default"}
            text={
              <span style={{ color: "rgba(255,255,255,0.6)" }}>
                {isConnected ? "实时连接" : "已断开"}
              </span>
            }
          />
        </Space>
      }
      extra={
        onClose && (
          <Button
            size="small"
            onClick={onClose}
            style={{
              background: "rgba(255,255,255,0.1)",
              color: "rgba(255,255,255,0.7)",
              borderColor: "rgba(255,255,255,0.2)",
            }}
          >
            收起
          </Button>
        )
      }
      style={{
        width: 420,
        maxHeight: 800,
        overflow: "auto",
        boxShadow: "0 4px 20px rgba(0,0,0,0.4)",
        ...darkCardStyle,
      }}
      bodyStyle={darkBodyStyle}
    >
      {/* 成长摘要迷你栏 */}
      {growthSummary && (
        <div
          style={{
            marginBottom: 12,
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 8,
          }}
        >
          <div
            style={{
              textAlign: "center",
              padding: "8px 4px",
              background: "rgba(255,255,255,0.04)",
              borderRadius: 8,
              border: "1px solid rgba(255,255,255,0.06)",
            }}
          >
            <TrophyOutlined style={{ color: "#f59e0b", fontSize: 14 }} />
            <div
              style={{
                fontSize: 13,
                fontWeight: "bold",
                color: "rgba(255,255,255,0.85)",
              }}
            >
              Lv.{growthSummary.level}
            </div>
            <div style={{ fontSize: 10, color: "rgba(255,255,255,0.4)" }}>
              {growthSummary.level_name}
            </div>
          </div>
          <div
            style={{
              textAlign: "center",
              padding: "8px 4px",
              background: "rgba(255,255,255,0.04)",
              borderRadius: 8,
              border: "1px solid rgba(255,255,255,0.06)",
            }}
          >
            <RiseOutlined style={{ color: "#34d399", fontSize: 14 }} />
            <div
              style={{
                fontSize: 13,
                fontWeight: "bold",
                color: "rgba(255,255,255,0.85)",
              }}
            >
              {growthSummary.total_xp}
            </div>
            <div style={{ fontSize: 10, color: "rgba(255,255,255,0.4)" }}>
              XP
            </div>
          </div>
          <div
            style={{
              textAlign: "center",
              padding: "8px 4px",
              background: "rgba(255,255,255,0.04)",
              borderRadius: 8,
              border: "1px solid rgba(255,255,255,0.06)",
            }}
          >
            <CompassOutlined style={{ color: "#60a5fa", fontSize: 14 }} />
            <div
              style={{
                fontSize: 13,
                fontWeight: "bold",
                color: "rgba(255,255,255,0.85)",
              }}
            >
              {growthSummary.days_alive}
            </div>
            <div style={{ fontSize: 10, color: "rgba(255,255,255,0.4)" }}>
              天
            </div>
          </div>
        </div>
      )}

      {/* 心情展示区域 */}
      <div
        style={{
          textAlign: "center",
          marginBottom: 16,
          padding: "20px 16px",
          background: `linear-gradient(135deg, ${getMoodColor(vitals.mood)}15, ${getMoodColor(vitals.mood)}05)`,
          borderRadius: 12,
          border: `1px solid ${getMoodColor(vitals.mood)}30`,
          transition: "all 0.5s ease",
        }}
      >
        <div
          style={{
            fontSize: 56,
            marginBottom: 8,
            animation: "pulse 2s infinite",
          }}
        >
          {getMoodEmoji(vitals.mood)}
        </div>
        <Title
          level={4}
          style={{ margin: 0, color: getMoodColor(vitals.mood) }}
        >
          {vitals.mood}
        </Title>
        <Space
          size="small"
          style={{ marginTop: 12, flexWrap: "wrap", justifyContent: "center" }}
        >
          {getStatusTags()}
        </Space>
      </div>

      {/* 总控开关面板 */}
      <div
        style={{
          marginBottom: 16,
          padding: 12,
          background: "rgba(255,255,255,0.04)",
          borderRadius: 8,
          border: "1px solid rgba(255,255,255,0.08)",
        }}
      >
        <Row gutter={[16, 16]}>
          <Col span={12}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <Space>
                <PoweroffOutlined
                  style={{ color: trainingEnabled ? "#52c41a" : "#ff4d4f" }}
                />
                <Text strong style={{ color: "rgba(255,255,255,0.85)" }}>
                  意识训练
                </Text>
              </Space>
              <Switch
                checked={trainingEnabled}
                onChange={toggleTraining}
                loading={switchLoading.training}
                checkedChildren="开"
                unCheckedChildren="关"
              />
            </div>
            <Text
              style={{
                fontSize: 11,
                marginTop: 4,
                display: "block",
                color: "rgba(255,255,255,0.45)",
              }}
            >
              {trainingEnabled
                ? "思考、走神、模型训练进行中"
                : "已关闭：不调用LLM，不训练"}
            </Text>
          </Col>
          <Col span={12}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <Space>
                <EyeOutlined
                  style={{
                    color: visionDiscoveryEnabled ? "#52c41a" : "#ff4d4f",
                  }}
                />
                <Text strong style={{ color: "rgba(255,255,255,0.85)" }}>
                  视觉发现
                </Text>
              </Space>
              <Switch
                checked={visionDiscoveryEnabled}
                onChange={toggleVisionDiscovery}
                loading={switchLoading.vision}
                checkedChildren="开"
                unCheckedChildren="关"
              />
            </div>
            <Text
              style={{
                fontSize: 11,
                marginTop: 4,
                display: "block",
                color: "rgba(255,255,255,0.45)",
              }}
            >
              {visionDiscoveryEnabled
                ? "自动标注未知UI元素"
                : "已关闭：不调用视觉模型"}
            </Text>
          </Col>
        </Row>
      </div>

      {/* 生命体征指标 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Statistic
            title={
              <Space>
                <ThunderboltOutlined
                  style={{ color: "rgba(255,255,255,0.5)" }}
                />{" "}
                <span style={{ color: "rgba(255,255,255,0.6)" }}>能量</span>
              </Space>
            }
            value={vitals.energy}
            suffix="/ 10"
            precision={1}
            valueStyle={{
              color:
                vitals.energy < 4
                  ? "#ff4d4f"
                  : vitals.energy > 7
                    ? "#52c41a"
                    : "#faad14",
              fontSize: 24,
            }}
          />
          <Progress
            percent={vitals.energy * 10}
            status={vitals.energy < 4 ? "exception" : "success"}
            showInfo={false}
            strokeColor={vitals.energy > 7 ? "#52c41a" : undefined}
            trailColor="rgba(255,255,255,0.08)"
          />
        </Col>
        <Col span={12}>
          <Statistic
            title={
              <Space>
                <ExperimentOutlined
                  style={{ color: "rgba(255,255,255,0.5)" }}
                />{" "}
                <span style={{ color: "rgba(255,255,255,0.6)" }}>好奇心</span>
              </Space>
            }
            value={vitals.curiosity}
            suffix="/ 10"
            precision={1}
            valueStyle={{
              color: vitals.curiosity > 7 ? "#722ed1" : "#1890ff",
              fontSize: 24,
            }}
          />
          <Progress
            percent={vitals.curiosity * 10}
            strokeColor="#722ed1"
            showInfo={false}
            trailColor="rgba(255,255,255,0.08)"
          />
        </Col>
        <Col span={12}>
          <Statistic
            title={
              <Space>
                <SmileOutlined style={{ color: "rgba(255,255,255,0.5)" }} />{" "}
                <span style={{ color: "rgba(255,255,255,0.6)" }}>满足感</span>
              </Space>
            }
            value={vitals.satisfaction}
            suffix="/ 10"
            precision={1}
            valueStyle={{ fontSize: 24, color: "rgba(255,255,255,0.85)" }}
          />
          <Progress
            percent={vitals.satisfaction * 10}
            strokeColor="#faad14"
            showInfo={false}
            trailColor="rgba(255,255,255,0.08)"
          />
        </Col>
        <Col span={12}>
          <Statistic
            title={
              <Space>
                <FireOutlined style={{ color: "rgba(255,255,255,0.5)" }} />{" "}
                <span style={{ color: "rgba(255,255,255,0.6)" }}>压力</span>
              </Space>
            }
            value={vitals.stress}
            suffix="/ 10"
            precision={1}
            valueStyle={{
              color: vitals.stress > 6 ? "#ff4d4f" : "rgba(255,255,255,0.6)",
              fontSize: 24,
            }}
          />
          <Progress
            percent={vitals.stress * 10}
            status={vitals.stress > 6 ? "exception" : "normal"}
            showInfo={false}
            trailColor="rgba(255,255,255,0.08)"
          />
        </Col>
      </Row>

      {/* 动机状态 */}
      {growthStats?.motivation_state && (
        <div
          style={{
            marginBottom: 16,
            padding: 12,
            background: "rgba(255,255,255,0.03)",
            borderRadius: 10,
            border: "1px solid rgba(255,255,255,0.06)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              marginBottom: 10,
            }}
          >
            <ThunderboltFilled style={{ color: "#f59e0b", fontSize: 14 }} />
            <span
              style={{
                fontSize: 13,
                fontWeight: "bold",
                color: "rgba(255,255,255,0.8)",
              }}
            >
              动机状态
            </span>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: "8px 12px",
            }}
          >
            {[
              {
                label: "好奇心",
                value: growthStats.motivation_state.curiosity,
                color: "#f59e0b",
              },
              {
                label: "胜任感",
                value: growthStats.motivation_state.mastery,
                color: "#10b981",
              },
              {
                label: "自主性",
                value: growthStats.motivation_state.autonomy,
                color: "#3b82f6",
              },
              {
                label: "目的感",
                value: growthStats.motivation_state.purpose,
                color: "#a855f7",
              },
            ].map((m) => (
              <div key={m.label}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 11,
                    marginBottom: 2,
                  }}
                >
                  <span style={{ color: "rgba(255,255,255,0.55)" }}>
                    {m.label}
                  </span>
                  <span style={{ color: m.color, fontWeight: "bold" }}>
                    {(m.value * 100).toFixed(0)}%
                  </span>
                </div>
                <div
                  style={{
                    width: "100%",
                    height: 4,
                    background: "rgba(255,255,255,0.08)",
                    borderRadius: 2,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      width: `${Math.min(m.value * 100, 100)}%`,
                      height: "100%",
                      background: m.color,
                      borderRadius: 2,
                      transition: "width 0.8s ease",
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* UKF 状态 */}
      {growthStats?.ukf_state && (
        <div
          style={{
            marginBottom: 16,
            padding: 12,
            background: "rgba(255,255,255,0.03)",
            borderRadius: 10,
            border: "1px solid rgba(255,255,255,0.06)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              marginBottom: 10,
            }}
          >
            <CompassOutlined style={{ color: "#60a5fa", fontSize: 14 }} />
            <span
              style={{
                fontSize: 13,
                fontWeight: "bold",
                color: "rgba(255,255,255,0.8)",
              }}
            >
              UKF 状态估计
            </span>
          </div>
          <div style={{ display: "flex", gap: 12 }}>
            {[
              {
                label: "行动意愿",
                value: growthStats.ukf_state.action_will,
                color: "#ef4444",
              },
              {
                label: "反思倾向",
                value: growthStats.ukf_state.reflect_tendency,
                color: "#3b82f6",
              },
              {
                label: "探索倾向",
                value: growthStats.ukf_state.explore_tendency,
                color: "#10b981",
              },
            ].map((u) => (
              <div key={u.label} style={{ flex: 1, textAlign: "center" }}>
                <div
                  style={{
                    fontSize: 11,
                    color: "rgba(255,255,255,0.5)",
                    marginBottom: 4,
                  }}
                >
                  {u.label}
                </div>
                <div
                  style={{ fontSize: 16, fontWeight: "bold", color: u.color }}
                >
                  {u.value.toFixed(2)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 训练数据 */}
      {growthStats && (
        <div
          style={{
            marginBottom: 16,
            padding: 12,
            background: "rgba(255,255,255,0.03)",
            borderRadius: 10,
            border: "1px solid rgba(255,255,255,0.06)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              marginBottom: 10,
            }}
          >
            <ExperimentOutlined style={{ color: "#34d399", fontSize: 14 }} />
            <span
              style={{
                fontSize: 13,
                fontWeight: "bold",
                color: "rgba(255,255,255,0.8)",
              }}
            >
              训练数据
            </span>
          </div>
          <div
            style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}
          >
            <div
              style={{
                textAlign: "center",
                padding: "8px 4px",
                background: "rgba(255,255,255,0.03)",
                borderRadius: 6,
              }}
            >
              <div
                style={{
                  fontSize: 16,
                  fontWeight: "bold",
                  color: "rgba(255,255,255,0.85)",
                }}
              >
                {growthStats.training_samples_total}
              </div>
              <div style={{ fontSize: 10, color: "rgba(255,255,255,0.4)" }}>
                磁盘样本
              </div>
            </div>
            <div
              style={{
                textAlign: "center",
                padding: "8px 4px",
                background: "rgba(255,255,255,0.03)",
                borderRadius: 6,
              }}
            >
              <div
                style={{
                  fontSize: 16,
                  fontWeight: "bold",
                  color: "rgba(255,255,255,0.85)",
                }}
              >
                {growthStats.training_samples_memory}
              </div>
              <div style={{ fontSize: 10, color: "rgba(255,255,255,0.4)" }}>
                内存样本
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 最近思考 */}
      {growthStats && growthStats.recent_thoughts.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Title
            level={5}
            style={{ marginBottom: 12, color: "rgba(255,255,255,0.85)" }}
          >
            <BulbOutlined style={{ color: "#a855f7" }} /> 最近思考
          </Title>
          <List
            size="small"
            dataSource={growthStats.recent_thoughts}
            renderItem={(item) => (
              <List.Item
                style={{
                  borderBottom: "1px solid rgba(255,255,255,0.06)",
                  padding: "8px 0",
                }}
              >
                <div>
                  <Tag color="purple" style={{ fontSize: 10, marginBottom: 4 }}>
                    {item.mode}
                  </Tag>
                  <div
                    style={{
                      fontSize: 12,
                      color: "rgba(255,255,255,0.7)",
                      lineHeight: 1.4,
                    }}
                  >
                    {item.content}
                  </div>
                </div>
              </List.Item>
            )}
          />
        </div>
      )}

      {/* AI的想法/提案区域 */}
      {proposals.filter((p) => !p.responded).length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Title
            level={5}
            style={{ marginBottom: 12, color: "rgba(255,255,255,0.85)" }}
          >
            <BulbOutlined style={{ color: "#faad14" }} /> 我的想法...
          </Title>
          <List
            size="small"
            bordered
            dataSource={proposals.filter((p) => !p.responded)}
            renderItem={(item) => (
              <List.Item
                style={{ padding: "12px" }}
                actions={[
                  <Tooltip title="允许执行（后端暂未实现）" key="allow">
                    <Button
                      size="small"
                      type="primary"
                      icon={<CheckCircleOutlined />}
                      disabled
                      onClick={() => respondToProposal(item.task_id, "allow")}
                      shape="circle"
                    />
                  </Tooltip>,
                  <Tooltip title="稍后处理（后端暂未实现）" key="later">
                    <Button
                      size="small"
                      icon={<ClockCircleOutlined />}
                      disabled
                      onClick={() => respondToProposal(item.task_id, "later")}
                      shape="circle"
                    />
                  </Tooltip>,
                  <Tooltip title="拒绝（后端暂未实现）" key="reject">
                    <Button
                      size="small"
                      danger
                      icon={<CloseCircleOutlined />}
                      disabled
                      onClick={() => respondToProposal(item.task_id, "reject")}
                      shape="circle"
                    />
                  </Tooltip>,
                ]}
              >
                <List.Item.Meta
                  avatar={getProposalTypeTag(item.type)}
                  title={<Text strong>{item.content}</Text>}
                  description={
                    <Tooltip title={item.reason}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {item.reason.length > 40
                          ? item.reason.slice(0, 40) + "..."
                          : item.reason}
                      </Text>
                    </Tooltip>
                  }
                />
              </List.Item>
            )}
          />
        </div>
      )}

      {/* 已处理的提案（折叠显示） */}
      {proposals.filter((p) => p.responded).length > 0 && (
        <details style={{ marginBottom: 16 }}>
          <summary
            style={{
              cursor: "pointer",
              color: "rgba(255,255,255,0.45)",
              fontSize: 12,
            }}
          >
            已处理的想法 ({proposals.filter((p) => p.responded).length})
          </summary>
          <List
            size="small"
            dataSource={proposals.filter((p) => p.responded)}
            renderItem={(item) => (
              <List.Item
                style={{
                  opacity: 0.5,
                  borderBottom: "1px solid rgba(255,255,255,0.06)",
                }}
              >
                <Text delete style={{ color: "rgba(255,255,255,0.4)" }}>
                  {item.content}
                </Text>
              </List.Item>
            )}
          />
        </details>
      )}

      {/* 生命体征历史 */}
      {history.length > 1 && (
        <div style={{ marginBottom: 16 }}>
          <Title
            level={5}
            style={{ marginBottom: 12, color: "rgba(255,255,255,0.85)" }}
          >
            <HistoryOutlined style={{ color: "rgba(255,255,255,0.5)" }} />{" "}
            最近状态
          </Title>
          <Timeline mode="left" style={{ marginTop: 8 }}>
            {history
              .slice(-5)
              .reverse()
              .map((record, index) => (
                <Timeline.Item key={index} color={getMoodColor(record.mood)}>
                  <Space direction="vertical" size={0}>
                    <Text strong style={{ color: getMoodColor(record.mood) }}>
                      {getMoodEmoji(record.mood)} {record.mood}
                    </Text>
                    <Text
                      style={{ fontSize: 12, color: "rgba(255,255,255,0.45)" }}
                    >
                      能量{record.energy.toFixed(1)} · 好奇
                      {record.curiosity.toFixed(1)} · 满足
                      {record.satisfaction.toFixed(1)}
                    </Text>
                  </Space>
                </Timeline.Item>
              ))}
          </Timeline>
        </div>
      )}

      {/* 底部信息栏 */}
      <div
        style={{
          marginTop: 16,
          padding: "10px 12px",
          background: "rgba(255,255,255,0.05)",
          borderRadius: 8,
          fontSize: 12,
          color: "rgba(255,255,255,0.45)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <Space size="small">
          <HeartOutlined style={{ color: "#ff4d4f" }} />
          <span>
            每 {lifeState!.current_interval.toFixed(0)} 秒感知一次世界
          </span>
        </Space>
        <Space size="small">
          <span>活动: {(lifeState!.activity_level * 100).toFixed(0)}%</span>
          {lifeState!.pending_actions > 0 && (
            <Badge count={lifeState!.pending_actions} size="small" />
          )}
        </Space>
      </div>
    </Card>
  );
};

export default LifeStatusPanel;
