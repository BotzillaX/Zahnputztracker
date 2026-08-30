//! Tray icon.
//!
//! Specification 5.3 and 5.4: the browser windows are shown and hidden
//! from here, and the run can be paused from here. Nothing in this file
//! decides anything: it asks the service and reports the answer back.

use std::sync::Arc;
use std::time::Duration;

use serde::Deserialize;
use serde_json::json;
use tauri::menu::{CheckMenuItem, Menu, MenuEvent, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager};

use crate::supervisor::Supervisor;

pub const SEARCH: &str = "search";
pub const SESSION: &str = "session";

#[derive(Deserialize, Default)]
pub struct InstanceState {
    pub role: String,
    pub running: bool,
    pub visible: bool,
}

#[derive(Deserialize, Default)]
pub struct FleetState {
    pub running: bool,
    pub paused: bool,
    #[serde(default)]
    pub instances: Vec<InstanceState>,
}

impl FleetState {
    fn visible(&self, role: &str) -> bool {
        self.instances
            .iter()
            .any(|entry| entry.role == role && entry.visible)
    }

    fn instance_running(&self, role: &str) -> bool {
        self.instances
            .iter()
            .any(|entry| entry.role == role && entry.running)
    }
}

fn get(supervisor: &Supervisor, path: &str) -> Option<FleetState> {
    let endpoint = supervisor.endpoint()?;
    ureq::get(&format!("http://127.0.0.1:{}{path}", endpoint.port))
        .set("X-Auth-Token", &endpoint.token)
        .timeout(Duration::from_secs(3))
        .call()
        .ok()?
        .into_json()
        .ok()
}

fn post(supervisor: &Supervisor, path: &str, body: serde_json::Value) -> Option<FleetState> {
    let endpoint = supervisor.endpoint()?;
    ureq::post(&format!("http://127.0.0.1:{}{path}", endpoint.port))
        .set("X-Auth-Token", &endpoint.token)
        .timeout(Duration::from_secs(30))
        .send_json(body)
        .ok()?
        .into_json()
        .ok()
}

pub fn fleet_state(supervisor: &Supervisor) -> Option<FleetState> {
    get(supervisor, "/browser")
}

pub fn set_visible(supervisor: &Supervisor, role: &str, visible: bool) -> Option<FleetState> {
    post(
        supervisor,
        &format!("/browser/{role}/visibility"),
        json!({ "visible": visible }),
    )
}

pub fn set_paused(supervisor: &Supervisor, paused: bool) -> Option<FleetState> {
    post(supervisor, "/browser/pause", json!({ "paused": paused }))
}

struct Items {
    search: CheckMenuItem<tauri::Wry>,
    session: CheckMenuItem<tauri::Wry>,
    pause: CheckMenuItem<tauri::Wry>,
}

pub fn install(app: &AppHandle) -> tauri::Result<()> {
    let window_item = MenuItem::with_id(app, "ui", "Fenster anzeigen", true, None::<&str>)?;
    let search = CheckMenuItem::with_id(
        app,
        "show-search",
        "Such-Browser einblenden",
        false,
        false,
        None::<&str>,
    )?;
    let session = CheckMenuItem::with_id(
        app,
        "show-session",
        "Sitzungs-Browser einblenden",
        false,
        false,
        None::<&str>,
    )?;
    let pause = CheckMenuItem::with_id(app, "pause", "Angehalten", false, false, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Beenden", true, None::<&str>)?;

    let menu = Menu::with_items(
        app,
        &[
            &window_item,
            &PredefinedMenuItem::separator(app)?,
            &search,
            &session,
            &PredefinedMenuItem::separator(app)?,
            &pause,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;

    let items = Arc::new(Items {
        search,
        session,
        pause,
    });
    app.manage(items.clone());

    let handle = app.clone();
    TrayIconBuilder::with_id("main")
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip("Zahnputztracker")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(move |_app, event| on_menu(&handle, event, &items))
        .build(app)?;

    Ok(())
}

fn on_menu(app: &AppHandle, event: MenuEvent, items: &Items) {
    let supervisor = app.state::<Arc<Supervisor>>().inner().clone();
    match event.id().as_ref() {
        "ui" => {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
        "quit" => app.exit(0),
        "show-search" => toggle(&supervisor, items, SEARCH),
        "show-session" => toggle(&supervisor, items, SESSION),
        "pause" => {
            let wanted = fleet_state(&supervisor).map(|state| !state.paused).unwrap_or(true);
            let state = set_paused(&supervisor, wanted);
            let _ = items.pause.set_checked(state.map(|s| s.paused).unwrap_or(wanted));
        }
        _ => {}
    }
}

fn toggle(supervisor: &Supervisor, items: &Items, role: &str) {
    let wanted = fleet_state(supervisor)
        .map(|state| !state.visible(role))
        .unwrap_or(true);
    let state = set_visible(supervisor, role, wanted);
    let checked = state.map(|s| s.visible(role)).unwrap_or(wanted);
    let item = if role == SEARCH {
        &items.search
    } else {
        &items.session
    };
    let _ = item.set_checked(checked);
}

/// Keep the tick marks in step with the service, which the user
/// interface can change as well.
pub fn watch(app: AppHandle, supervisor: Arc<Supervisor>) {
    std::thread::spawn(move || loop {
        if let Some(state) = fleet_state(&supervisor) {
            if let Some(items) = app.try_state::<Arc<Items>>() {
                let _ = items.search.set_checked(state.visible(SEARCH));
                let _ = items.session.set_checked(state.visible(SESSION));
                let _ = items.pause.set_checked(state.paused);
                // Nothing to show and nothing to pause while the browsers
                // are not running.
                let _ = items.search.set_enabled(state.instance_running(SEARCH));
                let _ = items.session.set_enabled(state.instance_running(SESSION));
                let _ = items.pause.set_enabled(state.running);
            }
        }
        std::thread::sleep(Duration::from_secs(2));
    });
}
