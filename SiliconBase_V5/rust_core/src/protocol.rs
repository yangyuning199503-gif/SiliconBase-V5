use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList};
use std::time::{SystemTime, UNIX_EPOCH};
use uuid::Uuid;

fn now_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

fn generate_trace_id() -> String {
    Uuid::new_v4().to_string()
}

fn create_message_inner(
    py: Python<'_>,
    msg_type: &str,
    source: &str,
    payload: &Bound<'_, PyAny>,
    target: Option<&str>,
    trace_id: Option<&str>,
) -> PyResult<Py<PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("msg_type", msg_type)?;
    dict.set_item("source", source)?;
    dict.set_item("target", target)?;
    dict.set_item("payload", payload)?;
    dict.set_item("timestamp", now_seconds())?;
    dict.set_item("trace_id", trace_id.unwrap_or(&generate_trace_id()))?;
    Ok(dict.unbind())
}

#[pyfunction]
#[pyo3(name = "create_message")]
#[pyo3(signature = (msg_type, source, payload, target=None, trace_id=None))]
fn create_message_py(
    py: Python<'_>,
    msg_type: &str,
    source: &str,
    payload: &Bound<'_, PyAny>,
    target: Option<&str>,
    trace_id: Option<&str>,
) -> PyResult<Py<PyDict>> {
    create_message_inner(py, msg_type, source, payload, target, trace_id)
}

