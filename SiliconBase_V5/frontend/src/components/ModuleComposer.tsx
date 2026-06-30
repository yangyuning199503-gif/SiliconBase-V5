/**
 * 模块组合器组件
 * SiliconBase V5 - L1层模块组合配置
 */
import React from 'react';
import { motion } from 'framer-motion';
import { Check, Layers, Puzzle, Zap, ArrowUp, ArrowDown } from 'lucide-react';

export interface Module {
  id: string;
  name: string;
  description: string;
  category: 'core' | 'optional' | 'advanced';
}

interface ModuleComposerProps {
  availableModules: Module[];
  selectedModules: string[];
  onChange: (modules: string[]) => void;
}

export const ModuleComposer: React.FC<ModuleComposerProps> = React.memo(({
  availableModules,
  selectedModules,
  onChange
}) => {
  const categories: Record<Module['category'], { label: string; icon: React.ReactNode; color: string }> = {
    core: {
      label: '核心模块',
      icon: <Layers className="w-4 h-4" />,
      color: 'text-sb-cyan'
    },
    optional: {
      label: '可选模块',
      icon: <Puzzle className="w-4 h-4" />,
      color: 'text-yellow-400'
    },
    advanced: {
      label: '高级模块',
      icon: <Zap className="w-4 h-4" />,
      color: 'text-purple-400'
    }
  };

  const toggleModule = (moduleId: string) => {
    if (selectedModules.includes(moduleId)) {
      onChange(selectedModules.filter(m => m !== moduleId));
    } else {
      onChange([...selectedModules, moduleId]);
    }
  };

  const isSelected = (moduleId: string) => selectedModules.includes(moduleId);

  const moveModule = (index: number, direction: 'up' | 'down') => {
    const newModules = [...selectedModules];
    const targetIndex = direction === 'up' ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= newModules.length) return;
    [newModules[index], newModules[targetIndex]] = [newModules[targetIndex], newModules[index]];
    onChange(newModules);
  };

  return (
    <div className="module-composer">
      <div className="mb-6">
        <h3 className="text-xl font-bold text-sb-text-primary mb-2">L1层模块组合</h3>
        <p className="text-sm text-sb-text-secondary">
          选择要在L1基础提示词中包含的模块，系统将按顺序组合这些模块的内容
        </p>
      </div>

      {/* 已选模块计数 */}
      <div className="mb-6 p-3 bg-sb-cyan/10 border border-sb-cyan/20 rounded-lg">
        <div className="flex items-center justify-between">
          <span className="text-sm text-sb-text-secondary">已选择模块</span>
          <span className="text-lg font-semibold text-sb-cyan">
            {selectedModules.length} / {availableModules.length}
          </span>
        </div>
      </div>

      {/* 按分类显示模块 */}
      {(Object.keys(categories) as Module['category'][]).map(category => {
        const categoryModules = availableModules.filter(m => m.category === category);
        if (categoryModules.length === 0) return null;

        const { label, icon, color } = categories[category];

        return (
          <div key={category} className="mb-6">
            <div className="flex items-center gap-2 mb-3">
              <span className={color}>{icon}</span>
              <h4 className="text-lg font-semibold text-sb-text-primary">{label}</h4>
              <span className="text-xs text-sb-text-secondary ml-auto">
                {categoryModules.filter(m => isSelected(m.id)).length} / {categoryModules.length}
              </span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {categoryModules.map(module => (
                <motion.div
                  key={module.id}
                  className={`p-4 rounded-lg border cursor-pointer transition-all ${
                    isSelected(module.id)
                      ? 'bg-sb-cyan/10 border-sb-cyan'
                      : 'bg-sb-bg-secondary border-white/10 hover:border-white/20'
                  }`}
                  onClick={() => toggleModule(module.id)}
                  whileHover={{ scale: 1.01 }}
                  whileTap={{ scale: 0.99 }}
                >
                  <div className="flex items-start gap-3">
                    <div className={`mt-0.5 w-5 h-5 rounded border flex items-center justify-center transition-colors ${
                      isSelected(module.id)
                        ? 'bg-sb-cyan border-sb-cyan'
                        : 'border-white/30'
                    }`}>
                      {isSelected(module.id) && (
                        <Check className="w-3.5 h-3.5 text-black" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-sb-text-primary text-sm">
                        {module.name}
                      </div>
                      <div className="text-xs text-sb-text-secondary mt-1">
                        {module.description}
                      </div>
                    </div>
                  </div>
                </motion.div>
              ))}
            </div>
          </div>
        );
      })}

      {/* 组合预览 */}
      {selectedModules.length > 0 && (
        <div className="mt-6 p-4 bg-sb-bg-secondary border border-white/10 rounded-lg">
          <h4 className="text-sm font-semibold text-sb-text-primary mb-3">组合顺序预览</h4>
          <div className="space-y-2">
            {selectedModules.map((moduleId, index) => {
              const module = availableModules.find(m => m.id === moduleId);
              if (!module) return null;
              return (
                <div
                  key={moduleId}
                  className="flex items-center gap-3 text-sm"
                >
                  <span className="w-6 h-6 flex items-center justify-center bg-sb-cyan/20 text-sb-cyan rounded text-xs font-mono">
                    {index + 1}
                  </span>
                  <span className="text-sb-text-secondary flex-1">{module.name}</span>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => moveModule(index, 'up')}
                      disabled={index === 0}
                      className="p-1 rounded hover:bg-white/10 text-sb-text-secondary disabled:opacity-30 transition-colors"
                      title="上移"
                    >
                      <ArrowUp className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => moveModule(index, 'down')}
                      disabled={index === selectedModules.length - 1}
                      className="p-1 rounded hover:bg-white/10 text-sb-text-secondary disabled:opacity-30 transition-colors"
                      title="下移"
                    >
                      <ArrowDown className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <span className="text-xs text-sb-text-secondary/50">
                    {categories[module.category].label}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
});

export default ModuleComposer;
