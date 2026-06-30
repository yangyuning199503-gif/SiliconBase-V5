// frontend/src/pages/LifeStatusPage.tsx
/**
 * 生命体征页面
 *
 * 将 LifeStatusPanel 组件作为独立页面渲染，使用当前登录用户ID。
 */

import React from 'react';
import LifeStatusPanel from '@/components/LifeStatusPanel';
import { getCurrentUserId } from '@/utils/auth';

export const LifeStatusPage: React.FC = () => {
  const userId = getCurrentUserId() || 'default';
  return (
    <div className="min-h-screen bg-sb-darker p-4 md:p-6">
      <LifeStatusPanel userId={userId} visible onClose={() => {}} />
    </div>
  );
};

export default LifeStatusPage;
