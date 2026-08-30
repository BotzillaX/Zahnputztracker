mod secrets;
mod supervisor;

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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            app.manage(Arc::new(Supervisor::new()));
            supervisor::launch(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            service_endpoint,
            service_status,
            service_restart
        ])
        .run(tauri::generate_context!())
        .expect("Anwendung konnte nicht gestartet werden");
}
