mod notices;
mod secrets;
mod supervisor;
mod tray;
mod update;
mod windows;

use std::sync::Arc;

use supervisor::{Endpoint, Status, Supervisor};
use tauri::{AppHandle, Manager};

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

/// State of the update button (specification 13.4).
#[tauri::command]
fn update_state(state: tauri::State<Arc<update::Updates>>) -> update::State {
    state.read()
}

/// A forced check. Runs in its own thread: the window stays usable.
#[tauri::command]
fn update_check(app: AppHandle) {
    std::thread::spawn(move || update::check(&app, true));
}

/// What is running right now, so the user interface can ask before it
/// closes anything.
#[tauri::command]
async fn update_situation(state: tauri::State<'_, Arc<Supervisor>>) -> Result<update::Situation, String> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || update::situation(&supervisor))
        .await
        .map_err(|error| error.to_string())
}

/// Download and install, after the user asked for it and confirmed.
#[tauri::command]
fn update_install(app: AppHandle) {
    std::thread::spawn(move || {
        let _ = update::install(&app);
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            let supervisor = Arc::new(Supervisor::new());
            app.manage(supervisor.clone());
            app.manage(Arc::new(update::Updates::new()));
            supervisor::launch(app.handle().clone());
            tray::install(app.handle())?;
            tray::watch(app.handle().clone(), supervisor.clone());
            notices::watch(app.handle().clone(), supervisor.clone());
            update::watch(app.handle().clone());
            windows::enforce(supervisor);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            service_endpoint,
            service_status,
            service_restart,
            browser_window_count,
            update_state,
            update_check,
            update_situation,
            update_install
        ])
        .run(tauri::generate_context!())
        .expect("Anwendung konnte nicht gestartet werden");
}
