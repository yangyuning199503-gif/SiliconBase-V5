/**
 * 记忆可视化页面
 */
import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  Search,
  Trash2,
  Edit2,
  X,
  ChevronLeft,
  ChevronRight,
  Filter,
  Clock,
  Star,
  AlertCircle,
  CheckCircle,
  CheckSquare,
  Square,
  Sparkles,
  History,
  SlidersHorizontal,
  Target,
  Terminal,
  XCircle,
  Zap,
  BarChart3,
  Bot,
  User,
  RefreshCw,
  Cpu,
  Wrench,
  Plus,
} from "lucide-react";
import {
  memoryAPI,
  Memory,
  SearchResult,
  EvolutionRecord,
  ExecutionMemory,
  ExecutionStats,
} from "../utils/api/memory";
import { fetchAPI } from "../utils/api/index";

// 维度定义
const DIMENSIONS = [
  {
    key: "emotional_temperature",
    label: "情感温度",
    icon: "🤗",
    weight: "25%",
  },
  { key: "ethical_safety", label: "伦理安全", icon: "⚖️", weight: "20%" },
  { key: "self_growth", label: "自我成长", icon: "🌱", weight: "20%" },
  {
    key: "execution_effectiveness",
    label: "执行成效",
    icon: "✅",
    weight: "15%",
  },
  { key: "sustainability", label: "存续保障", icon: "🛡️", weight: "15%" },
  {
    key: "inspiration_innovation",
    label: "灵感创新",
    icon: "💫",
    weight: "5%",
  },
] as const;

// 等级定义
const GRADES = ["S", "A", "B", "C", "D"] as const;

// 维度筛选器组件
interface DimensionFilterProps {
  selectedDimensions: string[];
  minScores: Record<string, number>;
  onDimensionToggle: (dimension: string) => void;
  onMinScoreChange: (dimension: string, score: number) => void;
  onApply: () => void;
  onReset: () => void;
  isOpen: boolean;
  onClose: () => void;
}

