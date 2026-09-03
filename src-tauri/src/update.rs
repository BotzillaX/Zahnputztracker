//! Updates (specification 13).
//!
//! The rules that shape this file:
//!
//!   * Nothing is downloaded before the user asks for it (13.5). The
//!     background check only reads the small description file.
//!   * A failed background check stays quiet. No internet is not a
//!     problem the user has to solve (13.4).
//!   * Before an installation both browsers are closed in an orderly
//!     way and only then is the service ended (13.5). A browser that is
//!     killed leaves orphaned processes and locked profiles behind.
//!   * Without a valid signature nothing is installed. That is the
//!     plugin's own rule; here it only has to stay switched on.

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::json;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_updater::UpdaterExt;

use crate::supervisor::{self, Supervisor};

/// Both values in the configuration are filled in (see
/// docs\signatur.md). Should a fresh key pair ever put a placeholder
/// back, the button says so instead of reporting an error nobody can
/// act on.
const PLACEHOLDER: &str = "PLATZHALTER";

const FIRST_CHECK: Duration = Duration::from_secs(5);
const BETWEEN_CHECKS: Duration = Duration::from_secs(6 * 60 * 60);
/// How long the browsers are given to close by themselves.
const CLOSING_GRACE: Duration = Duration::from_secs(20);

pub const UNSET: &str = "nicht_eingerichtet";
pub const IDLE: &str = "aktuell";
pub const CHECKING: &str = "pruefung";
pub const AVAILABLE: &str = "verfuegbar";
pub const DOWNLOADING: &str = "laedt";
pub const READY: &str = "bereit";
pub const ERROR: &str = "fehler";

#[derive(Clone, Serialize)]
pub struct State {
    /// One of the constants above. The user interface shows one of the
    /// six appearances of the button from 13.4 for it.
    pub state: String,
    pub current: String,
    pub version: String,
    pub notes: String,
    pub date: String,
    pub done: u64,
    pub total: u64,
    /// Only shown on hover. A background failure never lights up.
    pub detail: String,
    pub checked_at: String,
}

impl Default for State {
    fn default() -> Self {
        Self {
            state: IDLE.into(),
            current: env!("CARGO_PKG_VERSION").into(),
            version: String::new(),
            notes: String::new(),
            date: String::new(),
            done: 0,
            total: 0,
            detail: String::new(),
            checked_at: String::new(),
        }
    }
}

pub struct Updates {
    state: Mutex<State>,
    /// A check and an installation never run twice at the same time.
    working: Mutex<bool>,
}

impl Updates {
    pub fn new() -> Self {
        Self {
            state: Mutex::new(State::default()),
            working: Mutex::new(false),
        }
    }

    pub fn read(&self) -> State {
        self.state.lock().unwrap().clone()
    }

    fn write(&self, app: &AppHandle, change: impl FnOnce(&mut State)) {
        let mut state = self.state.lock().unwrap();
        change(&mut state);
        let _ = app.emit("update-status", state.clone());
    }

    fn claim(&self) -> bool {
        let mut working = self.working.lock().unwrap();
        if *working {
            return false;
        }
        *working = true;
        true
    }

    fn release(&self) {
        *self.working.lock().unwrap() = false;
    }
}

/// Whether the account and the key have been filled in.
fn configured(app: &AppHandle) -> bool {
    let Some(section) = app.config().plugins.0.get("updater") else {
        return false;
    };
    let key = section.get("pubkey").and_then(|v| v.as_str()).unwrap_or("");
    let endpoint = section
        .get("endpoints")
        .and_then(|v| v.as_array())
        .and_then(|list| list.first())
        .and_then(|v| v.as_str())
        .unwrap_or("");
    !key.contains(PLACEHOLDER) && !endpoint.contains(PLACEHOLDER)
}

fn now() -> String {
    // The core has no clock library of its own. The seconds since the
    // start of the day are enough for "checked just now".
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let day = seconds % 86_400;
    format!("{:02}:{:02}", day / 3600, (day % 3600) / 60)
}

/// Ask the release description whether there is something newer.
///
/// `loud` decides what a failure means: a forced check says so, a
/// background check falls silent and leaves the button as it was.
pub fn check(app: &AppHandle, loud: bool) {
    let updates = app.state::<Arc<Updates>>().inner().clone();
    if !configured(app) {
        updates.write(app, |state| {
            state.state = UNSET.into();
            state.detail = "Konto und Schlüssel sind noch nicht eingetragen".into();
        });
        return;
    }
    if !updates.claim() {
        return;
    }
    updates.write(app, |state| {
        state.state = CHECKING.into();
        state.detail.clear();
    });

    let answer = app
        .updater()
        .map_err(|error| error.to_string())
        .and_then(|updater| {
            tauri::async_runtime::block_on(updater.check()).map_err(|error| error.to_string())
        });
    updates.release();

    match answer {
        Ok(Some(found)) => updates.write(app, |state| {
            state.state = AVAILABLE.into();
            state.version = found.version.clone();
            state.notes = found.body.clone().unwrap_or_default();
            state.date = found.date.map(|d| d.to_string()).unwrap_or_default();
            state.detail.clear();
            state.checked_at = now();
        }),
        Ok(None) => updates.write(app, |state| {
            state.state = IDLE.into();
            state.version.clear();
            state.detail.clear();
            state.checked_at = now();
        }),
        Err(reason) => updates.write(app, |state| {
            if loud {
                state.state = ERROR.into();
            } else if state.state == CHECKING {
                // Back to how it looked before. A background failure
                // must not draw attention.
                state.state = IDLE.into();
            }
            state.detail = reason;
            state.checked_at = now();
        }),
    }
}

