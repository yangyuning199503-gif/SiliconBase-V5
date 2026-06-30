use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::HashMap;

/// Rust 端条件求值器。
///
/// 输入表达式应为已做变量替换后的"安全表达式"：只包含字面量、比较运算符、
/// 算术运算符、逻辑运算符 and/or/not 和括号。
///
/// 设计目标：替代 Python 中 `eval(compile(...))` 的代码注入风险点。

#[derive(Debug, Clone, PartialEq)]
enum Value {
    Null,
    Bool(bool),
    Number(f64),
    String(String),
}

impl Value {
    fn is_truthy(&self) -> bool {
        match self {
            Value::Null => false,
            Value::Bool(b) => *b,
            Value::Number(n) => *n != 0.0,
            Value::String(s) => !s.is_empty(),
        }
    }

    fn as_number(&self) -> Option<f64> {
        match self {
            Value::Number(n) => Some(*n),
            _ => None,
        }
    }

    fn as_string(&self) -> String {
        match self {
            Value::Null => "None".to_string(),
            Value::Bool(b) => b.to_string(),
            Value::Number(n) => n.to_string(),
            Value::String(s) => s.clone(),
        }
    }
}

fn pyobject_to_value(obj: &Bound<'_, PyAny>) -> PyResult<Value> {
    if obj.is_none() {
        return Ok(Value::Null);
    }
    if let Ok(b) = obj.extract::<bool>() {
        // bool 在 PyO3 中也能被提取为 int，必须先试 bool
        return Ok(Value::Bool(b));
    }
    if let Ok(n) = obj.extract::<i64>() {
        return Ok(Value::Number(n as f64));
    }
    if let Ok(n) = obj.extract::<f64>() {
        return Ok(Value::Number(n));
    }
    if let Ok(s) = obj.extract::<String>() {
        return Ok(Value::String(s));
    }
    // 其他类型退化为字符串表示
    Ok(Value::String(obj.to_string()))
}

#[derive(Debug, Clone, PartialEq)]
enum Token {
    Number(f64),
    String(String),
    Bool(bool),
    Null,
    Ident(String),
    Op(String),
    LParen,
    RParen,
    And,
    Or,
    Not,
}

fn tokenize(expr: &str) -> Result<Vec<Token>, String> {
    let mut tokens = Vec::new();
    let chars: Vec<char> = expr.chars().collect();
    let mut i = 0;

    while i < chars.len() {
        let c = chars[i];
        if c.is_whitespace() {
            i += 1;
            continue;
        }

        if c == '(' {
            tokens.push(Token::LParen);
            i += 1;
            continue;
        }
        if c == ')' {
            tokens.push(Token::RParen);
            i += 1;
            continue;
        }

        // 字符串字面量（单引号）
        if c == '\'' || c == '"' {
            let quote = c;
            i += 1;
            let mut s = String::new();
            while i < chars.len() {
                let ch = chars[i];
                if ch == '\\' && i + 1 < chars.len() {
                    let next = chars[i + 1];
                    match next {
                        'n' => s.push('\n'),
                        't' => s.push('\t'),
                        'r' => s.push('\r'),
                        '\\' => s.push('\\'),
                        '\'' => s.push('\''),
                        '"' => s.push('"'),
                        _ => s.push(next),
                    }
                    i += 2;
                    continue;
                }
                if ch == quote {
                    i += 1;
                    break;
                }
                s.push(ch);
                i += 1;
            }
            tokens.push(Token::String(s));
            continue;
        }

        // 数字
        if c.is_ascii_digit() || (c == '.' && i + 1 < chars.len() && chars[i + 1].is_ascii_digit()) {
            let start = i;
            let mut dot_count = if c == '.' { 1 } else { 0 };
            i += 1;
            while i < chars.len() {
                let ch = chars[i];
                if ch.is_ascii_digit() {
                    i += 1;
                } else if ch == '.' && dot_count == 0 {
                    dot_count += 1;
                    i += 1;
                } else {
                    break;
                }
            }
            let num_str: String = chars[start..i].iter().collect();
            match num_str.parse::<f64>() {
                Ok(n) => tokens.push(Token::Number(n)),
                Err(_) => return Err(format!("无效数字: {}", num_str)),
            }
            continue;
        }

        // 标识符 / 关键字 / 运算符
        if c.is_alphabetic() || c == '_' {
            let start = i;
            i += 1;
            while i < chars.len() && (chars[i].is_alphanumeric() || chars[i] == '_') {
                i += 1;
            }
            let word: String = chars[start..i].iter().collect();
            let lower = word.to_lowercase();
            match lower.as_str() {
                "true" => tokens.push(Token::Bool(true)),
                "false" => tokens.push(Token::Bool(false)),
                "null" | "none" => tokens.push(Token::Null),
                "and" => tokens.push(Token::And),
                "or" => tokens.push(Token::Or),
                "not" => tokens.push(Token::Not),
                _ => tokens.push(Token::Ident(word)),
            }
            continue;
        }

        // 运算符（>=, <=, ==, !=, **, +, -, *, /, %, <, >）
        let op = if i + 1 < chars.len() {
            let two: String = chars[i..i + 2].iter().collect();
            match two.as_str() {
                ">=" | "<=" | "==" | "!=" | "**" => {
                    i += 2;
                    two
                }
                _ => {
                    i += 1;
                    c.to_string()
                }
            }
        } else {
            i += 1;
            c.to_string()
        };
        tokens.push(Token::Op(op));
    }

    Ok(tokens)
}

