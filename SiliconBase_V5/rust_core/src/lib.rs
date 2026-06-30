mod condition_evaluator;
mod event_bus;
mod protocol;

use pyo3::prelude::*;

/// A Python module implemented in Rust.
#[pymodule]
fn siliconbase_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(
        condition_evaluator::evaluate_condition_py,
        m
    )?)?;
    protocol::register_protocol(m)?;
    m.add_class::<event_bus::EventBus>()?;
    Ok(())
}
