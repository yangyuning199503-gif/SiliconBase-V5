/**
 * 代理树视图组件
 * 
 * 展示SubAgent的父子关系树
 */
import React, { useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  Bot, 
  ChevronRight, 
  ChevronDown, 
  Play, 
  CheckCircle2, 
  XCircle, 
  PauseCircle,
  Clock,
  Layers
} from 'lucide-react'
import type { AgentNode, AgentTreeViewProps } from '../types/subagent'

// 获取状态图标
const getStatusIcon = (status: AgentNode['status']) => {
  switch (status) {
    case 'running':
      return <Play className="w-3.5 h-3.5 text-emerald-400" />
    case 'completed':
      return <CheckCircle2 className="w-3.5 h-3.5 text-blue-400" />
    case 'failed':
      return <XCircle className="w-3.5 h-3.5 text-red-400" />
    case 'cancelled':
      return <PauseCircle className="w-3.5 h-3.5 text-slate-400" />
    default:
      return <Clock className="w-3.5 h-3.5 text-slate-500" />
  }
}

// 获取状态颜色
const getStatusColor = (status: AgentNode['status']) => {
  switch (status) {
    case 'running':
      return 'border-emerald-500/50 bg-emerald-500/10'
    case 'completed':
      return 'border-blue-500/50 bg-blue-500/10'
    case 'failed':
      return 'border-red-500/50 bg-red-500/10'
    case 'cancelled':
      return 'border-slate-500/50 bg-slate-500/10'
    default:
      return 'border-slate-600/50 bg-slate-800/50'
  }
}

// 获取状态文本
const getStatusText = (status: AgentNode['status']) => {
  switch (status) {
    case 'running':
      return '运行中'
    case 'completed':
      return '已完成'
    case 'failed':
      return '失败'
    case 'cancelled':
      return '已取消'
    default:
      return '等待中'
  }
}

// 树节点组件
interface TreeNodeProps {
  node: AgentNode
  depth: number
  isLast: boolean
  expandedNodes: string[]
  selectedNode?: string
  onToggle: (runtimeId: string) => void
  onSelect: (node: AgentNode) => void
}

