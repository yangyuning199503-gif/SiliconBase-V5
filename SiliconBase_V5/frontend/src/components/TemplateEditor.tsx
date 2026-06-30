/**
 * 模板编辑器组件
 * SiliconBase V5 - 提示词模板内容编辑
 */
import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Edit2, Save, X, RotateCcw, CheckCircle } from 'lucide-react';

interface TemplateEditorProps {
  templateName: string;
  templateKey: string;
  initialContent: string;
  onSave: (key: string, content: string) => Promise<void>;
  variables?: string[];
}

export const TemplateEditor: React.FC<TemplateEditorProps> = React.memo(({
  templateName,
  templateKey,
  initialContent,
  onSave,
  variables = []
}) => {
  const [content, setContent] = useState(initialContent);
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    setContent(initialContent);
  }, [initialContent]);

  const handleSave = async () => {
    setIsSaving(true);
    setSaveSuccess(false);
    try {
      await onSave(templateKey, content);
      setIsEditing(false);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2000);
    } catch (error) {
      console.error('[TemplateEditor] 保存失败:', error);
      alert('保存失败: ' + (error instanceof Error ? error.message : String(error)));
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = () => {
    if (confirm('确定恢复默认内容？')) {
      setContent(initialContent);
    }
  };

  const handleCancel = () => {
    setContent(initialContent);
    setIsEditing(false);
  };

  return (
    <motion.div
      className="bg-sb-bg-secondary border border-white/10 rounded-xl p-4 mb-4"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <div className="flex justify-between items-center mb-3">
        <h4 className="text-lg font-semibold text-sb-text-primary">{templateName}</h4>
        <div className="flex gap-2">
          {!isEditing ? (
            <button
              onClick={() => setIsEditing(true)}
              className="flex items-center gap-1 px-3 py-1.5 bg-sb-cyan/20 text-sb-cyan rounded-lg hover:bg-sb-cyan/30 transition-colors text-sm"
            >
              <Edit2 className="w-4 h-4" />
              编辑内容
            </button>
          ) : (
            <>
              <button
                onClick={handleSave}
                disabled={isSaving || saveSuccess}
                className={`flex items-center gap-1 px-3 py-1.5 rounded-lg transition-colors text-sm disabled:opacity-50 ${
                  saveSuccess
                    ? 'bg-green-500/30 text-green-300'
                    : 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                }`}
              >
                {saveSuccess ? (
                  <>
                    <CheckCircle className="w-4 h-4" />
                    已保存
                  </>
                ) : (
                  <>
                    <Save className="w-4 h-4" />
                    {isSaving ? '保存中...' : '保存'}
                  </>
                )}
              </button>
              <button
                onClick={handleCancel}
                disabled={isSaving}
                className="flex items-center gap-1 px-3 py-1.5 bg-white/10 text-sb-text-secondary rounded-lg hover:bg-white/20 transition-colors text-sm disabled:opacity-50"
              >
                <X className="w-4 h-4" />
                取消
              </button>
              <button
                onClick={handleReset}
                disabled={isSaving}
                className="flex items-center gap-1 px-3 py-1.5 bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors text-sm disabled:opacity-50"
              >
                <RotateCcw className="w-4 h-4" />
                恢复默认
              </button>
            </>
          )}
        </div>
      </div>

      {/* 变量提示 */}
      {variables.length > 0 && (
        <div className="mb-3 text-sm text-sb-text-secondary">
          <span className="mr-2">可用变量:</span>
          {variables.map(v => (
            <code
              key={v}
              className="mx-1 px-2 py-0.5 bg-sb-cyan/10 text-sb-cyan rounded text-xs"
            >
              {v}
            </code>
          ))}
        </div>
      )}

      {/* 编辑器 */}
      {isEditing ? (
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          className="w-full h-64 p-3 bg-sb-bg-primary text-sb-text-primary font-mono text-sm rounded-lg border border-white/10 focus:border-sb-cyan focus:outline-none resize-none"
          placeholder="输入模板内容..."
          spellCheck={false}
        />
      ) : (
        <pre className="w-full h-64 p-3 bg-sb-bg-primary text-sb-text-secondary text-sm rounded-lg overflow-auto whitespace-pre-wrap font-mono">
          {content || (
            <span className="text-sb-text-secondary/50 italic">
              此模块暂无内容，点击&quot;编辑内容&quot;添加提示词...
            </span>
          )}
        </pre>
      )}
    </motion.div>
  );
});

export default TemplateEditor;