#[derive(Deserialize, Default)]
struct Fleet {
    #[serde(default)]
    running: bool,
    #[serde(default)]
    instances: Vec<serde_json::Value>,
}

#[derive(Deserialize, Default)]
struct Flow {
    #[serde(default)]
    running: bool,
}

fn get<T: serde::de::DeserializeOwned>(supervisor: &Supervisor, path: &str) -> Option<T> {
    let endpoint = supervisor.endpoint()?;
    ureq::get(&format!("http://127.0.0.1:{}{path}", endpoint.port))
        .set("X-Auth-Token", &endpoint.token)
        .timeout(Duration::from_secs(3))
        .call()
        .ok()?
        .into_json()
        .ok()
}

fn post(supervisor: &Supervisor, path: &str, body: serde_json::Value) -> bool {
    let Some(endpoint) = supervisor.endpoint() else {
        return false;
    };
    ureq::post(&format!("http://127.0.0.1:{}{path}", endpoint.port))
        .set("X-Auth-Token", &endpoint.token)
        .timeout(Duration::from_secs(60))
        .send_json(body)
        .is_ok()
}

/// What the user has to be asked about before an installation (13.5).
#[derive(Serialize, Default)]
pub struct Situation {
    pub browsers_running: bool,
    pub flow_running: bool,
}

pub fn situation(supervisor: &Supervisor) -> Situation {
    let fleet: Fleet = get(supervisor, "/browser").unwrap_or_default();
    let flow: Flow = get(supervisor, "/flow").unwrap_or_default();
    Situation {
        browsers_running: fleet.running || !fleet.instances.is_empty(),
        flow_running: flow.running,
    }
}

/// Stop the run, close both browsers, end the service. In that order.
fn make_room(app: &AppHandle, supervisor: &Supervisor) {
    let updates = app.state::<Arc<Updates>>().inner().clone();
    updates.write(app, |state| {
        state.detail = "Vorgang wird beendet".into();
    });
    post(supervisor, "/flow/stop", json!({}));

    updates.write(app, |state| {
        state.detail = "Browser werden geschlossen".into();
    });
    post(supervisor, "/browser/stop", json!({}));

    // Wait for the browsers to really be gone. Only then may the
    // service be ended, or the processes would stay behind.
    let deadline = Instant::now() + CLOSING_GRACE;
    while Instant::now() < deadline {
        let fleet: Fleet = get(supervisor, "/browser").unwrap_or_default();
        if !fleet.running && fleet.instances.is_empty() {
            break;
        }
        std::thread::sleep(Duration::from_millis(500));
    }

    updates.write(app, |state| {
        state.detail = "Dienst wird beendet".into();
    });
    supervisor::halt(supervisor);
}

/// Download and install. Only ever after a click (13.5).
pub fn install(app: &AppHandle) -> Result<(), String> {
    let updates = app.state::<Arc<Updates>>().inner().clone();
    let supervisor = app.state::<Arc<Supervisor>>().inner().clone();
    if !configured(app) {
        return Err("Konto und Schlüssel sind noch nicht eingetragen".into());
    }
    if !updates.claim() {
        return Err("Es läuft bereits etwas".into());
    }

    let found = app
        .updater()
        .map_err(|error| error.to_string())
        .and_then(|updater| {
            tauri::async_runtime::block_on(updater.check()).map_err(|error| error.to_string())
        });
    let found = match found {
        Ok(Some(found)) => found,
        Ok(None) => {
            updates.release();
            updates.write(app, |state| {
                state.state = IDLE.into();
                state.version.clear();
            });
            return Err("Es gibt nichts Neueres".into());
        }
        Err(reason) => {
            updates.release();
            updates.write(app, |state| {
                state.state = ERROR.into();
                state.detail = reason.clone();
            });
            return Err(reason);
        }
    };

    make_room(app, &supervisor);

    updates.write(app, |state| {
        state.state = DOWNLOADING.into();
        state.done = 0;
        state.total = 0;
        state.detail.clear();
    });

    let counting = app.clone();
    let finished = app.clone();
    let outcome = tauri::async_runtime::block_on(found.download_and_install(
        move |chunk, total| {
            let updates = counting.state::<Arc<Updates>>().inner().clone();
            updates.write(&counting, |state| {
                state.done += chunk as u64;
                state.total = total.unwrap_or(0);
            });
        },
        move || {
            let updates = finished.state::<Arc<Updates>>().inner().clone();
            updates.write(&finished, |state| {
                state.state = READY.into();
                state.detail = "Wird installiert, die Anwendung startet neu".into();
            });
        },
    ));
    updates.release();

    match outcome {
        Ok(()) => {
            // The installer takes over from here. Restarting is the
            // last thing this process does.
            app.restart();
        }
        Err(error) => {
            let reason = error.to_string();
            updates.write(app, |state| {
                state.state = ERROR.into();
                state.detail = reason.clone();
            });
            Err(reason)
        }
    }
}

/// The two quiet checks from 13.3: shortly after the start, then every
/// six hours.
pub fn watch(app: AppHandle) {
    std::thread::spawn(move || {
        std::thread::sleep(FIRST_CHECK);
        loop {
            check(&app, false);
            std::thread::sleep(BETWEEN_CHECKS);
        }
    });
}
