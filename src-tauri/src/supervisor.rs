//! Starts, watches and re-attaches to the local background service.
//!
//! Two guarantees from the specification (section 4):
//!   * if the service dies, the core reports it and starts it again;
//!   * if the user interface dies, the service keeps running and is
//!     picked up again on the next start.

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use rand::RngCore;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager};

use crate::secrets;

const TOKEN_KEY: &str = "service-token";
const PROBE_INTERVAL: Duration = Duration::from_secs(1);
const FAILURES_BEFORE_RESTART: u32 = 3;

#[derive(Clone, Serialize)]
pub struct Status {
    pub state: &'static str,
    pub detail: String,
}

#[derive(Clone, Serialize)]
pub struct Endpoint {
    pub port: u16,
    pub token: String,
}

#[derive(Deserialize)]
struct RuntimeFile {
    port: u16,
}

pub struct Supervisor {
    endpoint: Mutex<Option<Endpoint>>,
    child: Mutex<Option<Child>>,
    status: Mutex<Status>,
}

impl Supervisor {
    pub fn new() -> Self {
        Self {
            endpoint: Mutex::new(None),
            child: Mutex::new(None),
            status: Mutex::new(Status {
                state: "startet",
                detail: String::new(),
            }),
        }
    }

    pub fn endpoint(&self) -> Option<Endpoint> {
        self.endpoint.lock().unwrap().clone()
    }

    pub fn status(&self) -> Status {
        self.status.lock().unwrap().clone()
    }

    fn publish(&self, app: &AppHandle, state: &'static str, detail: impl Into<String>) {
        let status = Status {
            state,
            detail: detail.into(),
        };
        *self.status.lock().unwrap() = status.clone();
        let _ = app.emit("service-status", status);
    }
}

fn token() -> String {
    if let Some(existing) = secrets::get(TOKEN_KEY) {
        if !existing.is_empty() {
            return existing;
        }
    }
    let mut bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut bytes);
    let fresh: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
    let _ = secrets::set(TOKEN_KEY, &fresh);
    fresh
}

fn runtime_file() -> PathBuf {
    let base = std::env::var("APPDATA").unwrap_or_default();
    PathBuf::from(base).join("Zahnputztracker").join("runtime.json")
}

/// Ask a candidate port whether our service is listening there.
/// Returns Ok(true) when the token is accepted.
fn probe(port: u16, token: &str) -> Result<bool, String> {
    let url = format!("http://127.0.0.1:{port}/health");
    match ureq::get(&url)
        .set("X-Auth-Token", token)
        .timeout(Duration::from_secs(2))
        .call()
    {
        Ok(_) => Ok(true),
        Err(ureq::Error::Status(401, _)) => Ok(false),
        Err(ureq::Error::Status(code, _)) => Err(format!("HTTP {code}")),
        Err(e) => Err(e.to_string()),
    }
}

/// Re-attach to a service that survived a restart of the user interface.
fn attach(token: &str) -> Option<u16> {
    let raw = std::fs::read_to_string(runtime_file()).ok()?;
    let parsed: RuntimeFile = serde_json::from_str(&raw).ok()?;
    match probe(parsed.port, token) {
        Ok(true) => Some(parsed.port),
        _ => None,
    }
}

/// Command line of the service. In development the project virtual
/// environment is used; a packaged build runs the bundled executable.
fn service_command(app: &AppHandle) -> Command {
    if cfg!(debug_assertions) {
        let project = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .expect("project root")
            .to_path_buf();
        let python = project.join(".venv").join("Scripts").join("python.exe");
        let mut command = Command::new(python);
        command.args(["-m", "service.main"]).current_dir(project);
        command
    } else {
        let dir = app
            .path()
            .resource_dir()
            .expect("resource dir")
            .join("service");
        let mut command = Command::new(dir.join("service.exe"));
        command.current_dir(dir);
        command
    }
}

