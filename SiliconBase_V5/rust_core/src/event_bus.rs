use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::HashMap;
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::Duration;

type EventItem = (String, Py<PyAny>);

struct EventBusInner {
    handlers: HashMap<String, Vec<Py<PyAny>>>,
    wildcard_handlers: Vec<Py<PyAny>>,
    running: bool,
    stats: HashMap<String, u64>,
}

impl EventBusInner {
    fn new() -> Self {
        let mut stats = HashMap::new();
        stats.insert("published".to_string(), 0);
        stats.insert("handled".to_string(), 0);
        stats.insert("errors".to_string(), 0);
        Self {
            handlers: HashMap::new(),
            wildcard_handlers: Vec::new(),
            running: true,
            stats,
        }
    }
}

fn worker_loop(inner: Arc<Mutex<EventBusInner>>, rx: mpsc::Receiver<EventItem>) {
    loop {
        match rx.recv_timeout(Duration::from_millis(100)) {
            Ok((event_type, data)) => {
                let mut handled = 0u64;
                let mut errors = 0u64;
                let _ = Python::attach(|py| -> PyResult<()> {
                    let callbacks: Vec<Py<PyAny>> = {
                        let guard = inner.lock().unwrap();
                        let mut cbs = Vec::new();
                        if let Some(list) = guard.handlers.get(&event_type) {
                            for h in list {
                                cbs.push(h.clone_ref(py));
                            }
                        }
                        for h in guard.wildcard_handlers.iter() {
                            cbs.push(h.clone_ref(py));
                        }
                        cbs
                    };
                    for cb in callbacks {
                        match cb.call1(py, (&data,)) {
                            Ok(_) => handled += 1,
                            Err(_) => errors += 1,
                        }
                    }
                    Ok(())
                });

                let mut guard = inner.lock().unwrap();
                *guard.stats.entry("handled".to_string()).or_insert(0) += handled;
                *guard.stats.entry("errors".to_string()).or_insert(0) += errors;
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {
                let guard = inner.lock().unwrap();
                if !guard.running {
                    break;
                }
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }
}

#[pyclass]
pub struct EventBus {
    inner: Arc<Mutex<EventBusInner>>,
    sender: mpsc::Sender<EventItem>,
    worker: Arc<Mutex<Option<thread::JoinHandle<()>>>>,
}

#[pymethods]
impl EventBus {
    #[new]
    fn new() -> PyResult<Self> {
        let (tx, rx) = mpsc::channel();
        let inner = Arc::new(Mutex::new(EventBusInner::new()));
        let worker = Arc::new(Mutex::new(None));

        let worker_inner = inner.clone();
        let handle = thread::spawn(move || worker_loop(worker_inner, rx));
        *worker.lock().unwrap() = Some(handle);

        Ok(Self {
            inner,
            sender: tx,
            worker,
        })
    }

    fn subscribe(&self, event_type: &str, handler: &Bound<'_, PyAny>) -> PyResult<()> {
        let cb = handler.clone().unbind();
        let mut guard = self.inner.lock().unwrap();
        let list = guard.handlers.entry(event_type.to_string()).or_default();
        if !list.iter().any(|existing| existing.is(&cb)) {
            list.push(cb);
        }
        Ok(())
    }

    fn subscribe_all(&self, handler: &Bound<'_, PyAny>) -> PyResult<()> {
        let cb = handler.clone().unbind();
        let mut guard = self.inner.lock().unwrap();
        if !guard
            .wildcard_handlers
            .iter()
            .any(|existing| existing.is(&cb))
        {
            guard.wildcard_handlers.push(cb);
        }
        Ok(())
    }

    fn unsubscribe(&self, event_type: &str, handler: &Bound<'_, PyAny>) -> PyResult<bool> {
        let target = handler.clone().unbind();
        let mut guard = self.inner.lock().unwrap();
        if let Some(list) = guard.handlers.get_mut(event_type) {
            let before = list.len();
            list.retain(|existing| !existing.is(&target));
            return Ok(list.len() < before);
        }
        Ok(false)
    }

    fn publish(&self, event_type: &str, data: &Bound<'_, PyAny>) -> PyResult<bool> {
        let item = (event_type.to_string(), data.clone().unbind());
        {
            let mut guard = self.inner.lock().unwrap();
            if !guard.running {
                return Ok(false);
            }
            *guard.stats.entry("published".to_string()).or_insert(0) += 1;
        }
        match self.sender.send(item) {
            Ok(_) => Ok(true),
            Err(_) => {
                let mut guard = self.inner.lock().unwrap();
                *guard.stats.entry("errors".to_string()).or_insert(0) += 1;
                Ok(false)
            }
        }
    }

    fn start(&self) -> PyResult<()> {
        let mut guard = self.inner.lock().unwrap();
        if guard.running {
            return Ok(());
        }
        guard.running = true;
        Ok(())
    }

    fn stop(&mut self) -> PyResult<()> {
        {
            let mut guard = self.inner.lock().unwrap();
            guard.running = false;
        }
        if let Some(handle) = self.worker.lock().unwrap().take() {
            let _ = handle.join();
        }
        Ok(())
    }

    fn get_stats(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let guard = self.inner.lock().unwrap();
        let dict = PyDict::new(py);
        for (k, v) in guard.stats.iter() {
            dict.set_item(k, *v)?;
        }
        Ok(dict.unbind())
    }

    fn clear(&self) -> PyResult<()> {
        let mut guard = self.inner.lock().unwrap();
        guard.handlers.clear();
        guard.wildcard_handlers.clear();
        guard.stats.insert("published".to_string(), 0);
        guard.stats.insert("handled".to_string(), 0);
        guard.stats.insert("errors".to_string(), 0);
        Ok(())
    }
}
