mod notices;
mod secrets;
mod supervisor;
mod tray;
mod windows;

use std::sync::Arc;

use supervisor::{Endpoint, Status, Supervisor};
use tauri::Manager;

/// Port and token of the running service, for the user interface.
#[tauri::command]
fn service_endpoint(state: tauri::State<Arc<Supervisor>>) -> Result<Endpoint, String> {
    state.endpoint().ok_or_else(|| "Dienst nicht verbunden".to_string())
}

#[tauri::command]
fn service_status(state: tauri::State<Arc<Supervisor>>) -> Status {
    state.status()
}

#[tauri::command]
fn service_restart(state: tauri::State<Arc<Supervisor>>) {
    supervisor::restart(&state);
}

/// How many windows of an instance are currently visible. Used by the
/// user interface to show that hiding really happened.
#[tauri::command]
fn browser_window_count(pids: Vec<u32>) -> usize {
    windows::visible_window_count(&pids)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            let supervisor = Arc::new(Supervisor::new());
            app.manage(supervisor.clone());
            supervisor::launch(app.handle().clone());
            tray::install(app.handle())?;
            tray::watch(app.handle().clone(), supervisor.clone());
            notices::watch(app.handle().clone(), supervisor.clone());
            windows::enforce(supervisor);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            service_endpoint,
            service_status,
            service_restart,
            browser_window_count
        ])
        .run(tauri::generate_context!())
        .expect("Anwendung konnte nicht gestartet werden");
}