struct Parser {
    tokens: Vec<Token>,
    pos: usize,
    context: HashMap<String, Value>,
}

impl Parser {
    fn new(tokens: Vec<Token>, context: HashMap<String, Value>) -> Self {
        Self { tokens, pos: 0, context }
    }

    fn peek(&self) -> Option<&Token> {
        self.tokens.get(self.pos)
    }

    fn consume(&mut self) -> Option<Token> {
        if self.pos < self.tokens.len() {
            let t = self.tokens[self.pos].clone();
            self.pos += 1;
            Some(t)
        } else {
            None
        }
    }

    fn expect_op(&mut self, op: &str) -> Result<(), String> {
        match self.peek() {
            Some(Token::Op(o)) if o == op => {
                self.consume();
                Ok(())
            }
            other => Err(format!("期望运算符 '{}', 得到 {:?}", op, other)),
        }
    }

    fn parse_expression(&mut self) -> Result<Value, String> {
        self.parse_or()
    }

    fn parse_or(&mut self) -> Result<Value, String> {
        let mut left = self.parse_and()?;
        while let Some(Token::Or) = self.peek() {
            self.consume();
            let right = self.parse_and()?;
            left = Value::Bool(left.is_truthy() || right.is_truthy());
        }
        Ok(left)
    }

    fn parse_and(&mut self) -> Result<Value, String> {
        let mut left = self.parse_not()?;
        while let Some(Token::And) = self.peek() {
            self.consume();
            let right = self.parse_not()?;
            left = Value::Bool(left.is_truthy() && right.is_truthy());
        }
        Ok(left)
    }

    fn parse_not(&mut self) -> Result<Value, String> {
        if let Some(Token::Not) = self.peek() {
            self.consume();
            let val = self.parse_not()?;
            return Ok(Value::Bool(!val.is_truthy()));
        }
        self.parse_comparison()
    }

    fn parse_comparison(&mut self) -> Result<Value, String> {
        let mut left = self.parse_additive()?;
        while let Some(Token::Op(op)) = self.peek() {
            let op = op.clone();
            if !matches!(op.as_str(), "==" | "!=" | "<" | "<=" | ">" | ">=") {
                break;
            }
            self.consume();
            let right = self.parse_additive()?;
            left = self.compare(&left, &op, &right)?;
        }
        Ok(left)
    }

    fn compare(&self, left: &Value, op: &str, right: &Value) -> Result<Value, String> {
        let result = match op {
            "==" => self.eq_values(left, right),
            "!=" => !self.eq_values(left, right),
            "<" => self.order_values(left, right)? < 0.0,
            "<=" => self.order_values(left, right)? <= 0.0,
            ">" => self.order_values(left, right)? > 0.0,
            ">=" => self.order_values(left, right)? >= 0.0,
            _ => return Err(format!("未知比较运算符: {}", op)),
        };
        Ok(Value::Bool(result))
    }

    fn eq_values(&self, a: &Value, b: &Value) -> bool {
        match (a, b) {
            (Value::Null, Value::Null) => true,
            (Value::Bool(x), Value::Bool(y)) => x == y,
            (Value::Number(x), Value::Number(y)) => (x - y).abs() < f64::EPSILON,
            (Value::String(x), Value::String(y)) => x == y,
            _ => false,
        }
    }

    fn order_values(&self, a: &Value, b: &Value) -> Result<f64, String> {
        match (a.as_number(), b.as_number()) {
            (Some(x), Some(y)) => Ok(x - y),
            _ => Err(format!(
                "无法比较非数值类型: {:?} 和 {:?}",
                a, b
            )),
        }
    }

