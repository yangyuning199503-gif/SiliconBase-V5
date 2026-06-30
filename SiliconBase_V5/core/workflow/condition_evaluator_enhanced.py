#!/usr/bin/env python3
"""
ConditionEvaluator - 安全条件表达式评估器 V1.1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
使用 AST 安全地评估条件表达式，支持复杂逻辑操作

【核心特性】
1. 安全的 AST 解析（无代码注入风险）
2. 支持复杂表达式: a > 0 and b < 10 or c == "test"
3. 支持 JSONPath 变量引用: $step.items[0].value > 100
4. 自动回退到基础评估（功能降级兼容）

【架构位置】
- 位于: core/workflow/condition_evaluator_enhanced.py
- 调用方: WorkflowEngine._evaluate_condition()
- 依赖: VariableResolver（变量解析）

【使用示例】
```python
evaluator = ConditionEvaluator()
result = evaluator.evaluate("$step.score > 80 and $step.passed == true", variables, step_results)
```
"""

import ast
import contextlib
from dataclasses import dataclass
from typing import Any

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('condition_evaluator')

# Rust 硬壳层：安全条件求值（PoC）
_RUST_CONDITION_EVALUATOR = None
try:
    from siliconbase_core import evaluate_condition_py
    _RUST_CONDITION_EVALUATOR = evaluate_condition_py
except Exception:
    pass

with contextlib.suppress(ImportError):
    from .variable_resolver_with_fallback import resolve_variable

def resolve_variable_fallback(path: str, data: dict[str, Any]) -> Any:
    """兼容回退 - 基础变量解析（支持嵌套数组路径）"""
    if not path:
        return None

    # 移除 $ 前缀
    if path.startswith('$'):
        path = path[1:]

    # 检查是否包含数组访问语法
    if '[' in path:
        return _resolve_with_array(path, data)

    # 解析简单点号路径
    parts = path.split('.')
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
        if value is None:
            return None
    return value


def _resolve_with_array(path: str, data: dict[str, Any]) -> Any:
    """解析包含数组访问的路径（如 step1.items[0].value）"""

    # 将路径拆分为段
    # 示例: "step1.items[0].value" -> ["step1", "items[0]", "value"]
    segments = []
    i = 0
    while i < len(path):
        if path[i] == '.':
            i += 1
            continue
        if path[i] == '[':
            # 数组索引
            end = path.find(']', i)
            if end == -1:
                return None
            segments.append(path[i:end+1])
            i = end + 1
        else:
            # 普通字段名
            end = i
            while end < len(path) and path[end] not in '.[':
                end += 1
            segments.append(path[i:end])
            i = end

    # 逐级解析
    value = data
    for segment in segments:
        if segment.startswith('['):
            # 数组索引 [n]
            try:
                idx = int(segment[1:-1])
                if isinstance(value, list) and 0 <= idx < len(value):
                    value = value[idx]
                else:
                    return None
            except (ValueError, IndexError):
                return None
        else:
            # 字典键
            if isinstance(value, dict):
                value = value.get(segment)
            else:
                return None

        if value is None:
            return None

    return value


@dataclass
class Token:
    """表达式词法单元"""
    type: str  # 'var', 'op', 'str', 'num', 'bool', 'null', 'lparen', 'rparen'
    value: Any
    raw: str