#[cfg(windows)]
fn hide_console(command: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    command.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn hide_console(_command: &mut Command) {}

fn spawn(app: &AppHandle, token: &str) -> Result<(u16, Child), String> {
    let mut command = service_command(app);
    hide_console(&mut command);
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Dienst konnte nicht gestartet werden: {e}"))?;

    // The token travels over standard input and is never written to a file.
    child
        .stdin
        .as_mut()
        .ok_or("kein Eingabekanal")?
        .write_all(format!("{token}\n").as_bytes())
        .map_err(|e| e.to_string())?;

    let stdout = child.stdout.take().ok_or("kein Ausgabekanal")?;
    let mut reader = BufReader::new(stdout);
    let mut line = String::new();
    reader.read_line(&mut line).map_err(|e| e.to_string())?;

    let handshake: serde_json::Value =
        serde_json::from_str(line.trim()).map_err(|_| format!("unerwartete Antwort: {line}"))?;
    match handshake.get("event").and_then(|v| v.as_str()) {
        Some("ready") => {
            let port = handshake
                .get("port")
                .and_then(|v| v.as_u64())
                .ok_or("kein Port in der Antwort")? as u16;
            // Keep draining stdout so the service never blocks on a full pipe.
            std::thread::spawn(move || {
                let mut sink = String::new();
                while reader.read_line(&mut sink).unwrap_or(0) > 0 {
                    sink.clear();
                }
            });
            Ok((port, child))
        }
        Some("already_running") => {
            let _ = child.kill();
            Err("Dienst laeuft bereits, konnte aber nicht uebernommen werden".into())
        }
        _ => {
            let _ = child.kill();
            Err(format!("unerwartete Antwort: {line}"))
        }
    }
}

/// Start or adopt the service, then keep watching it.
pub fn launch(app: AppHandle) {
    let supervisor = app.state::<Arc<Supervisor>>().inner().clone();
    std::thread::spawn(move || {
        let token = token();

        if let Some(port) = attach(&token) {
            *supervisor.endpoint.lock().unwrap() = Some(Endpoint {
                port,
                token: token.clone(),
            });
            supervisor.publish(&app, "verbunden", "vorhandenen Dienst uebernommen");
        }

        let mut failures = 0u32;
        loop {
            match supervisor.endpoint() {
                None => {
                    supervisor.publish(&app, "startet", "");
                    match spawn(&app, &token) {
                        Ok((port, child)) => {
                            *supervisor.child.lock().unwrap() = Some(child);
                            *supervisor.endpoint.lock().unwrap() = Some(Endpoint {
                                port,
                                token: token.clone(),
                            });
                            failures = 0;
                            supervisor.publish(&app, "verbunden", "");
                        }
                        Err(reason) => {
                            supervisor.publish(&app, "getrennt", reason);
                            std::thread::sleep(Duration::from_secs(5));
                        }
                    }
                }
                Some(endpoint) => match probe(endpoint.port, &endpoint.token) {
                    Ok(true) => {
                        if failures > 0 {
                            failures = 0;
                            supervisor.publish(&app, "verbunden", "");
                        }
                    }
                    _ => {
                        failures += 1;
                        if failures >= FAILURES_BEFORE_RESTART {
                            supervisor.publish(
                                &app,
                                "getrennt",
                                "Dienst antwortet nicht, Neustart",
                            );
                            *supervisor.endpoint.lock().unwrap() = None;
                            if let Some(mut child) = supervisor.child.lock().unwrap().take() {
                                let _ = child.kill();
                                let _ = child.wait();
                            }
                            failures = 0;
                        }
                    }
                },
            }
            std::thread::sleep(PROBE_INTERVAL);
        }
    });
}

/// Force a restart: the watchdog picks the service up again immediately.
pub fn restart(supervisor: &Supervisor) {
    *supervisor.endpoint.lock().unwrap() = None;
    if let Some(mut child) = supervisor.child.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}
