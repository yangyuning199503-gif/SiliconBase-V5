/**
 * Week 5 面板集成页面
 * 
 * 展示新开发的三个面板：
 * 1. PhaseAnchorPanel - 阶段锚点面板
 * 2. ReflectionPanel - 反思系统面板
 * 3. TonePreferencePanel - 语气偏好设置面板
 */

import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { 
  Tabs, Typography, Space, Alert, Card, Row, Col,
  Input, message, Tag
} from 'antd';
import { 
  FlagOutlined, 
  BulbOutlined, 
  MessageOutlined,
  ExperimentOutlined,
  InfoCircleOutlined
} from '@ant-design/icons';

// 导入新开发的三个面板
import { PhaseAnchorPanel } from '../components/PhaseAnchorPanel';
import { ReflectionPanel } from '../components/ReflectionPanel';
import { TonePreferencePanel } from '../components/TonePreferencePanel';
import { getCurrentUserId } from '../utils/auth';

const { Title, Paragraph, Text } = Typography;
const { TabPane } = Tabs;

export const Week5PanelsPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState('phase-anchor');
  const [demoTaskId, setDemoTaskId] = useState('demo-task-001');
  const [demoSessionId, setDemoSessionId] = useState('demo-session-001');
  const currentUserId = getCurrentUserId() || 'default';

  // 处理阶段锚点选择
  const handleAnchorSelect = (anchor: any) => {
    message.info(`选择了锚点: ${anchor.phase}`);
    console.log('[Week5PanelsPage] 锚点选择:', anchor);
  };

  // 处理从锚点继续
  const handleContinueFromAnchor = (anchorId: string) => {
    message.success(`从锚点 ${anchorId} 继续执行`);
    console.log('[Week5PanelsPage] 从锚点继续:', anchorId);
  };

  // 处理语气偏好变化
  const handleToneChange = (config: any) => {
    console.log('[Week5PanelsPage] 语气偏好变化:', config);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="h-full overflow-auto p-6"
    >
      <div className="max-w-7xl mx-auto">
        {/* 页面标题 */}
        <div className="mb-6">
          <Space align="center" size="large">
            <ExperimentOutlined className="text-3xl text-sb-cyan" />
            <div>
              <Title level={2} className="!mb-0 !text-white">
                Week 5 新面板预览
              </Title>
              <Paragraph className="!mb-0 text-sb-text-secondary">
                体验新开发的三个功能面板：阶段锚点、反思系统、语气偏好
              </Paragraph>
            </div>
          </Space>
        </div>

        {/* 演示配置 */}
        <Card className="mb-6 bg-sb-bg-secondary/50 border-white/5">
          <Row gutter={[16, 16]} align="middle">
            <Col xs={24} md={12}>
              <Space direction="vertical" className="w-full">
                <Text strong className="text-white">演示任务ID：</Text>
                <Input
                  value={demoTaskId}
                  onChange={(e) => setDemoTaskId(e.target.value)}
                  placeholder="输入任务ID"
                  prefix={<FlagOutlined />}
                />
              </Space>
            </Col>
            <Col xs={24} md={12}>
              <Space direction="vertical" className="w-full">
                <Text strong className="text-white">演示会话ID：</Text>
                <Input
                  value={demoSessionId}
                  onChange={(e) => setDemoSessionId(e.target.value)}
                  placeholder="输入会话ID"
                  prefix={<MessageOutlined />}
                />
              </Space>
            </Col>
          </Row>
        </Card>

        {/* 信息提示 */}
        <Alert
          message="关于 Week 5 新面板"
          description={
            <Space direction="vertical">
              <Text>
                <FlagOutlined /> <strong>阶段锚点面板：</strong>用于在任务执行过程中设置检查点，支持从特定阶段回滚或继续执行。
              </Text>
              <Text>
                <BulbOutlined /> <strong>反思系统面板：</strong>展示AI的反思和学习记录，帮助AI从经验中持续改进。
              </Text>
              <Text>
                <MessageOutlined /> <strong>语气偏好面板：</strong>允许自定义AI的回复语气和风格，让交互更符合个人偏好。
              </Text>
            </Space>
          }
          type="info"
          showIcon
          className="mb-6"
        />

        {/* 面板展示区域 */}
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          type="card"
          className="week5-panels-tabs"
        >
          <TabPane
            tab={
              <Space>
                <FlagOutlined />
                <span>阶段锚点</span>
                <Tag color="blue">New</Tag>
              </Space>
            }
            key="phase-anchor"
          >
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={12}>
                <PhaseAnchorPanel
                  taskId={demoTaskId}
                  onAnchorSelect={handleAnchorSelect}
                  onContinueFromAnchor={handleContinueFromAnchor}
                />
              </Col>
              <Col xs={24} lg={12}>
                <Card title="使用说明" className="h-full">
                  <Space direction="vertical" className="w-full">
                    <Title level={4}>阶段锚点面板</Title>
                    <Paragraph>
                      阶段锚点用于在任务执行过程中标记关键状态点。当任务执行失败时，
                      可以从最近的锚点回滚，而不是从头开始。
                    </Paragraph>
                    <Title level={5}>主要功能：</Title>
                    <ul>
                      <li>创建任务执行的关键阶段标记</li>
                      <li>保存阶段状态数据（checkpoint）</li>
                      <li>从任意锚点继续执行</li>
                      <li>回滚到指定锚点</li>
                      <li>实时查看锚点状态</li>
                    </ul>
                    <Title level={5}>API 接口：</Title>
                    <ul>
                      <li><code>GET /api/tasks/&#123;taskId&#125;/anchors</code> - 获取锚点列表</li>
                      <li><code>POST /api/tasks/&#123;taskId&#125;/anchors</code> - 创建锚点</li>
                      <li><code>POST /api/tasks/&#123;taskId&#125;/continue</code> - 从锚点继续</li>
                      <li><code>POST /api/tasks/&#123;taskId&#125;/rollback</code> - 回滚到锚点</li>
                    </ul>
                  </Space>
                </Card>
              </Col>
            </Row>
          </TabPane>

          <TabPane
            tab={
              <Space>
                <BulbOutlined />
                <span>反思系统</span>
                <Tag color="gold">New</Tag>
              </Space>
            }
            key="reflection"
          >
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={12}>
                <ReflectionPanel
                  taskId={demoTaskId}
                  sessionId={demoSessionId}
                  showStats={true}
                />
              </Col>
              <Col xs={24} lg={12}>
                <Card title="使用说明" className="h-full">
                  <Space direction="vertical" className="w-full">
                    <Title level={4}>反思系统面板</Title>
                    <Paragraph>
                      反思系统记录AI在执行任务过程中的自我反思和学习。
                      这些反思帮助AI不断改进决策质量和执行效率。
                    </Paragraph>
                    <Title level={5}>反思类型：</Title>
                    <ul>
                      <li><Tag color="green">成功经验</Tag> - 记录有效的执行策略</li>
                      <li><Tag color="red">失败教训</Tag> - 分析错误原因</li>
                      <li><Tag color="blue">优化建议</Tag> - 提出改进方法</li>
                      <li><Tag color="orange">深度洞察</Tag> - 发现隐藏模式</li>
                    </ul>
                    <Title level={5}>主要功能：</Title>
                    <ul>
                      <li>启用/禁用反思系统</li>
                      <li>查看反思记录和置信度</li>
                      <li>对反思进行评分反馈</li>
                      <li>归档不再需要的反思</li>
                      <li>查看反思统计数据</li>
                    </ul>
                    <Title level={5}>API 接口：</Title>
                    <ul>
                      <li><code>GET /api/reflection/status</code> - 获取状态</li>
                      <li><code>GET /api/reflections</code> - 获取反思列表</li>
                      <li><code>POST /api/reflections/&#123;id&#125;/feedback</code> - 提交反馈</li>
                      <li><code>GET /api/reflections/stats</code> - 获取统计</li>
                    </ul>
                  </Space>
                </Card>
              </Col>
            </Row>
          </TabPane>

          <TabPane
            tab={
              <Space>
                <MessageOutlined />
                <span>语气偏好</span>
                <Tag color="purple">New</Tag>
              </Space>
            }
            key="tone-preference"
          >
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={12}>
                <TonePreferencePanel
                  userId={currentUserId}
                  showPreview={true}
                  onChange={handleToneChange}
                />
              </Col>
              <Col xs={24} lg={12}>
                <Card title="使用说明" className="h-full">
                  <Space direction="vertical" className="w-full">
                    <Title level={4}>语气偏好面板</Title>
                    <Paragraph>
                      允许用户自定义AI的回复语气和风格。
                      通过调整语气类型和各项参数，让AI回复更符合个人偏好。
                    </Paragraph>
                    <Title level={5}>语气类型：</Title>
                    <Space wrap>
                      <Tag color="#1890ff">正式</Tag>
                      <Tag color="#52c41a">随意</Tag>
                      <Tag color="#faad14">幽默</Tag>
                      <Tag color="#722ed1">专业</Tag>
                      <Tag color="#eb2f96">友善</Tag>
                      <Tag color="#13c2c2">简洁</Tag>
                      <Tag color="#2f54eb">详细</Tag>
                    </Space>
                    <Title level={5}>可调参数：</Title>
                    <ul>
                      <li><strong>正式程度</strong> - 控制回复的正式程度（0-100）</li>
                      <li><strong>热情程度</strong> - 控制回复的热情程度（0-100）</li>
                      <li><strong>同理心</strong> - 控制对用户情感的理解（0-100）</li>
                      <li><strong>专业程度</strong> - 控制使用专业术语的程度（0-100）</li>
                    </ul>
                    <Title level={5}>API 接口：</Title>
                    <ul>
                      <li><code>GET /api/users/&#123;userId&#125;/tone-preference</code> - 获取偏好</li>
                      <li><code>PUT /api/users/&#123;userId&#125;/tone-preference</code> - 更新偏好</li>
                      <li><code>GET /api/tone-presets</code> - 获取预设</li>
                      <li><code>POST /api/tone-preview</code> - 生成预览</li>
                    </ul>
                  </Space>
                </Card>
              </Col>
            </Row>
          </TabPane>

          <TabPane
            tab={
              <Space>
                <InfoCircleOutlined />
                <span>全部预览</span>
              </Space>
            }
            key="all"
          >
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={8}>
                <PhaseAnchorPanel
                  taskId={demoTaskId}
                  readOnly={true}
                />
              </Col>
              <Col xs={24} lg={8}>
                <ReflectionPanel
                  taskId={demoTaskId}
                  sessionId={demoSessionId}
                  showStats={false}
                />
              </Col>
              <Col xs={24} lg={8}>
                <TonePreferencePanel
                  userId={currentUserId}
                  showPreview={false}
                />
              </Col>
            </Row>
          </TabPane>
        </Tabs>

        {/* 底部说明 */}
        <Card className="mt-6 bg-sb-bg-secondary/30 border-white/5">
          <Space direction="vertical">
            <Text type="secondary">
              <InfoCircleOutlined /> <strong>开发说明：</strong>
              这三个面板是 Week 5 的核心交付物，它们增强了任务执行的可控性、
              AI的自我学习能力以及个性化的交互体验。
            </Text>
            <Text type="secondary">
              <strong>相关文件：</strong>
            </Text>
            <ul className="text-sb-text-secondary text-sm">
              <li>组件：src/components/PhaseAnchorPanel.tsx, ReflectionPanel.tsx, TonePreferencePanel.tsx</li>
              <li>API：src/utils/api/phaseAnchor.ts, reflection.ts, tonePreference.ts</li>
              <li>页面：src/pages/Week5PanelsPage.tsx</li>
              <li>测试：src/__tests__/components/PhaseAnchorPanel.test.tsx, ReflectionPanel.test.tsx, TonePreferencePanel.test.tsx</li>
            </ul>
          </Space>
        </Card>
      </div>
    </motion.div>
  );
};

export default Week5PanelsPage;