class ExpressionLexer:
    """表达式词法分析器"""

    # 操作符（按长度降序排列，确保多字符操作符先匹配）
    OPERATORS = ['==', '!=', '<=', '>=', '<', '>', 'in', 'is', 'not']

    # 关键字
    KEYWORDS = {'true': True, 'false': False, 'null': None, 'none': None,
                'and': 'and', 'or': 'or', 'not': 'not', 'is': 'is', 'in': 'in'}

    def __init__(self, expression: str):
        self.expression = expression
        self.pos = 0
        self.tokens: list[Token] = []

    def tokenize(self) -> list[Token]:
        """将表达式转换为词法单元列表"""
        while self.pos < len(self.expression):
            self._skip_whitespace()
            if self.pos >= len(self.expression):
                break

            char = self.expression[self.pos]

            # 变量引用: $step.name 或 $step.items[0].value
            if char == '$':
                self._read_variable()
            # 括号
            elif char == '(':
                self.tokens.append(Token('lparen', '(', '('))
                self.pos += 1
            elif char == ')':
                self.tokens.append(Token('rparen', ')', ')'))
                self.pos += 1
            # 字符串: "..." 或 '...'
            elif char in '"\'':
                self._read_string()
            # 数字
            elif char.isdigit() or (char == '-' and self._peek().isdigit()):
                self._read_number()
            # 标识符或关键字
            elif char.isalpha() or char == '_':
                self._read_identifier()
            # 操作符
            else:
                self._read_operator()

        return self.tokens

    def _skip_whitespace(self):
        """跳过空白字符"""
        while self.pos < len(self.expression) and self.expression[self.pos].isspace():
            self.pos += 1

    def _peek(self, offset: int = 1) -> str:
        """预览下一个字符"""
        pos = self.pos + offset
        return self.expression[pos] if pos < len(self.expression) else ''

    def _read_variable(self):
        """读取变量引用: $step.name, $step.items[0].value"""
        start = self.pos
        self.pos += 1  # 跳过 $

        # 读取变量路径（支持字母、数字、下划线、点、方括号）
        while self.pos < len(self.expression):
            char = self.expression[self.pos]
            if char.isalnum() or char in '._[]':
                self.pos += 1
            else:
                break

        raw = self.expression[start:self.pos]
        self.tokens.append(Token('var', raw, raw))

    def _read_string(self):
        """读取字符串字面量"""
        quote = self.expression[self.pos]
        self.pos += 1
        start = self.pos

        while self.pos < len(self.expression) and self.expression[self.pos] != quote:
            if self.expression[self.pos] == '\\':
                self.pos += 2
            else:
                self.pos += 1

        value = self.expression[start:self.pos]
        raw = f"{quote}{value}{quote}"
        self.pos += 1  # 跳过结束引号
        self.tokens.append(Token('str', value, raw))

    def _read_number(self):
        """读取数字"""
        start = self.pos
        if self.expression[self.pos] == '-':
            self.pos += 1

        has_dot = False
        while self.pos < len(self.expression):
            char = self.expression[self.pos]
            if char.isdigit():
                self.pos += 1
            elif char == '.' and not has_dot:
                has_dot = True
                self.pos += 1
            else:
                break

        raw = self.expression[start:self.pos]
        value = float(raw) if has_dot else int(raw)
        self.tokens.append(Token('num', value, raw))

    def _read_identifier(self):
        """读取标识符或关键字"""
        start = self.pos
        while self.pos < len(self.expression):
            char = self.expression[self.pos]
            if char.isalnum() or char == '_':
                self.pos += 1
            else:
                break

        raw = self.expression[start:self.pos]
        raw_lower = raw.lower()

        if raw_lower in self.KEYWORDS:
            value = self.KEYWORDS[raw_lower]
            if raw_lower in ('and', 'or', 'not'):
                self.tokens.append(Token('op', value, raw))
            elif raw_lower in ('is', 'in'):
                self.tokens.append(Token('op', raw_lower, raw))
            else:
                self.tokens.append(Token('bool' if isinstance(value, bool) else 'null', value, raw))
        else:
            self.tokens.append(Token('ident', raw, raw))

    def _read_operator(self):
        """读取操作符"""
        remaining = self.expression[self.pos:]

        # 检查多字符操作符 (==, !=, <=, >=)
        for op in self.OPERATORS:
            if remaining.startswith(op):
                self.tokens.append(Token('op', op, op))
                self.pos += len(op)
                return

        # 未知字符，跳过
        self.pos += 1