const TreeNode: React.FC<TreeNodeProps> = ({
  node,
  depth,
  isLast,
  expandedNodes,
  selectedNode,
  onToggle,
  onSelect
}) => {
  const isExpanded = expandedNodes.includes(node.runtime_id)
  const hasChildren = node.children && node.children.length > 0
  const isSelected = selectedNode === node.runtime_id

  const handleToggle = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    if (hasChildren) {
      onToggle(node.runtime_id)
    }
  }, [hasChildren, node.runtime_id, onToggle])

  const handleSelect = useCallback(() => {
    onSelect(node)
  }, [node, onSelect])

  // 缩进宽度
  const indentWidth = depth * 24

  return (
    <div className="tree-node">
      {/* 节点连接线 */}
      {depth > 0 && (
        <div 
          className={`absolute left-0 top-0 w-px bg-slate-700/50 ${isLast ? 'h-5' : 'bottom-0'}`}
          style={{ marginLeft: `${indentWidth - 12}px` }}
        />
      )}
      
      {/* 节点内容 */}
      <motion.div
        initial={{ opacity: 0, x: -10 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.2, delay: depth * 0.05 }}
        className={`
          relative flex items-center gap-2 p-2 rounded-lg cursor-pointer
          transition-all duration-200
          ${isSelected ? 'bg-cyan-500/20 border border-cyan-500/30' : 'hover:bg-slate-700/30'}
        `}
        style={{ marginLeft: `${indentWidth}px` }}
        onClick={handleSelect}
      >
        {/* 展开/折叠按钮 */}
        <button
          onClick={handleToggle}
          className={`
            w-5 h-5 flex items-center justify-center rounded
            transition-colors
            ${hasChildren ? 'hover:bg-slate-600/50' : 'invisible'}
          `}
        >
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-slate-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-400" />
          )}
        </button>

        {/* 状态图标 */}
        <div className={`
          w-8 h-8 rounded-lg flex items-center justify-center
          border ${getStatusColor(node.status)}
        `}>
          {getStatusIcon(node.status)}
        </div>

        {/* 代理信息 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-white font-medium text-sm truncate">
              {node.name}
            </span>
            <span className={`
              text-xs px-1.5 py-0.5 rounded
              ${node.status === 'running' ? 'bg-emerald-500/20 text-emerald-400' : ''}
              ${node.status === 'completed' ? 'bg-blue-500/20 text-blue-400' : ''}
              ${node.status === 'failed' ? 'bg-red-500/20 text-red-400' : ''}
              ${node.status === 'pending' ? 'bg-slate-500/20 text-slate-400' : ''}
            `}>
              {getStatusText(node.status)}
            </span>
          </div>
          
          {node.stage && (
            <p className="text-slate-500 text-xs mt-0.5">
              阶段: {node.stage}
            </p>
          )}
        </div>

        {/* 子代理数量 */}
        {hasChildren && (
          <div className="flex items-center gap-1 text-slate-500 text-xs">
            <Layers className="w-3 h-3" />
            <span>{node.children.length}</span>
          </div>
        )}
      </motion.div>

      {/* 子节点 */}
      <AnimatePresence>
        {isExpanded && hasChildren && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="relative"
          >
            {node.children.map((child, index) => (
              <TreeNode
                key={child.runtime_id}
                node={child}
                depth={depth + 1}
                isLast={index === node.children.length - 1}
                expandedNodes={expandedNodes}
                selectedNode={selectedNode}
                onToggle={onToggle}
                onSelect={onSelect}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// 主组件
export const AgentTreeView: React.FC<AgentTreeViewProps> = ({
  tree,
  onNodeClick,
  onNodeExpand,
  expandedNodes: controlledExpandedNodes,
  selectedNode,
  className = ''
}) => {
  const [internalExpandedNodes, setInternalExpandedNodes] = useState<string[]>([])
  const [internalSelectedNode, setInternalSelectedNode] = useState<string>()

  // 使用受控或非受控模式
  const expandedNodes = controlledExpandedNodes ?? internalExpandedNodes
  const currentSelectedNode = selectedNode ?? internalSelectedNode

  // 切换展开状态
  const handleToggle = useCallback((runtimeId: string) => {
    if (controlledExpandedNodes === undefined) {
      setInternalExpandedNodes(prev => 
        prev.includes(runtimeId)
          ? prev.filter(id => id !== runtimeId)
          : [...prev, runtimeId]
      )
    }
    onNodeExpand?.(tree.root.children.find(n => n.runtime_id === runtimeId) || tree.root)
  }, [controlledExpandedNodes, onNodeExpand, tree.root])

  // 选择节点
  const handleSelect = useCallback((node: AgentNode) => {
    if (selectedNode === undefined) {
      setInternalSelectedNode(node.runtime_id)
    }
    onNodeClick?.(node)
  }, [selectedNode, onNodeClick])

  // 展开全部
  const expandAll = useCallback(() => {
    const collectIds = (node: AgentNode): string[] => {
      const ids = [node.runtime_id]
      node.children?.forEach(child => {
        ids.push(...collectIds(child))
      })
      return ids
    }
    setInternalExpandedNodes(collectIds(tree.root))
  }, [tree.root])

  // 折叠全部
  const collapseAll = useCallback(() => {
    setInternalExpandedNodes([])
  }, [])

  return (
    <div className={`bg-slate-800/50 rounded-xl border border-white/10 ${className}`}>
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <Bot className="w-5 h-5 text-cyan-400" />
          <h3 className="text-white font-semibold">代理执行树</h3>
          <span className="text-slate-500 text-xs">
            ({tree.total_nodes} 个代理, 深度 {tree.max_depth})
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={expandAll}
            className="px-2 py-1 text-xs text-slate-400 hover:text-white hover:bg-slate-700/50 rounded transition-colors"
          >
            展开全部
          </button>
          <button
            onClick={collapseAll}
            className="px-2 py-1 text-xs text-slate-400 hover:text-white hover:bg-slate-700/50 rounded transition-colors"
          >
            折叠全部
          </button>
        </div>
      </div>

      {/* 树内容 */}
      <div className="p-4 max-h-[400px] overflow-y-auto">
        <TreeNode
          node={tree.root}
          depth={0}
          isLast={true}
          expandedNodes={expandedNodes}
          selectedNode={currentSelectedNode}
          onToggle={handleToggle}
          onSelect={handleSelect}
        />
      </div>

      {/* 底部统计 */}
      <div className="px-4 py-2 border-t border-white/10 flex items-center gap-4 text-xs">
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-emerald-400" />
          <span className="text-slate-400">运行中</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-blue-400" />
          <span className="text-slate-400">已完成</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-red-400" />
          <span className="text-slate-400">失败</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-slate-400" />
          <span className="text-slate-400">等待中</span>
        </div>
      </div>
    </div>
  )
}

export default AgentTreeView