const DimensionFilter: React.FC<DimensionFilterProps> = ({
  selectedDimensions,
  minScores,
  onDimensionToggle,
  onMinScoreChange,
  onApply,
  onReset,
  isOpen,
  onClose,
}) => {
  if (!isOpen) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="absolute top-full left-0 mt-2 w-80 bg-sb-bg-secondary border border-white/10 rounded-lg shadow-xl z-50 p-4"
    >
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-white flex items-center gap-2">
          <Target className="w-4 h-4 text-sb-cyan" />
          维度筛选
        </h3>
        <button
          onClick={onClose}
          className="p-1 hover:bg-white/10 rounded transition-colors"
        >
          <X className="w-4 h-4 text-sb-text-secondary" />
        </button>
      </div>

      <div className="space-y-3 max-h-80 overflow-auto">
        {DIMENSIONS.map((dim) => (
          <div
            key={dim.key}
            className={`p-3 rounded-lg border transition-all ${
              selectedDimensions.includes(dim.key)
                ? "bg-sb-cyan/5 border-sb-cyan/30"
                : "bg-white/5 border-white/5 hover:border-white/10"
            }`}
          >
            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={selectedDimensions.includes(dim.key)}
                onChange={() => onDimensionToggle(dim.key)}
                className="w-4 h-4 rounded border-white/20 bg-sb-bg-primary text-sb-cyan focus:ring-sb-cyan focus:ring-offset-0"
              />
              <span className="text-lg">{dim.icon}</span>
              <span className="text-sm text-white flex-1">{dim.label}</span>
              <span className="text-xs text-sb-text-secondary">
                {dim.weight}
              </span>
            </label>

            {selectedDimensions.includes(dim.key) && (
              <div className="mt-3 pl-7">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-sb-text-secondary">
                    最低分数
                  </span>
                  <span className="text-xs font-medium text-sb-cyan">
                    {minScores[dim.key] || 3}
                  </span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="5"
                  step="0.5"
                  value={minScores[dim.key] || 3}
                  onChange={(e) =>
                    onMinScoreChange(dim.key, parseFloat(e.target.value))
                  }
                  className="w-full h-1.5 bg-white/10 rounded-lg appearance-none cursor-pointer accent-sb-cyan"
                />
                <div className="flex justify-between mt-1 text-xs text-sb-text-secondary">
                  <span>1</span>
                  <span>5</span>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2 mt-4 pt-4 border-t border-white/10">
        <button
          onClick={onApply}
          className="flex-1 flex items-center justify-center gap-2 px-3 py-2 bg-sb-cyan text-sb-bg-primary rounded-lg text-sm font-medium hover:bg-sb-cyan-hover transition-colors"
        >
          <Filter className="w-4 h-4" />
          应用筛选
        </button>
        <button
          onClick={onReset}
          className="flex-1 px-3 py-2 border border-white/20 text-white rounded-lg text-sm hover:bg-white/5 transition-colors"
        >
          重置
        </button>
      </div>
    </motion.div>
  );
};

// 等级筛选组件
interface GradeFilterProps {
  selectedGrades: string[];
  onChange: (grades: string[]) => void;
}

const GradeFilter: React.FC<GradeFilterProps> = ({
  selectedGrades,
  onChange,
}) => {
  const toggleGrade = (grade: string) => {
    if (selectedGrades.includes(grade)) {
      onChange(selectedGrades.filter((g) => g !== grade));
    } else {
      onChange([...selectedGrades, grade]);
    }
  };

  const getGradeStyle = (grade: string) => {
    const baseStyles =
      "px-3 py-1.5 rounded-lg text-sm font-medium transition-all";
    const isSelected = selectedGrades.includes(grade);

    const gradeColors: Record<string, string> = {
      S: isSelected
        ? "bg-yellow-500 text-sb-bg-primary"
        : "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
      A: isSelected
        ? "bg-green-500 text-sb-bg-primary"
        : "bg-green-500/20 text-green-400 border border-green-500/30",
      B: isSelected
        ? "bg-blue-500 text-sb-bg-primary"
        : "bg-blue-500/20 text-blue-400 border border-blue-500/30",
      C: isSelected
        ? "bg-gray-500 text-white"
        : "bg-gray-500/20 text-gray-400 border border-gray-500/30",
      D: isSelected
        ? "bg-red-500 text-white"
        : "bg-red-500/20 text-red-400 border border-red-500/30",
    };

    return `${baseStyles} ${gradeColors[grade] || ""}`;
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-sb-text-secondary mr-1">等级:</span>
      {GRADES.map((grade) => (
        <button
          key={grade}
          onClick={() => toggleGrade(grade)}
          className={getGradeStyle(grade)}
        >
          {grade}
        </button>
      ))}
    </div>
  );
};

// 记忆详情/编辑面板
function MemoryDetailPanel({
  memory,
  onClose,
  onSave,
  onDelete,
}: {
  memory: Memory;
  onClose: () => void;
  onSave: (updates: { content?: string; rating?: number }) => void;
  onDelete: () => void;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState(
    typeof memory.content === "string"
      ? memory.content
      : memory.content?.text || JSON.stringify(memory.content),
  );
  const [editedRating, setEditedRating] = useState(memory.rating);

  const handleSave = () => {
    onSave({
      content: editedContent,
      rating: editedRating,
    });
    setIsEditing(false);
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: 300 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 300 }}
      className="fixed right-0 top-0 h-full w-96 bg-sb-bg-secondary border-l border-white/10 shadow-2xl z-50 overflow-auto"
    >
      <div className="p-6 space-y-6">
        {/* 头部 */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <div
              className={`w-3 h-3 rounded-full ${
                memory.layer === "short"
                  ? "bg-sb-cyan"
                  : memory.layer === "medium"
                    ? "bg-green-400"
                    : "bg-purple-400"
              }`}
            />
            <span className="text-xs text-sb-text-secondary uppercase">
              {memory.layer}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/10 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-sb-text-secondary" />
          </button>
        </div>

        {/* 内容 */}
        <div className="space-y-4">
          <div>
            <label className="text-xs text-sb-text-secondary block mb-2">
              内容
            </label>
            {isEditing ? (
              <textarea
                value={editedContent}
                onChange={(e) => setEditedContent(e.target.value)}
                rows={6}
                className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-4 py-2 text-white text-sm focus:border-sb-cyan outline-none resize-none"
              />
            ) : (
              <p className="text-white text-sm whitespace-pre-wrap">
                {typeof memory.content === "string"
                  ? memory.content
                  : JSON.stringify(memory.content)}
              </p>
            )}
          </div>

          {/* 价值评估评分 V2 - 有温度 */}
          <div>
            <label className="text-xs text-sb-text-secondary block mb-2">
              价值评估{" "}
              {memory.context?.value_assessment_v2 && "(V2.0 情感加权)"}
            </label>
            {isEditing ? (
              <div className="flex items-center gap-2">
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    onClick={() => setEditedRating(star)}
                    className={`text-lg ${star <= editedRating ? "text-yellow-400" : "text-white/20"}`}
                  >
                    ★
                  </button>
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                {/* 总分和等级 */}
                <div className="flex items-center gap-2">
                  <div className="flex items-center gap-1">
                    {[1, 2, 3, 4, 5].map((s) => (
                      <Star
                        key={s}
                        className={`w-4 h-4 ${s <= (memory.rating ?? 0) ? "text-yellow-400 fill-yellow-400" : "text-white/20"}`}
                      />
                    ))}
                  </div>
                  <span className="text-white font-bold">
                    {memory.rating ?? 0}/5
                  </span>
                  {memory.context?.value_assessment_v2?.overall_grade && (
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-bold ${
                        memory.context.value_assessment_v2.overall_grade === "S"
                          ? "bg-yellow-500/20 text-yellow-400"
                          : memory.context.value_assessment_v2.overall_grade ===
                              "A"
                            ? "bg-green-500/20 text-green-400"
                            : memory.context.value_assessment_v2
                                  .overall_grade === "B"
                              ? "bg-blue-500/20 text-blue-400"
                              : "bg-white/10 text-white/60"
                      }`}
                    >
                      {memory.context.value_assessment_v2.overall_grade}级
                    </span>
                  )}
                  {memory.context?.value_assessment_v2
                    ?.will_affect_behavior && (
                    <span className="text-xs text-sb-cyan">✨ 影响行为</span>
                  )}
                </div>

                {/* 详细维度评分 - V2 */}
                {memory.context?.value_assessment_v2?.dimension_scores && (
                  <div className="bg-white/5 rounded p-3 text-xs space-y-1.5">
                    <div className="text-sb-text-secondary mb-2 font-medium">
                      六维价值评估：
                    </div>
                    {Object.entries(
                      memory.context.value_assessment_v2.dimension_scores,
                    )
                      .sort((a, b) => b[1] - a[1]) // 按分数降序
                      .map(([dim, score]) => {
                        const weights: Record<string, string> = {
                          情感温度: "25% 🤗",
                          伦理安全: "20% ⚖️",
                          自我成长: "20% 🌱",
                          执行成效: "15% ✅",
                          存续保障: "15% 🛡️",
                          灵感创新: "5% 💫",
                        };
                        return (
                          <div
                            key={dim}
                            className="flex justify-between items-center"
                          >
                            <span className="text-white/80">
                              {dim}{" "}
                              <span className="text-white/40">
                                {weights[dim] || ""}
                              </span>
                            </span>
                            <div className="flex items-center gap-1">
                              <div className="w-16 h-1.5 bg-white/10 rounded-full overflow-hidden">
                                <div
                                  className={`h-full rounded-full ${
                                    score >= 4
                                      ? "bg-green-400"
                                      : score >= 3
                                        ? "bg-yellow-400"
                                        : "bg-red-400"
                                  }`}
                                  style={{ width: `${(score / 5) * 100}%` }}
                                />
                              </div>
                              <span
                                className={`w-6 text-right ${
                                  score >= 4
                                    ? "text-green-400"
                                    : score >= 3
                                      ? "text-yellow-400"
                                      : "text-red-400"
                                }`}
                              >
                                {score}
                              </span>
                            </div>
                          </div>
                        );
                      })}
                  </div>
                )}

                {/* 情感影响 */}
                {memory.context?.value_assessment_v2?.emotional_impact && (
                  <div className="bg-pink-500/10 rounded p-2 text-xs border border-pink-500/20">
                    <div className="text-pink-400 mb-1">💝 情感状态影响：</div>
                    <div className="grid grid-cols-2 gap-1 text-white/70">
                      {Object.entries(
                        memory.context.value_assessment_v2.emotional_impact,
                      ).map(([key, val]) => (
                        <div key={key}>
                          {key}:{" "}
                          {typeof val === "number"
                            ? val.toFixed(2)
                            : String(val ?? "")}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* 建议反思 */}
                {memory.context?.value_assessment_v2?.suggested_reflection && (
                  <div className="bg-sb-cyan/10 rounded p-2 text-xs border border-sb-cyan/30">
                    <div className="text-sb-cyan mb-1">💭 建议反思方向：</div>
                    <div className="text-white/80">
                      {memory.context.value_assessment_v2.suggested_reflection}
                    </div>
                  </div>
                )}

                {/* 成长收获 */}
                {(memory.context?.value_assessment_v2?.growth_insights
                  ?.length || 0) > 0 && (
                  <div className="bg-green-500/10 rounded p-2 text-xs border border-green-500/20">
                    <div className="text-green-400 mb-1">🌱 成长收获：</div>
                    {memory.context!.value_assessment_v2!.growth_insights!.map(
                      (insight, idx) => (
                        <div key={idx} className="text-white/80">
                          • {insight}
                        </div>
                      ),
                    )}
                  </div>
                )}

                {/* 伦理观察 */}
                {(memory.context?.value_assessment_v2?.ethical_notes?.length ||
                  0) > 0 && (
                  <div className="bg-blue-500/10 rounded p-2 text-xs border border-blue-500/20">
                    <div className="text-blue-400 mb-1">⚖️ 伦理观察：</div>
                    {memory.context!.value_assessment_v2!.ethical_notes!.map(
                      (note, idx) => (
                        <div key={idx} className="text-white/80">
                          • {note}
                        </div>
                      ),
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center gap-4 text-xs text-sb-text-secondary">
            <div className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {memory.created_at
                ? new Date(memory.created_at).toLocaleString()
                : "-"}
            </div>
            <div>ID: {memory.id?.slice(0, 8) ?? "unknown"}...</div>
          </div>
        </div>

        {/* 操作按钮 */}
        <div className="flex items-center gap-3 pt-4 border-t border-white/10">
          {isEditing ? (
            <>
              <button
                onClick={handleSave}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-sb-cyan text-sb-bg-primary rounded-lg hover:bg-sb-cyan-hover transition-colors"
              >
                <CheckCircle className="w-4 h-4" />
                保存
              </button>
              <button
                onClick={() => setIsEditing(false)}
                className="flex-1 px-4 py-2 border border-white/20 text-white rounded-lg hover:bg-white/5 transition-colors"
              >
                取消
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => setIsEditing(true)}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-white/10 text-white rounded-lg hover:bg-white/20 transition-colors"
              >
                <Edit2 className="w-4 h-4" />
                编辑
              </button>
              <button
                onClick={onDelete}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors"
              >
                <Trash2 className="w-4 h-4" />
                删除
              </button>
            </>
          )}
        </div>
      </div>
    </motion.div>
  );
}

export function MemoryPage() {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit] = useState(20);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [selectedMemory, setSelectedMemory] = useState<Memory | null>(null);
  const [filterLayer, setFilterLayer] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isBatchMode, setIsBatchMode] = useState(false);
  const [evolutions, setEvolutions] = useState<EvolutionRecord[]>([]);
  const [evolving, setEvolving] = useState(false);
  const [showEvolutionPanel, setShowEvolutionPanel] = useState(false);

  // L5 执行记忆状态
  const [executions, setExecutions] = useState<ExecutionMemory[]>([]);
  const [executionStats, setExecutionStats] = useState<ExecutionStats | null>(
    null,
  );
  const [showExecutionStats, setShowExecutionStats] = useState(false);

  // 添加记忆弹窗状态
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [addForm, setAddForm] = useState({
    content: "",
    scene: "",
    layer: "short",
    type: "internal_thought",
  });
  const [adding, setAdding] = useState(false);

  // 维度筛选状态
  const [dimensionFilter, setDimensionFilter] = useState({
    selectedDimensions: [] as string[],
    minScores: {} as Record<string, number>,
  });
  const [showDimensionFilter, setShowDimensionFilter] = useState(false);

  // 等级筛选状态
  const [selectedGrades, setSelectedGrades] = useState<string[]>([]);

  // 来源筛选状态 (新增：自动保存数据筛选)
  const [filterSource, setFilterSource] = useState<string | null>(null);

  // L4 向量记忆状态
  const [selectedCollection, setSelectedCollection] =
    useState<string>("experience");
  const [vectorQuery, setVectorQuery] = useState<string>("");
  const [vectorResults, setVectorResults] = useState<
    Array<{ content: string; similarity: number; memory_type: string }>
  >([]);
  const [vectorLoading, setVectorLoading] = useState<boolean>(false);

  const handleAddMemory = async () => {
    if (!addForm.content.trim()) {
      setError("记忆内容不能为空");
      return;
    }
    try {
      setAdding(true);
      setError(null);
      await memoryAPI.createMemory({
        content: addForm.content,
        layer: addForm.layer,
        mem_type: addForm.type,
        scene: addForm.scene,
        source: "user",
      });
      setSuccess("记忆添加成功");
      setShowAddDialog(false);
      setAddForm({
        content: "",
        scene: "",
        layer: "short",
        type: "internal_thought",
      });
      await loadMemories();
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      console.error("[MemoryPage] 添加记忆失败:", err);
      setError(err instanceof Error ? err.message : "添加记忆失败");
    } finally {
      setAdding(false);
    }
  };

  const loadMemories = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await memoryAPI.getMemories({
        limit,
        offset,
        layer: filterLayer || undefined,
        type: filterType || undefined,
      });
      setMemories(data?.memories || []);
      setTotal(data?.total || 0);
    } catch (err) {
      console.error("[MemoryPage] 加载记忆失败:", err);
      setError(err instanceof Error ? err.message : "加载记忆失败");
      setMemories([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [limit, offset, filterLayer, filterType, filterSource]);

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }
    try {
      const params: any = {};

      // 添加维度筛选参数
      if (dimensionFilter.selectedDimensions.length > 0) {
        params.dimension_weights = dimensionFilter.selectedDimensions.reduce(
          (acc, dim) => {
            acc[dim] = 2.0; // 选中维度权重加倍
            return acc;
          },
          {} as Record<string, number>,
        );

        params.min_dimension_scores = dimensionFilter.minScores;
      }

      // 添加等级筛选参数
      if (selectedGrades.length > 0) {
        params.grades = selectedGrades;
      }

      const data = await memoryAPI.searchMemories(searchQuery, params);
      setSearchResults(data?.results || []);
    } catch (err) {
      console.error("[MemoryPage] 搜索失败:", err);
      setSearchResults([]);
    }
  }, [searchQuery, dimensionFilter, selectedGrades]);

  // 应用维度筛选
  const applyDimensionFilter = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const params: any = {
        limit,
        offset: 0,
      };

      if (filterLayer) params.layer = filterLayer;
      if (filterType) params.type = filterType;

      // 添加维度筛选参数
      if (dimensionFilter.selectedDimensions.length > 0) {
        params.dimension_weights = dimensionFilter.selectedDimensions.reduce(
          (acc, dim) => {
            acc[dim] = 2.0; // 选中维度权重加倍
            return acc;
          },
          {} as Record<string, number>,
        );

        params.min_dimension_scores = dimensionFilter.minScores;
      }

      // 添加等级筛选参数
      if (selectedGrades.length > 0) {
        params.grades = selectedGrades;
      }

      const data = await memoryAPI.getMemories(params);
      setMemories(data?.memories || []);
      setTotal(data?.total || 0);
      setOffset(0);

      setSuccess("筛选已应用");
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      console.error("[MemoryPage] 应用筛选失败:", err);
      setError(err instanceof Error ? err.message : "应用筛选失败");
    } finally {
      setLoading(false);
      setShowDimensionFilter(false);
    }
  }, [limit, filterLayer, filterType, dimensionFilter, selectedGrades]);

  // 重置维度筛选
  const resetDimensionFilter = useCallback(() => {
    setDimensionFilter({
      selectedDimensions: [],
      minScores: {},
    });
    setSelectedGrades([]);
    setOffset(0);
    loadMemories();
    setShowDimensionFilter(false);
  }, [loadMemories]);

  // 切换维度选择
  const handleDimensionToggle = (dimension: string) => {
    setDimensionFilter((prev) => {
      const newSelected = prev.selectedDimensions.includes(dimension)
        ? prev.selectedDimensions.filter((d) => d !== dimension)
        : [...prev.selectedDimensions, dimension];

      // 如果取消选择，同时清除该维度的最低分数
      const newMinScores = { ...prev.minScores };
      if (!newSelected.includes(dimension)) {
        delete newMinScores[dimension];
      } else if (!newMinScores[dimension]) {
        newMinScores[dimension] = 3; // 默认最低分数
      }

      return {
        selectedDimensions: newSelected,
        minScores: newMinScores,
      };
    });
  };

  // 修改最低分数
  const handleMinScoreChange = (dimension: string, score: number) => {
    setDimensionFilter((prev) => ({
      ...prev,
      minScores: {
        ...prev.minScores,
        [dimension]: score,
      },
    }));
  };

  const handleDelete = async (memoryId: string) => {
    try {
      await memoryAPI.deleteMemory(memoryId);
      // 强制重新加载列表以同步总数和分页
      await loadMemories();
      setSelectedMemory(null);
      setSuccess("记忆已删除");
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      console.error("[MemoryPage] 删除记忆失败:", err, "memoryId:", memoryId);
      setError(err instanceof Error ? err.message : "删除失败");
    }
  };

  const handleUpdate = async (memoryId: string, updates: Partial<Memory>) => {
    try {
      const normalized: { content?: string; rating?: number } = {
        rating: updates.rating,
      };
      if (updates.content !== undefined) {
        normalized.content =
          typeof updates.content === "string"
            ? updates.content
            : updates.content?.text || JSON.stringify(updates.content);
      }
      await memoryAPI.updateMemory(memoryId, normalized);
      setMemories((prev) =>
        prev.map((m) => (m.id === memoryId ? { ...m, ...updates } : m)),
      );
      setSuccess("记忆已更新");
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      console.error("[MemoryPage] 更新记忆失败:", err, "memoryId:", memoryId);
      setError(err instanceof Error ? err.message : "更新失败");
    }
  };

  const toggleSelection = (memoryId: string) => {
    setSelectedIds((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(memoryId)) {
        newSet.delete(memoryId);
      } else {
        newSet.add(memoryId);
      }
      return newSet;
    });
  };

  const toggleSelectAll = () => {
    if (filterLayer === "execution") {
      // L5 执行轨迹全选
      if (selectedIds.size === executions.length) {
        setSelectedIds(new Set());
      } else {
        setSelectedIds(
          new Set(executions.map((e) => `${e.tool_name}-${e.timestamp}`)),
        );
      }
    } else {
      // 普通记忆全选
      if (selectedIds.size === memories.length) {
        setSelectedIds(new Set());
      } else {
        setSelectedIds(new Set(memories.map((m) => m.id)));
      }
    }
  };

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!confirm(`确定要删除选中的 ${selectedIds.size} 条记忆吗？`)) return;

    try {
      await memoryAPI.deleteBatch(Array.from(selectedIds));
      // 强制重新加载列表
      await loadMemories();
      setSuccess(`已删除 ${selectedIds.size} 条记忆`);
      setSelectedIds(new Set());
      setIsBatchMode(false);
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      console.error(
        "[MemoryPage] 批量删除记忆失败:",
        err,
        "selectedIds:",
        Array.from(selectedIds),
      );
      setError(err instanceof Error ? err.message : "批量删除失败");
    }
  };

  const cancelBatchMode = () => {
    setIsBatchMode(false);
    setSelectedIds(new Set());
  };

  // L5 批量删除处理
  const handleExecutionBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!confirm(`确定要删除选中的 ${selectedIds.size} 条执行记录吗？`)) return;

    try {
      const result = await memoryAPI.deleteExecutionsBatch(
        Array.from(selectedIds),
      );
      await loadExecutions();
      setSuccess(`已删除 ${result.deleted} 条执行记录`);
      setSelectedIds(new Set());
      setIsBatchMode(false);
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      console.error(
        "[MemoryPage] 批量删除执行记录失败:",
        err,
        "selectedIds:",
        Array.from(selectedIds),
      );
      setError(err instanceof Error ? err.message : "批量删除执行记录失败");
    }
  };

  const loadEvolutionHistory = useCallback(async () => {
    try {
      const data = await memoryAPI.getEvolutionHistory(10);
      setEvolutions(data?.evolutions || []);
    } catch (err) {
      console.error("[MemoryPage] 加载进化历史失败:", err);
    }
  }, []);

  // L5 执行记忆加载
  const loadExecutions = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await memoryAPI.getExecutions({
        limit,
        offset,
      });
      setExecutions(data?.executions || []);
      setTotal(data?.total || 0);
    } catch (err) {
      console.error("[MemoryPage] 加载执行轨迹失败:", err);
      setError(err instanceof Error ? err.message : "加载执行轨迹失败");
      setExecutions([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [limit, offset]);

  // L5 执行统计加载
  const loadExecutionStats = useCallback(async () => {
    try {
      const data = await memoryAPI.getExecutionStats(30);
      setExecutionStats(data?.stats || null);
    } catch (err) {
      console.error("[MemoryPage] 加载执行统计失败:", err);
    }
  }, []);

  // L4 向量记忆搜索
  const searchVector = useCallback(async () => {
    if (!vectorQuery.trim()) {
      setVectorResults([]);
      return;
    }
    try {
      setVectorLoading(true);
      setError(null);
      // 调用向量搜索API
      const data = await fetchAPI<{ results?: any[] }>(
        `/api/memory/vector/search?collection=${selectedCollection}&query=${encodeURIComponent(vectorQuery)}&top_k=10`,
      );
      setVectorResults(data?.results || []);
    } catch (err) {
      console.error("[MemoryPage] 向量搜索失败:", err);
      setError(err instanceof Error ? err.message : "向量搜索失败");
      setVectorResults([]);
    } finally {
      setVectorLoading(false);
    }
  }, [vectorQuery, selectedCollection]);

  // L4 向量集合切换时自动搜索
  useEffect(() => {
    if (filterLayer === "vector" && vectorQuery.trim()) {
      searchVector();
    }
  }, [selectedCollection, filterLayer]);

  const handleTriggerEvolution = async () => {
    try {
      setEvolving(true);
      const result = await memoryAPI.triggerEvolution();
      if (result.success) {
        setSuccess(
          `记忆进化完成！整理了${result.compressed_count || 0}条记忆，进化出${result.evolved_count || 0}条经验。`,
        );
        await loadEvolutionHistory();
      } else {
        setError(result.message || "记忆进化失败");
      }
    } catch (err) {
      console.error("[MemoryPage] 触发记忆进化失败:", err);
      setError(err instanceof Error ? err.message : "记忆进化失败");
    } finally {
      setEvolving(false);
      setTimeout(() => {
        setSuccess(null);
        setError(null);
      }, 5000);
    }
  };

  useEffect(() => {
    (async () => {
      try {
        if (filterLayer === "execution") {
          await loadExecutions();
          await loadExecutionStats();
        } else {
          await loadMemories();
        }
        await loadEvolutionHistory();
      } catch (err) {
        console.error("[MemoryPage] 初始化加载失败:", err);
      }
    })();
  }, [
    filterLayer,
    loadExecutions,
    loadExecutionStats,
    loadMemories,
    loadEvolutionHistory,
  ]);

  useEffect(() => {
    const timer = setTimeout(() => {
      (async () => {
        try {
          await handleSearch();
        } catch (err) {
          console.error("[MemoryPage] 搜索失败:", err);
        }
      })();
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, handleSearch]);

  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(offset / limit) + 1;

  // 检查是否有活跃的筛选
  const hasActiveFilters =
    dimensionFilter.selectedDimensions.length > 0 || selectedGrades.length > 0;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* 顶部工具栏 */}
      <div className="p-4 border-b border-white/5 space-y-4">
        {/* 标题和搜索 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Brain className="w-6 h-6 text-sb-cyan" />
            <h1 className="text-xl font-bold text-white">记忆管理</h1>
            <span className="text-sm text-sb-text-secondary">({total} 条)</span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowEvolutionPanel(!showEvolutionPanel)}
              className="flex items-center gap-1 px-3 py-1.5 text-sm text-purple-400 border border-purple-500/30 rounded-lg hover:bg-purple-500/10 transition-colors"
            >
              <History className="w-4 h-4" />
              进化历史
            </button>
            <button
              onClick={() => setShowAddDialog(true)}
              className="flex items-center gap-1 px-3 py-1.5 text-sm text-sb-cyan border border-sb-cyan/30 rounded-lg hover:bg-sb-cyan/10 transition-colors"
            >
              <Plus className="w-4 h-4" />
              添加记忆
            </button>
            {!isBatchMode ? (
              <button
                onClick={() => setIsBatchMode(true)}
                className="px-3 py-1.5 text-sm text-sb-text-secondary hover:text-white border border-white/10 rounded-lg hover:bg-white/5 transition-colors"
              >
                批量操作
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-sm text-sb-text-secondary">
                  已选 {selectedIds.size} 条
                </span>
                <button
                  onClick={toggleSelectAll}
                  className="px-3 py-1.5 text-sm text-sb-cyan border border-sb-cyan/30 rounded-lg hover:bg-sb-cyan/10 transition-colors"
                >
                  {filterLayer === "execution"
                    ? selectedIds.size === executions.length
                      ? "取消全选"
                      : "全选"
                    : selectedIds.size === memories.length
                      ? "取消全选"
                      : "全选"}
                </button>
                <button
                  onClick={
                    filterLayer === "execution"
                      ? handleExecutionBatchDelete
                      : handleBatchDelete
                  }
                  disabled={selectedIds.size === 0}
                  className="flex items-center gap-1 px-3 py-1.5 text-sm bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 disabled:opacity-50 transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                  删除
                </button>
                <button
                  onClick={cancelBatchMode}
                  className="px-3 py-1.5 text-sm text-sb-text-secondary hover:text-white transition-colors"
                >
                  取消
                </button>
              </div>
            )}
            <div className="relative w-64">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-sb-text-secondary" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                placeholder="搜索记忆..."
                className="w-full bg-sb-bg-secondary border border-white/10 rounded-lg pl-9 pr-4 py-2 text-sm text-white focus:border-sb-cyan outline-none"
              />
            </div>
          </div>
        </div>

        {/* 筛选器和操作按钮 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-sb-text-secondary" />
              <span className="text-sm text-sb-text-secondary">筛选:</span>
            </div>
            <select
              value={filterLayer || ""}
              onChange={(e) => setFilterLayer(e.target.value || null)}
              className="bg-sb-bg-secondary border border-white/10 rounded-lg px-3 py-1.5 text-sm text-white focus:border-sb-cyan outline-none"
            >
              <option value="">所有层级</option>
              <option value="short">L1 短期记忆</option>
              <option value="medium">L2 中期记忆 (经验/教训)</option>
              <option value="evolve">L3 进化记忆 (策略/优化)</option>
              <option value="vector">L4 向量记忆 (向量库)</option>
              <option value="execution">L5 执行轨迹</option>
            </select>
            <select
              value={filterType || ""}
              onChange={(e) => setFilterType(e.target.value || null)}
              className="bg-sb-bg-secondary border border-white/10 rounded-lg px-3 py-1.5 text-sm text-white focus:border-sb-cyan outline-none"
            >
              <option value="">所有类型</option>
              <option value="internal_thought">AI思考</option>
              <option value="thinking_flow">思维流</option>
              <option value="tool_execution">工具执行</option>
              <option value="experience">任务经验</option>
              <option value="user_preference">用户偏好</option>
              <option value="optimization">优化经验</option>
              <option value="pending_action">待办事项</option>
            </select>
            <select
              value={filterSource || ""}
              onChange={(e) => setFilterSource(e.target.value || null)}
              className="bg-sb-bg-secondary border border-white/10 rounded-lg px-3 py-1.5 text-sm text-white focus:border-sb-cyan outline-none"
            >
              <option value="">所有来源</option>
              <option value="user">🧑 用户手动</option>
              <option value="auto_save">🤖 系统自动</option>
              <option value="ai">🧠 AI自主</option>
              <option value="reflection">💭 反思产生</option>
              <option value="evolution">✨ 进化产生</option>
            </select>

            {/* 维度筛选按钮 */}
            <div className="relative">
              <button
                onClick={() => setShowDimensionFilter(!showDimensionFilter)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors ${
                  hasActiveFilters
                    ? "bg-sb-cyan/20 text-sb-cyan border border-sb-cyan/50"
                    : "bg-sb-bg-secondary border border-white/10 text-white hover:bg-white/5"
                }`}
              >
                <SlidersHorizontal className="w-4 h-4" />
                维度筛选
                {hasActiveFilters && (
                  <span className="px-1.5 py-0.5 bg-sb-cyan text-sb-bg-primary rounded text-xs font-bold">
                    {dimensionFilter.selectedDimensions.length +
                      selectedGrades.length}
                  </span>
                )}
              </button>

              <DimensionFilter
                selectedDimensions={dimensionFilter.selectedDimensions}
                minScores={dimensionFilter.minScores}
                onDimensionToggle={handleDimensionToggle}
                onMinScoreChange={handleMinScoreChange}
                onApply={applyDimensionFilter}
                onReset={resetDimensionFilter}
                isOpen={showDimensionFilter}
                onClose={() => setShowDimensionFilter(false)}
              />
            </div>

            {/* 等级筛选 */}
            <GradeFilter
              selectedGrades={selectedGrades}
              onChange={(grades) => {
                setSelectedGrades(grades);
                // 立即应用筛选
                setTimeout(() => applyDimensionFilter(), 0);
              }}
            />
          </div>

          {/* 整理记忆按钮 */}
          <button
            onClick={handleTriggerEvolution}
            disabled={evolving}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-purple-500 to-pink-500 text-white rounded-lg hover:from-purple-600 hover:to-pink-600 disabled:opacity-50 transition-all"
          >
            {evolving ? (
              <motion.div
                animate={{ rotate: 360 }}
                transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                className="w-4 h-4 border-2 border-white border-t-transparent rounded-full"
              />
            ) : (
              <Sparkles className="w-4 h-4" />
            )}
            {evolving ? "整理中..." : "整理记忆"}
          </button>
        </div>

        {/* 活跃的筛选标签 */}
        {hasActiveFilters && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="flex items-center gap-2 flex-wrap"
          >
            <span className="text-xs text-sb-text-secondary">已启用筛选:</span>
            {dimensionFilter.selectedDimensions.map((dimKey) => {
              const dim = DIMENSIONS.find((d) => d.key === dimKey);
              if (!dim) return null;
              return (
                <span
                  key={dimKey}
                  className="inline-flex items-center gap-1 px-2 py-1 bg-sb-cyan/10 border border-sb-cyan/30 rounded text-xs text-sb-cyan"
                >
                  {dim.icon} {dim.label} ≥{" "}
                  {dimensionFilter.minScores[dimKey] || 3}
                  <button
                    onClick={() => handleDimensionToggle(dimKey)}
                    className="hover:text-white ml-1"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              );
            })}
            {selectedGrades.map((grade) => (
              <span
                key={grade}
                className="inline-flex items-center gap-1 px-2 py-1 bg-sb-cyan/10 border border-sb-cyan/30 rounded text-xs text-sb-cyan"
              >
                {grade}级
                <button
                  onClick={() => {
                    setSelectedGrades((prev) =>
                      prev.filter((g) => g !== grade),
                    );
                    setTimeout(() => applyDimensionFilter(), 0);
                  }}
                  className="hover:text-white ml-1"
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
            <button
              onClick={resetDimensionFilter}
              className="text-xs text-sb-text-secondary hover:text-white underline"
            >
              清除全部
            </button>
          </motion.div>
        )}

        {/* 状态提示 */}
        {success && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-2 p-3 bg-green-500/10 border border-green-500/30 rounded-lg text-green-400 text-sm"
          >
            <CheckCircle className="w-4 h-4" />
            {success}
          </motion.div>
        )}
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-2 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm"
          >
            <AlertCircle className="w-4 h-4" />
            {error}
          </motion.div>
        )}

        {/* 进化历史面板 */}
        {showEvolutionPanel && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="border border-purple-500/20 rounded-lg bg-purple-500/5 p-4"
          >
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-purple-400 flex items-center gap-2">
                <Sparkles className="w-4 h-4" />
                记忆进化历史
              </h3>
              <button
                onClick={() => setShowEvolutionPanel(false)}
                className="text-sb-text-secondary hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            {evolutions.length === 0 ? (
              <p className="text-sm text-sb-text-secondary">暂无进化记录</p>
            ) : (
              <div className="space-y-2 max-h-48 overflow-auto">
                {evolutions.map((evo) => (
                  <div
                    key={evo.id}
                    className="flex items-center justify-between p-2 bg-sb-bg-secondary rounded text-sm"
                  >
                    <div className="flex items-center gap-3">
                      <Clock className="w-3 h-3 text-sb-text-secondary" />
                      <span className="text-white/80">
                        {evo.timestamp
                          ? new Date(evo.timestamp).toLocaleString()
                          : "-"}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 text-xs">
                      <span className="text-sb-text-secondary">
                        整理:{" "}
                        <span className="text-purple-400">
                          {evo.compressed_count}
                        </span>{" "}
                        条
                      </span>
                      <span className="text-sb-text-secondary">
                        进化:{" "}
                        <span className="text-pink-400">
                          {evo.evolved_count}
                        </span>{" "}
                        条
                      </span>
                      <span
                        className={`px-2 py-0.5 rounded ${
                          evo.status === "completed"
                            ? "bg-green-500/20 text-green-400"
                            : evo.status === "pending"
                              ? "bg-yellow-500/20 text-yellow-400"
                              : "bg-red-500/20 text-red-400"
                        }`}
                      >
                        {evo.status === "completed"
                          ? "完成"
                          : evo.status === "pending"
                            ? "处理中"
                            : "失败"}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </motion.div>
        )}

        {/* L4 向量记忆浏览视图 */}
        {filterLayer === "vector" && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="border border-blue-500/20 rounded-lg bg-blue-500/5 p-4"
          >
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-blue-400 flex items-center gap-2">
                <Brain className="w-4 h-4" />
                L4 向量记忆库
              </h3>
            </div>

            {/* 向量集合选择 */}
            <div className="flex gap-2 flex-wrap mb-4">
              {[
                "experience",
                "knowledge",
                "chat",
                "voice_fix",
                "execution",
              ].map((coll) => (
                <button
                  key={coll}
                  onClick={() => setSelectedCollection(coll)}
                  className={`px-3 py-1.5 rounded-lg text-sm transition-all ${
                    selectedCollection === coll
                      ? "bg-blue-600 text-white"
                      : "bg-sb-bg-secondary text-sb-text-secondary hover:bg-white/10"
                  }`}
                >
                  {coll}
                </button>
              ))}
            </div>

            {/* 语义搜索 */}
            <div className="flex gap-2 mb-4">
              <input
                type="text"
                value={vectorQuery}
                onChange={(e) => setVectorQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && searchVector()}
                placeholder="语义搜索向量记忆..."
                className="flex-1 px-3 py-2 bg-sb-bg-secondary border border-white/10 rounded-lg text-white text-sm focus:border-blue-500 outline-none"
              />
              <button
                onClick={searchVector}
                disabled={vectorLoading}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {vectorLoading ? (
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{
                      duration: 1,
                      repeat: Infinity,
                      ease: "linear",
                    }}
                    className="w-4 h-4 border-2 border-white border-t-transparent rounded-full"
                  />
                ) : (
                  "搜索"
                )}
              </button>
            </div>

            {/* 向量结果列表 */}
            <div className="space-y-2 max-h-64 overflow-auto">
              {vectorResults.length === 0 &&
                !vectorLoading &&
                vectorQuery.trim() && (
                  <p className="text-sm text-sb-text-secondary text-center py-4">
                    未找到匹配的向量记忆
                  </p>
                )}
              {vectorResults.length === 0 && !vectorQuery.trim() && (
                <p className="text-sm text-sb-text-secondary text-center py-4">
                  输入查询内容开始语义搜索
                </p>
              )}
              {vectorResults.map((item, idx) => (
                <motion.div
                  key={idx}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: idx * 0.05 }}
                  className="p-3 bg-sb-bg-secondary rounded-lg border border-white/5 hover:border-blue-500/30 transition-colors"
                >
                  <div className="text-gray-200 text-sm">
                    {typeof item.content === "string"
                      ? item.content
                      : JSON.stringify(item.content)}
                  </div>
                  <div className="text-xs text-sb-text-secondary mt-2 flex items-center gap-3">
                    <span>
                      相似度:{" "}
                      <span className="text-blue-400">
                        {(item.similarity * 100).toFixed(1)}%
                      </span>
                    </span>
                    <span>类型: {item.memory_type}</span>
                  </div>
                </motion.div>
              ))}
            </div>
          </motion.div>
        )}

        {/* L5 执行统计面板 */}
        {filterLayer === "execution" &&
          executionStats &&
          showExecutionStats && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="border border-orange-500/20 rounded-lg bg-orange-500/5 p-4"
            >
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-orange-400 flex items-center gap-2">
                  <BarChart3 className="w-4 h-4" />
                  L5 执行统计 (近{executionStats.period_days}天)
                </h3>
                <button
                  onClick={() => setShowExecutionStats(false)}
                  className="text-sb-text-secondary hover:text-white"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="grid grid-cols-4 gap-4 text-center">
                <div className="bg-sb-bg-secondary rounded p-3">
                  <div className="text-lg font-bold text-white">
                    {executionStats.total}
                  </div>
                  <div className="text-xs text-sb-text-secondary">
                    总执行次数
                  </div>
                </div>
                <div className="bg-sb-bg-secondary rounded p-3">
                  <div
                    className={`text-lg font-bold ${executionStats.success_rate >= 0.8 ? "text-green-400" : executionStats.success_rate >= 0.5 ? "text-yellow-400" : "text-red-400"}`}
                  >
                    {(executionStats.success_rate * 100).toFixed(1)}%
                  </div>
                  <div className="text-xs text-sb-text-secondary">成功率</div>
                </div>
                <div className="bg-sb-bg-secondary rounded p-3">
                  <div className="text-lg font-bold text-green-400">
                    {executionStats.success}
                  </div>
                  <div className="text-xs text-sb-text-secondary">成功</div>
                </div>
                <div className="bg-sb-bg-secondary rounded p-3">
                  <div className="text-lg font-bold text-red-400">
                    {executionStats.failed}
                  </div>
                  <div className="text-xs text-sb-text-secondary">失败</div>
                </div>
              </div>
              {executionStats.common_tools.length > 0 && (
                <div className="mt-3">
                  <div className="text-xs text-sb-text-secondary mb-2">
                    常用工具 TOP5:
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {executionStats.common_tools.slice(0, 5).map((tool) => (
                      <span
                        key={tool.tool_name}
                        className="px-2 py-1 bg-orange-500/10 text-orange-400 rounded text-xs"
                      >
                        {tool.tool_name} ({tool.count}次)
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </motion.div>
          )}
      </div>

      {/* 搜索结果或记忆列表 */}
      <div className="flex-1 overflow-auto p-4">
        {searchQuery && searchResults.length > 0 ? (
          <div className="space-y-3">
            <h3 className="text-sm text-sb-text-secondary mb-3">
              搜索结果: {searchResults.length} 条
            </h3>
            {searchResults.map((result, index) => (
              <motion.div
                key={index}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.05 }}
                className="bg-sb-bg-secondary/50 border border-white/5 rounded-lg p-4 hover:border-sb-cyan/30 transition-colors"
              >
                <p className="text-white text-sm">
                  {typeof result.content === "string"
                    ? result.content
                    : JSON.stringify(result.content)}
                </p>
                <div className="flex items-center gap-4 mt-2 text-xs text-sb-text-secondary">
                  <span>
                    相似度: {((1 - (result.distance ?? 0)) * 100).toFixed(1)}%
                  </span>
                  <span>类型: {result.metadata?.type || "unknown"}</span>
                </div>
              </motion.div>
            ))}
          </div>
        ) : searchQuery && searchResults.length === 0 && !loading ? (
          <div className="flex flex-col items-center justify-center h-full text-sb-text-secondary">
            <Search className="w-12 h-12 mb-3 opacity-30" />
            <p>未找到匹配的记忆</p>
            <p className="text-xs mt-1">尝试更换关键词或调整筛选条件</p>
          </div>
        ) : loading ? (
          <div className="flex items-center justify-center h-full">
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
              className="w-8 h-8 border-2 border-sb-cyan border-t-transparent rounded-full"
            />
          </div>
        ) : filterLayer === "execution" ? (
          // L5 执行轨迹列表
          <>
            {/* L5 统计切换按钮 */}
            {!showExecutionStats && executionStats && (
              <div className="flex justify-end mb-3">
                <button
                  onClick={() => setShowExecutionStats(true)}
                  className="flex items-center gap-1 px-3 py-1.5 text-sm text-orange-400 border border-orange-500/30 rounded-lg hover:bg-orange-500/10 transition-colors"
                >
                  <BarChart3 className="w-4 h-4" />
                  查看执行统计
                </button>
              </div>
            )}
            <div className="space-y-3">
              {executions.map((exec, index) => (
                <motion.div
                  key={`${exec.tool_name}-${exec.timestamp}-${index}`}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                  onClick={() =>
                    isBatchMode &&
                    toggleSelection(`${exec.tool_name}-${exec.timestamp}`)
                  }
                  className={`bg-sb-bg-secondary/50 border rounded-lg p-4 hover:border-orange-500/30 transition-all group ${
                    selectedIds.has(`${exec.tool_name}-${exec.timestamp}`)
                      ? "border-orange-500 bg-orange-500/5"
                      : "border-white/5"
                  } ${isBatchMode ? "cursor-pointer" : ""}`}
                >
                  <div className="flex items-start gap-3">
                    {isBatchMode && (
                      <div className="mt-0.5">
                        {selectedIds.has(
                          `${exec.tool_name}-${exec.timestamp}`,
                        ) ? (
                          <CheckSquare className="w-5 h-5 text-orange-500" />
                        ) : (
                          <Square className="w-5 h-5 text-white/30" />
                        )}
                      </div>
                    )}
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <div
                          className={`w-2 h-2 rounded-full ${exec.success ? "bg-green-400" : "bg-red-400"}`}
                        />
                        <Terminal className="w-4 h-4 text-orange-400" />
                        <span className="text-sm font-medium text-white">
                          {exec.tool_name}
                        </span>
                        {exec.success ? (
                          <span className="px-1.5 py-0.5 rounded text-xs bg-green-500/20 text-green-400 flex items-center gap-1">
                            <CheckCircle className="w-3 h-3" />
                            成功
                          </span>
                        ) : (
                          <span className="px-1.5 py-0.5 rounded text-xs bg-red-500/20 text-red-400 flex items-center gap-1">
                            <XCircle className="w-3 h-3" />
                            失败
                          </span>
                        )}
                      </div>
                      <div className="space-y-1">
                        <p className="text-sm text-white/80">
                          <span className="text-sb-text-secondary">输入:</span>{" "}
                          {JSON.stringify(exec.input_params).slice(0, 100)}
                          {JSON.stringify(exec.input_params).length > 100
                            ? "..."
                            : ""}
                        </p>
                        {exec.error_message && (
                          <p className="text-sm text-red-400">
                            <span className="text-sb-text-secondary">
                              错误:
                            </span>{" "}
                            {exec.error_message}
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      <div className="flex items-center gap-1 text-xs text-sb-text-secondary">
                        <Zap className="w-3 h-3" />
                        {exec.execution_time_ms}ms
                      </div>
                      <span className="text-xs text-sb-text-secondary">
                        {new Date(exec.timestamp).toLocaleString()}
                      </span>
                    </div>
                  </div>
                </motion.div>
              ))}
              {executions.length === 0 && !loading && (
                <div className="text-center py-12 text-sb-text-secondary">
                  <Terminal className="w-12 h-12 mx-auto mb-3 opacity-30" />
                  <p>暂无执行记录</p>
                  <p className="text-xs mt-1">
                    L5执行轨迹会记录所有工具调用历史
                  </p>
                </div>
              )}
            </div>
          </>
        ) : (
          <>
            <div className="space-y-3">
              {memories.map((memory, index) => (
                <motion.div
                  key={memory.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                  onClick={() =>
                    isBatchMode
                      ? toggleSelection(memory.id)
                      : setSelectedMemory(memory)
                  }
                  className={`bg-sb-bg-secondary/50 border rounded-lg p-4 hover:border-sb-cyan/30 cursor-pointer transition-all group ${
                    selectedIds.has(memory.id)
                      ? "border-sb-cyan bg-sb-cyan/5"
                      : "border-white/5"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    {isBatchMode && (
                      <div className="mt-0.5">
                        {selectedIds.has(memory.id) ? (
                          <CheckSquare className="w-5 h-5 text-sb-cyan" />
                        ) : (
                          <Square className="w-5 h-5 text-white/30" />
                        )}
                      </div>
                    )}
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <div
                          className={`w-2 h-2 rounded-full ${
                            memory.layer === "short"
                              ? "bg-sb-cyan"
                              : memory.layer === "medium"
                                ? "bg-green-400"
                                : "bg-purple-400"
                          }`}
                        />
                        <span className="text-xs text-sb-text-secondary uppercase">
                          {memory.layer}
                        </span>
                        <span className="text-xs text-sb-text-secondary">
                          ·
                        </span>
                        <span className="text-xs text-sb-text-secondary">
                          {memory.mem_type}
                        </span>
                        {/* 来源标识 */}
                        {memory.source === "auto_save" && (
                          <span
                            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-cyan-500/20 text-cyan-400 border border-cyan-500/30"
                            title="系统自动保存"
                          >
                            <Bot className="w-3 h-3" />
                            自动
                          </span>
                        )}
                        {memory.source === "user" && (
                          <span
                            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-green-500/20 text-green-400 border border-green-500/30"
                            title="用户手动保存"
                          >
                            <User className="w-3 h-3" />
                            手动
                          </span>
                        )}
                        {memory.source === "reflection" && (
                          <span
                            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-purple-500/20 text-purple-400 border border-purple-500/30"
                            title="反思系统产生"
                          >
                            <RefreshCw className="w-3 h-3" />
                            反思
                          </span>
                        )}
                        {memory.source === "evolution" && (
                          <span
                            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-pink-500/20 text-pink-400 border border-pink-500/30"
                            title="记忆进化产生"
                          >
                            <Sparkles className="w-3 h-3" />
                            进化
                          </span>
                        )}
                        {memory.source === "ai" && (
                          <span
                            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-blue-500/20 text-blue-400 border border-blue-500/30"
                            title="AI自主产生"
                          >
                            <Brain className="w-3 h-3" />
                            AI
                          </span>
                        )}
                        {/* 特殊类型标识 */}
                        {memory.mem_type === "thinking_flow" && (
                          <span
                            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-amber-500/20 text-amber-400 border border-amber-500/30"
                            title="AI思维流"
                          >
                            <Cpu className="w-3 h-3" />
                            思维流
                          </span>
                        )}
                        {memory.mem_type === "tool_execution" && (
                          <span
                            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-orange-500/20 text-orange-400 border border-orange-500/30"
                            title="工具调用记录"
                          >
                            <Wrench className="w-3 h-3" />
                            工具
                          </span>
                        )}
                        {memory.context?.value_assessment_v2?.overall_grade && (
                          <span
                            className={`px-1.5 py-0.5 rounded text-xs font-bold ${
                              memory.context.value_assessment_v2
                                .overall_grade === "S"
                                ? "bg-yellow-500/20 text-yellow-400"
                                : memory.context.value_assessment_v2
                                      .overall_grade === "A"
                                  ? "bg-green-500/20 text-green-400"
                                  : memory.context.value_assessment_v2
                                        .overall_grade === "B"
                                    ? "bg-blue-500/20 text-blue-400"
                                    : "bg-white/10 text-white/60"
                            }`}
                          >
                            {memory.context.value_assessment_v2.overall_grade}
                          </span>
                        )}
                      </div>
                      <p
                        className={`text-white text-sm line-clamp-2 transition-colors ${
                          !isBatchMode && "group-hover:text-sb-cyan"
                        }`}
                      >
                        {typeof memory.content === "string"
                          ? memory.content
                          : JSON.stringify(memory.content || "")}
                      </p>
                    </div>
                    <div className="flex items-center gap-1 ml-4">
                      <Star className="w-3 h-3 text-yellow-400" />
                      <span className="text-xs text-sb-text-secondary">
                        {memory.rating ?? 0}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-4 mt-2 text-xs text-sb-text-secondary pl-0">
                    {isBatchMode && <div className="w-5" />}
                    <span>
                      场景:{" "}
                      {typeof memory.scene === "string"
                        ? memory.scene
                        : JSON.stringify(memory.scene || "-")}
                    </span>
                    <span>
                      {memory.created_at
                        ? new Date(memory.created_at).toLocaleDateString()
                        : "-"}
                    </span>
                  </div>
                </motion.div>
              ))}
            </div>

            {/* 分页 */}
            {memories.length === 0 && !loading && !searchQuery && (
              <div className="flex flex-col items-center justify-center py-12 text-sb-text-secondary">
                <Brain className="w-12 h-12 mb-3 opacity-30" />
                <p>暂无记忆记录</p>
                <p className="text-xs mt-1">
                  与 AI 对话后，记忆系统会自动保存关键信息
                </p>
              </div>
            )}

            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-4 mt-6">
                <button
                  onClick={() => setOffset((prev) => Math.max(0, prev - limit))}
                  disabled={offset === 0}
                  className="p-2 text-sb-text-secondary hover:text-white disabled:opacity-30 transition-colors"
                >
                  <ChevronLeft className="w-5 h-5" />
                </button>
                <span className="text-sm text-sb-text-secondary">
                  {currentPage} / {totalPages}
                </span>
                <button
                  onClick={() => setOffset((prev) => prev + limit)}
                  disabled={currentPage >= totalPages}
                  className="p-2 text-sb-text-secondary hover:text-white disabled:opacity-30 transition-colors"
                >
                  <ChevronRight className="w-5 h-5" />
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* 记忆详情面板 - 仅在非L5模式下显示 */}
      <AnimatePresence>
        {selectedMemory && filterLayer !== "execution" && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setSelectedMemory(null)}
              className="fixed inset-0 bg-black/50 z-40"
            />
            <MemoryDetailPanel
              memory={selectedMemory}
              onClose={() => setSelectedMemory(null)}
              onSave={(updates) => handleUpdate(selectedMemory.id, updates)}
              onDelete={() => handleDelete(selectedMemory.id)}
            />
          </>
        )}
      </AnimatePresence>

      {/* 添加记忆弹窗 */}
      <AnimatePresence>
        {showAddDialog && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/50 z-50"
              onClick={() => setShowAddDialog(false)}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.15 }}
              className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none"
            >
              <div className="bg-sb-bg-secondary border border-white/10 rounded-xl p-6 w-full max-w-lg pointer-events-auto shadow-2xl">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-bold text-white">添加新记忆</h2>
                  <button
                    onClick={() => setShowAddDialog(false)}
                    className="text-sb-text-secondary hover:text-white transition-colors"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-sb-text-primary mb-1">
                      记忆内容 <span className="text-red-400">*</span>
                    </label>
                    <textarea
                      value={addForm.content}
                      onChange={(e) =>
                        setAddForm((prev) => ({
                          ...prev,
                          content: e.target.value,
                        }))
                      }
                      placeholder="输入记忆内容..."
                      rows={4}
                      className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:border-sb-cyan outline-none resize-none"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-sb-text-primary mb-1">
                      场景
                    </label>
                    <input
                      type="text"
                      value={addForm.scene}
                      onChange={(e) =>
                        setAddForm((prev) => ({
                          ...prev,
                          scene: e.target.value,
                        }))
                      }
                      placeholder="描述该记忆相关的场景或上下文"
                      className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:border-sb-cyan outline-none"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-sb-text-primary mb-1">
                        层级
                      </label>
                      <select
                        value={addForm.layer}
                        onChange={(e) =>
                          setAddForm((prev) => ({
                            ...prev,
                            layer: e.target.value,
                          }))
                        }
                        className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:border-sb-cyan outline-none appearance-none cursor-pointer"
                      >
                        <option value="short">L1 短期记忆</option>
                        <option value="medium">L2 中期记忆</option>
                        <option value="evolve">L3 进化记忆</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-sb-text-primary mb-1">
                        类型
                      </label>
                      <select
                        value={addForm.type}
                        onChange={(e) =>
                          setAddForm((prev) => ({
                            ...prev,
                            type: e.target.value,
                          }))
                        }
                        className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:border-sb-cyan outline-none appearance-none cursor-pointer"
                      >
                        <option value="internal_thought">AI思考</option>
                        <option value="thinking_flow">思维流</option>
                        <option value="tool_execution">工具执行</option>
                        <option value="experience">任务经验</option>
                        <option value="user_preference">用户偏好</option>
                        <option value="optimization">优化经验</option>
                        <option value="pending_action">待办事项</option>
                      </select>
                    </div>
                  </div>
                </div>
                <div className="flex justify-end gap-3 mt-6">
                  <button
                    onClick={() => setShowAddDialog(false)}
                    className="px-4 py-2 text-sm text-sb-text-secondary hover:text-white transition-colors"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleAddMemory}
                    disabled={adding || !addForm.content.trim()}
                    className="flex items-center gap-2 px-4 py-2 text-sm bg-sb-cyan text-sb-bg-primary rounded-lg hover:bg-sb-cyan-hover transition-colors disabled:opacity-50"
                  >
                    {adding ? (
                      <motion.div
                        animate={{ rotate: 360 }}
                        transition={{
                          duration: 1,
                          repeat: Infinity,
                          ease: "linear",
                        }}
                        className="w-4 h-4 border-2 border-sb-bg-primary border-t-transparent rounded-full"
                      />
                    ) : (
                      <Plus className="w-4 h-4" />
                    )}
                    {adding ? "保存中..." : "添加记忆"}
                  </button>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}
