import { useEffect, useState, useCallback, useRef } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';

interface Proposal {
  anchor_id: string;
  message: string;
  action_text: string;
  timestamp: number;
}

export const ProposalBubble = () => {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const { sendMessage, lastMessage } = useWebSocket();
  // 记录已经向后端上报过的 anchor_id，避免忽略/超时重复上报
  const reportedRef = useRef<Set<string>>(new Set());

  // 处理接收到的WebSocket消息
  useEffect(() => {
    if (!lastMessage) return;
    
    // 监听弱连接提议事件
    if (lastMessage.type === 'weak_proposal' && lastMessage.data) {
      const data = lastMessage.data
      if (!data.anchor_id || !data.message) {
        console.error('[SILENT_FAILURE_BLOCKED] weak_proposal消息缺少必要字段')
        return
      }
      const proposal: Proposal = {
        anchor_id: data.anchor_id as string,
        message: data.message as string,
        action_text: (data.action_text as string) || '帮我处理',
        timestamp: (data.timestamp as number) || Date.now()
      };
      
      setProposals(prev => [...prev, proposal]);
      
      // 30秒后自动移除，并向后端发送超时反馈
      setTimeout(() => {
        setProposals(prev => {
          const stillExists = prev.some(p => p.anchor_id === proposal.anchor_id);
          if (stillExists && !reportedRef.current.has(proposal.anchor_id)) {
            reportedRef.current.add(proposal.anchor_id);
            sendMessage({
              type: 'timeout_weak_proposal',
              anchor_id: proposal.anchor_id
            });
          }
          return prev.filter(p => p.anchor_id !== proposal.anchor_id);
        });
      }, 30000);
    }
    
    // 监听接受确认
    if (lastMessage.type === 'weak_proposal_accepted') {
      // 移除已接受的提议
      const anchorId = lastMessage.data?.anchor_id as string | undefined
      if (anchorId) {
        setProposals(prev => prev.filter(p => p.anchor_id !== anchorId));
      }
    }
  }, [lastMessage]);

  const handleAccept = useCallback((proposal: Proposal) => {
    // 通过WebSocket发送接受消息
    sendMessage({
      type: 'accept_weak_proposal',
      anchor_id: proposal.anchor_id,
      message: proposal.message
    });
    
    // 立即移除气泡（等待后端确认）
    setProposals(prev => prev.filter(p => p.anchor_id !== proposal.anchor_id));
  }, [sendMessage]);

  const handleDismiss = useCallback((anchor_id: string) => {
    // 用户主动忽略，向后端发送反馈
    if (!reportedRef.current.has(anchor_id)) {
      reportedRef.current.add(anchor_id);
      sendMessage({
        type: 'dismiss_weak_proposal',
        anchor_id: anchor_id
      });
    }
    setProposals(prev => prev.filter(p => p.anchor_id !== anchor_id));
  }, [sendMessage]);

  if (proposals.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 space-y-3">
      {proposals.map(proposal => (
        <div
          key={proposal.anchor_id}
          className="bg-gradient-to-r from-sb-cyan/90 to-sb-blue/90 
                     text-white p-4 rounded-xl shadow-2xl 
                     max-w-sm animate-in slide-in-from-right
                     border border-white/20 backdrop-blur-sm"
        >
          <div className="flex items-start gap-3">
            <div className="text-2xl">💡</div>
            <div className="flex-1">
              <p className="text-sm leading-relaxed">{proposal.message}</p>
              <div className="flex gap-2 mt-3">
                <button
                  onClick={() => handleAccept(proposal)}
                  className="px-4 py-1.5 bg-white/20 hover:bg-white/30 
                           rounded-lg text-sm font-medium transition-colors
                           border border-white/30"
                >
                  {proposal.action_text || '帮我处理'}
                </button>
                <button
                  onClick={() => handleDismiss(proposal.anchor_id)}
                  className="px-4 py-1.5 bg-white/10 hover:bg-white/20 
                           rounded-lg text-sm transition-colors"
                >
                  忽略
                </button>
              </div>
            </div>
          </div>
          
          {/* 进度条（30秒自动消失） */}
          <div className="mt-3 h-0.5 bg-white/20 rounded-full overflow-hidden">
            <div 
              className="h-full bg-white/50"
              style={{
                animation: 'shrink 30s linear forwards'
              }}
            />
          </div>
        </div>
      ))}
      
      <style>{`
        @keyframes shrink {
          from { width: 100%; }
          to { width: 0%; }
        }
      `}</style>
    </div>
  );
};