class ConditionEvaluator:
    """
    安全条件表达式评估器

    支持语法:
    - 比较: ==, !=, <, >, <=, >=
    - 逻辑: and, or, not
    - 变量: $step.name, $step.items[0].value
    - 字面量: 字符串, 数字, true, false, null
    - 分组: (a and b) or c
    """

    def __init__(self):
        self._variables: dict[str, Any] = {}
        self._step_results: dict[str, Any] = {}
        self._var_values: dict[str, Any] = {}

    @staticmethod
    def evaluate(
        expression: str,
        variables: dict[str, Any],
        step_results: dict[str, Any]
    ) -> bool:
        """
        评估条件表达式（静态方法，便捷入口）

        Args:
            expression: 条件表达式字符串
            variables: 全局变量字典
            step_results: 步骤结果字典

        Returns:
            bool: 条件评估结果

        Examples:
            >>> ConditionEvaluator.evaluate("$step.score > 80", {}, {"step": {"score": 90}})
            True
            >>> ConditionEvaluator.evaluate("$step.a > 0 and $step.b < 10", {}, {"step": {"a": 5, "b": 5}})
            True
        """
        evaluator = ConditionEvaluator()
        evaluator._variables = variables
        evaluator._step_results = step_results
        return evaluator._evaluate(expression)

    def _evaluate(self, expression: str) -> bool:
        """内部评估方法"""
        if not expression or not expression.strip():
            return True  # 空条件视为满足

        expression = expression.strip()

        # 词法分析
        lexer = ExpressionLexer(expression)
        tokens = lexer.tokenize()

        if not tokens:
            return True

        # 预处理：将变量引用解析为实际值
        self._resolve_variables(tokens)

        # 构建可安全 eval 的表达式
        safe_expr = self._build_safe_expression(tokens)

        # 使用 AST 安全评估
        return self._safe_eval(safe_expr)

    def _resolve_variables(self, tokens: list[Token]):
        """将所有变量引用解析为实际值"""
        self._var_values = {}

        # 合并 variables 和 step_results 到一个数据源
        combined_data = {**self._variables, **self._step_results}

        for i, token in enumerate(tokens):
            if token.type == 'var':
                # 使用 VariableResolver 解析变量（优先使用导入的，否则使用回退）
                try:
                    value = resolve_variable(token.value, combined_data)
                except (NameError, TypeError):
                    value = resolve_variable_fallback(token.value, combined_data)
                var_name = f"_var_{i}_"
                self._var_values[var_name] = value
                token.resolved_name = var_name
                token.resolved_value = value

    def _build_safe_expression(self, tokens: list[Token]) -> str:
        """构建安全的 Python 表达式（用于 AST 评估）"""
        parts = []

        for token in tokens:
            if token.type == 'var':
                # 使用解析后的变量名
                parts.append(token.resolved_name)
            elif token.type == 'str':
                # 转义字符串
                escaped = token.value.replace('\\', '\\\\').replace("'", "\\'")
                parts.append(f"'{escaped}'")
            elif token.type == 'num' or token.type in ('bool', 'null'):
                parts.append(str(token.value))
            elif token.type == 'op':
                parts.append(token.value)
            elif token.type == 'lparen':
                parts.append('(')
            elif token.type == 'rparen':
                parts.append(')')
            elif token.type == 'ident':
                # 未识别的标识符，视为字符串
                parts.append(f"'{token.value}'")

        return ' '.join(parts)

    def _safe_eval(self, expression: str) -> bool:
        """安全评估表达式：优先使用 Rust 硬壳，失败回退到 Python AST。"""
        if not expression.strip():
            return True

        # 1. 尝试 Rust 硬壳层
        if _RUST_CONDITION_EVALUATOR is not None:
            try:
                result = _RUST_CONDITION_EVALUATOR(expression, self._var_values)
                logger.debug(f"[ConditionEvaluator] Rust 评估成功: {expression} => {result}")
                return bool(result)
            except Exception as rust_err:
                logger.debug(f"[ConditionEvaluator] Rust 评估失败，回退到 Python: {rust_err}")

        # 2. 回退：Python AST 安全评估
        try:
            tree = ast.parse(expression, mode='eval')
        except SyntaxError:
            logger.debug(f"[ConditionEvaluator] 语法错误: {expression}")
            return False

        # 只允许安全的节点类型
        allowed_nodes = (
            ast.Expression, ast.BoolOp, ast.Compare, ast.BinOp, ast.UnaryOp,
            ast.And, ast.Or, ast.Not,
            ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
            ast.Name, ast.Constant, ast.Load,
        )

        for node in ast.walk(tree):
            if not isinstance(node, allowed_nodes):
                logger.warning(f"[ConditionEvaluator] 不允许的节点类型: {type(node).__name__}")
                return False

        # 评估表达式
        try:
            result = eval(compile(tree, '<string>', 'eval'), {}, self._var_values)
            return bool(result)
        except Exception as e:
            logger.debug(f"[ConditionEvaluator] 评估失败: {e}")
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# 便捷函数接口（与 VariableResolver 风格一致）
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_condition(
    expression: str,
    variables: dict[str, Any],
    step_results: dict[str, Any]
) -> bool:
    """
    便捷函数：评估条件表达式

    Args:
        expression: 条件表达式
        variables: 全局变量
        step_results: 步骤结果

    Returns:
        bool: 评估结果
    """
    return ConditionEvaluator.evaluate(expression, variables, step_results)


# ═══════════════════════════════════════════════════════════════════════════════
# 测试代码
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    # 基础测试
    print("=" * 60)
    print("ConditionEvaluator Test")
    print("=" * 60)

    variables = {"env": "production"}
    step_results = {
        "step1": {
            "score": 85,
            "passed": True,
            "items": [{"name": "item1", "value": 100}]
        },
        "step2": {
            "count": 5,
            "threshold": 10
        }
    }

    test_cases = [
        ("$step1.score > 80", True),
        ("$step1.score > 90", False),
        ("$step1.score > 80 and $step1.passed == true", True),
        ("$step1.score < 80 or $step2.count < $step2.threshold", True),
        ("$step1.score > 90 or ($step2.count < $step2.threshold and $step1.passed)", True),
        ("not ($step1.score < 80)", True),
        ("$step1.items[0].value == 100", True),
        ("$step2.count >= 5 and $step2.count <= 10", True),
        ("$step1.score == 85", True),
        ("$step1.score != 90", True),
        ("$step1.score >= 85", True),
        ("$step1.score <= 85", True),
        ("$step2.count == 5", True),
        ("$step1.passed == true", True),
        ("$step1.passed != false", True),
    ]

    all_passed = True
    for expr, expected in test_cases:
        try:
            result = ConditionEvaluator.evaluate(expr, variables, step_results)
            status = "PASS" if result == expected else "FAIL"
            if result != expected:
                all_passed = False
            print(f"  [{status}] {expr:55s} => {result} (expected: {expected})")
        except Exception as e:
            all_passed = False
            print(f"  [ERR] {expr:55s} => error: {e}")

    print()
    if all_passed:
        print("All tests passed!")
        sys.exit(0)
    else:
        print("Some tests failed")
        sys.exit(1)