    fn parse_additive(&mut self) -> Result<Value, String> {
        let mut left = self.parse_multiplicative()?;
        while let Some(Token::Op(op)) = self.peek() {
            let op = op.clone();
            if op != "+" && op != "-" {
                break;
            }
            self.consume();
            let right = self.parse_multiplicative()?;
            left = self.arith(&left, &op, &right)?;
        }
        Ok(left)
    }

    fn parse_multiplicative(&mut self) -> Result<Value, String> {
        let mut left = self.parse_power()?;
        while let Some(Token::Op(op)) = self.peek() {
            let op = op.clone();
            if op != "*" && op != "/" && op != "%" {
                break;
            }
            self.consume();
            let right = self.parse_power()?;
            left = self.arith(&left, &op, &right)?;
        }
        Ok(left)
    }

    fn parse_power(&mut self) -> Result<Value, String> {
        let base = self.parse_unary()?;
        if let Some(Token::Op(op)) = self.peek() {
            if op == "**" {
                self.consume();
                let exp = self.parse_power()?;
                return self.arith(&base, "**", &exp);
            }
        }
        Ok(base)
    }

    fn parse_unary(&mut self) -> Result<Value, String> {
        if let Some(Token::Op(op)) = self.peek() {
            if op == "-" || op == "+" {
                let op = op.clone();
                self.consume();
                let val = self.parse_unary()?;
                return match (op.as_str(), val) {
                    ("-", Value::Number(n)) => Ok(Value::Number(-n)),
                    ("+", Value::Number(n)) => Ok(Value::Number(n)),
                    _ => Err(format!("一元运算符 '{}' 只能用于数字", op)),
                };
            }
        }
        self.parse_primary()
    }

    fn parse_primary(&mut self) -> Result<Value, String> {
        match self.peek() {
            Some(Token::Number(n)) => {
                let v = *n;
                self.consume();
                Ok(Value::Number(v))
            }
            Some(Token::String(s)) => {
                let v = s.clone();
                self.consume();
                Ok(Value::String(v))
            }
            Some(Token::Bool(b)) => {
                let v = *b;
                self.consume();
                Ok(Value::Bool(v))
            }
            Some(Token::Null) => {
                self.consume();
                Ok(Value::Null)
            }
            Some(Token::Ident(name)) => {
                let name = name.clone();
                self.consume();
                self.context
                    .get(&name)
                    .cloned()
                    .ok_or_else(|| format!("未定义的标识符: {}", name))
            }
            Some(Token::LParen) => {
                self.consume();
                let val = self.parse_expression()?;
                if let Some(Token::RParen) = self.peek() {
                    self.consume();
                    Ok(val)
                } else {
                    Err("缺少右括号".to_string())
                }
            }
            other => Err(format!("意外的 token: {:?}", other)),
        }
    }

    fn arith(&self, left: &Value, op: &str, right: &Value) -> Result<Value, String> {
        let x = left
            .as_number()
            .ok_or_else(|| format!("运算符 '{}' 左操作数不是数字", op))?;
        let y = right
            .as_number()
            .ok_or_else(|| format!("运算符 '{}' 右操作数不是数字", op))?;
        match op {
            "+" => Ok(Value::Number(x + y)),
            "-" => Ok(Value::Number(x - y)),
            "*" => Ok(Value::Number(x * y)),
            "/" => {
                if y == 0.0 {
                    return Err("除零错误".to_string());
                }
                Ok(Value::Number(x / y))
            }
            "%" => Ok(Value::Number(x % y)),
            "**" => Ok(Value::Number(x.powf(y))),
            _ => Err(format!("未知算术运算符: {}", op)),
        }
    }
}

pub fn evaluate_condition(
    expression: &str,
    context: HashMap<String, Value>,
) -> Result<bool, String> {
    let tokens = tokenize(expression)?;
    if tokens.is_empty() {
        return Ok(true);
    }
    let mut parser = Parser::new(tokens, context);
    let value = parser.parse_expression()?;
    Ok(value.is_truthy())
}

/// PyO3 暴露函数：接受表达式和变量字典，返回 bool。
#[pyfunction]
pub fn evaluate_condition_py(
    expression: &str,
    variables: &Bound<'_, PyDict>,
) -> PyResult<bool> {
    let mut context = HashMap::new();
    for (key_obj, val_obj) in variables.iter() {
        let key = key_obj.extract::<String>()?;
        let value = pyobject_to_value(&val_obj)?;
        context.insert(key, value);
    }
    match evaluate_condition(expression, context) {
        Ok(result) => Ok(result),
        Err(e) => Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(e)),
    }
}

// `evaluate_condition_py` 在 lib.rs 中通过 wrap_pyfunction 注册到 Python 模块。