fn empty_dict(py: Python<'_>) -> Bound<'_, PyDict> {
    PyDict::new(py)
}

#[pyfunction]
#[pyo3(name = "create_task_request")]
#[pyo3(signature = (goal, source="user", priority="normal", context=None, session_id="default", task_id=None))]
fn create_task_request_py(
    py: Python<'_>,
    goal: &str,
    source: &str,
    priority: &str,
    context: Option<&Bound<'_, PyDict>>,
    session_id: &str,
    task_id: Option<&str>,
) -> PyResult<Py<PyDict>> {
    let payload = empty_dict(py);
    payload.set_item("task_id", task_id.unwrap_or(&generate_trace_id()))?;
    payload.set_item("goal", goal)?;
    payload.set_item("priority", priority)?;
    match context {
        Some(ctx) => payload.set_item("context", ctx)?,
        None => payload.set_item("context", empty_dict(py))?,
    }
    payload.set_item("source", source)?;
    payload.set_item("session_id", session_id)?;
    create_message_inner(py, "task:request", source, payload.as_any(), None, None)
}

#[pyfunction]
#[pyo3(name = "create_task_result")]
#[pyo3(signature = (task_id, success, result, tools_used=None, error=None, execution_time=0.0, source="agent_loop"))]
fn create_task_result_py(
    py: Python<'_>,
    task_id: &str,
    success: bool,
    result: &Bound<'_, PyAny>,
    tools_used: Option<&Bound<'_, PyAny>>,
    error: Option<&str>,
    execution_time: f64,
    source: &str,
) -> PyResult<Py<PyDict>> {
    let payload = empty_dict(py);
    payload.set_item("task_id", task_id)?;
    payload.set_item("success", success)?;
    payload.set_item("result", result)?;
    match tools_used {
        Some(list) => payload.set_item("tools_used", list)?,
        None => payload.set_item("tools_used", PyList::empty(py))?,
    }
    payload.set_item("error", error)?;
    payload.set_item("execution_time", execution_time)?;
    create_message_inner(py, "task:result", source, payload.as_any(), None, None)
}

#[pyfunction]
#[pyo3(name = "create_tool_call")]
#[pyo3(signature = (tool_id, params, task_id, timeout=30, source="agent_loop"))]
fn create_tool_call_py(
    py: Python<'_>,
    tool_id: &str,
    params: &Bound<'_, PyAny>,
    task_id: &str,
    timeout: i64,
    source: &str,
) -> PyResult<Py<PyDict>> {
    let payload = empty_dict(py);
    payload.set_item("tool_id", tool_id)?;
    payload.set_item("params", params)?;
    payload.set_item("task_id", task_id)?;
    payload.set_item("timeout", timeout)?;
    create_message_inner(
        py,
        "tool:call",
        source,
        payload.as_any(),
        Some("tool_manager"),
        None,
    )
}

#[pyfunction]
#[pyo3(name = "create_thought")]
#[pyo3(signature = (content, source="consciousness", emotional_state=None, trigger=None))]
fn create_thought_py(
    py: Python<'_>,
    content: &str,
    source: &str,
    emotional_state: Option<&Bound<'_, PyAny>>,
    trigger: Option<&str>,
) -> PyResult<Py<PyDict>> {
    let payload = empty_dict(py);
    payload.set_item("thought_id", generate_trace_id())?;
    payload.set_item("content", content)?;
    payload.set_item("source", source)?;
    payload.set_item("emotional_state", emotional_state)?;
    payload.set_item("trigger", trigger)?;
    create_message_inner(py, "consciousness:thought", source, payload.as_any(), None, None)
}

#[pyfunction]
#[pyo3(name = "create_reflection_request")]
#[pyo3(signature = (task_description, execution_history, task_id=None, source="consciousness"))]
fn create_reflection_request_py(
    py: Python<'_>,
    task_description: &str,
    execution_history: &Bound<'_, PyAny>,
    task_id: Option<&str>,
    source: &str,
) -> PyResult<Py<PyDict>> {
    let payload = empty_dict(py);
    payload.set_item("reflection_id", generate_trace_id())?;
    payload.set_item("task_id", task_id)?;
    payload.set_item("task_description", task_description)?;
    payload.set_item("execution_history", execution_history)?;
    payload.set_item("success", None::<Option<&str>>)?;
    payload.set_item("insights", None::<Option<&str>>)?;
    payload.set_item("suggestions", None::<Option<&str>>)?;
    create_message_inner(py, "reflection:request", source, payload.as_any(), None, None)
}

#[pyfunction]
#[pyo3(name = "create_reflection_result")]
#[pyo3(signature = (reflection_id, success, insights, suggestions, task_id=None, source="reflector"))]
fn create_reflection_result_py(
    py: Python<'_>,
    reflection_id: &str,
    success: bool,
    insights: &Bound<'_, PyAny>,
    suggestions: &Bound<'_, PyAny>,
    task_id: Option<&str>,
    source: &str,
) -> PyResult<Py<PyDict>> {
    let payload = empty_dict(py);
    payload.set_item("reflection_id", reflection_id)?;
    payload.set_item("task_id", task_id)?;
    payload.set_item("task_description", "")?;
    payload.set_item("execution_history", PyList::empty(py))?;
    payload.set_item("success", success)?;
    payload.set_item("insights", insights)?;
    payload.set_item("suggestions", suggestions)?;
    create_message_inner(py, "reflection:result", source, payload.as_any(), None, None)
}

#[pyfunction]
#[pyo3(name = "create_evolution_trigger")]
#[pyo3(signature = (trigger_type, task_id=None, description=None, report=None, source="evolution"))]
fn create_evolution_trigger_py(
    py: Python<'_>,
    trigger_type: &str,
    task_id: Option<&str>,
    description: Option<&str>,
    report: Option<&Bound<'_, PyAny>>,
    source: &str,
) -> PyResult<Py<PyDict>> {
    let payload = empty_dict(py);
    payload.set_item("trigger_type", trigger_type)?;
    payload.set_item("task_id", task_id)?;
    payload.set_item("description", description)?;
    payload.set_item("report", report)?;
    create_message_inner(py, "evolution:trigger", source, payload.as_any(), None, None)
}

#[pyfunction]
#[pyo3(name = "validate_message")]
fn validate_message_py(message: &Bound<'_, PyDict>) -> PyResult<bool> {
    let required = ["msg_type", "source", "payload", "timestamp", "trace_id"];
    for key in required {
        if !message.contains(key)? {
            return Ok(false);
        }
    }
    Ok(true)
}

#[pyfunction]
#[pyo3(name = "generate_trace_id")]
fn generate_trace_id_py() -> String {
    generate_trace_id()
}

#[pyfunction]
#[pyo3(name = "priority_to_number")]
fn priority_to_number_py(priority: &str) -> i32 {
    match priority.to_lowercase().as_str() {
        "high" => 1,
        "normal" => 2,
        "low" => 3,
        _ => 2,
    }
}

#[pyfunction]
#[pyo3(name = "number_to_priority")]
fn number_to_priority_py(number: i32) -> String {
    match number {
        1 => "high".to_string(),
        2 => "normal".to_string(),
        3 => "low".to_string(),
        _ => "normal".to_string(),
    }
}

#[pyfunction]
#[pyo3(name = "get_message_summary")]
#[pyo3(signature = (msg, max_length=100))]
fn get_message_summary_py(msg: &Bound<'_, PyDict>, max_length: usize) -> PyResult<String> {
    let _py = msg.py();
    let msg_type: String = msg
        .get_item("msg_type")?
        .and_then(|v| v.extract::<String>().ok())
        .unwrap_or_else(|| "unknown".to_string());
    let source: String = msg
        .get_item("source")?
        .and_then(|v| v.extract::<String>().ok())
        .unwrap_or_else(|| "unknown".to_string());
    let trace_id: String = msg
        .get_item("trace_id")?
        .and_then(|v| v.extract::<String>().ok())
        .unwrap_or_else(|| "no-trace".to_string());

    let content = if let Ok(Some(payload)) = msg.get_item("payload") {
        if let Ok(dict) = payload.cast::<PyDict>() {
            let goal = dict
                .get_item("goal")?
                .and_then(|v| v.extract::<String>().ok());
            let task_id = dict
                .get_item("task_id")?
                .and_then(|v| v.extract::<String>().ok());
            let result = dict.get_item("result")?;
            if let Some(g) = goal {
                truncate(&g, max_length)
            } else if let Some(t) = task_id {
                format!("task:{}", truncate(&t, 8.min(max_length)))
            } else if let Some(r) = result {
                if let Ok(s) = r.extract::<String>() {
                    truncate(&s, max_length)
                } else {
                    truncate(&r.to_string(), max_length)
                }
            } else {
                truncate(&payload.to_string(), max_length)
            }
        } else {
            truncate(&payload.to_string(), max_length)
        }
    } else {
        "no-payload".to_string()
    };

    Ok(format!(
        "[{}] from:{} trace:{} - {}",
        msg_type,
        source,
        truncate(&trace_id, 8),
        content
    ))
}

fn truncate(s: &str, max_len: usize) -> String {
    if s.chars().count() <= max_len {
        s.to_string()
    } else {
        s.chars().take(max_len).collect::<String>() + "..."
    }
}

pub fn register_protocol(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(create_message_py, m)?)?;
    m.add_function(wrap_pyfunction!(create_task_request_py, m)?)?;
    m.add_function(wrap_pyfunction!(create_task_result_py, m)?)?;
    m.add_function(wrap_pyfunction!(create_tool_call_py, m)?)?;
    m.add_function(wrap_pyfunction!(create_thought_py, m)?)?;
    m.add_function(wrap_pyfunction!(create_reflection_request_py, m)?)?;
    m.add_function(wrap_pyfunction!(create_reflection_result_py, m)?)?;
    m.add_function(wrap_pyfunction!(create_evolution_trigger_py, m)?)?;
    m.add_function(wrap_pyfunction!(validate_message_py, m)?)?;
    m.add_function(wrap_pyfunction!(generate_trace_id_py, m)?)?;
    m.add_function(wrap_pyfunction!(priority_to_number_py, m)?)?;
    m.add_function(wrap_pyfunction!(number_to_priority_py, m)?)?;
    m.add_function(wrap_pyfunction!(get_message_summary_py, m)?)?;
    Ok(())
}
