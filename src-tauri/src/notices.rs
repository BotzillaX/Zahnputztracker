//! System notifications (specification 12.5).
//!
//! The service decides what is worth a notification and puts it in a
//! short queue. This module is the only thing that turns such a message
//! into something Windows shows, and it decides nothing of its own.
//!
//! It asks for everything after the number it saw last, so a message is
//! never shown twice and none is lost while the queue is not empty.

use std::sync::Arc;
use std::time::Duration;

use serde::Deserialize;
use tauri::AppHandle;
use tauri_plugin_notification::NotificationExt;

use crate::supervisor::Supervisor;

const EVERY: Duration = Duration::from_secs(2);

#[derive(Deserialize, Default)]
struct Message {
    #[serde(default)]
    number: u64,
    #[serde(default)]
    title: String,
    #[serde(default)]
    text: String,
    /// False when the user switched notifications off. The message is
    /// still in the queue, because the window shows it either way.
    #[serde(default)]
    wanted: bool,
}

#[derive(Deserialize, Default)]
struct Queue {
    #[serde(default)]
    number: u64,
    #[serde(default)]
    messages: Vec<Message>,
}

fn fetch(supervisor: &Supervisor, after: u64) -> Option<Queue> {
    let endpoint = supervisor.endpoint()?;
    ureq::get(&format!(
        "http://127.0.0.1:{}/notifications?after={after}",
        endpoint.port
    ))
    .set("X-Auth-Token", &endpoint.token)
    .timeout(Duration::from_secs(3))
    .call()
    .ok()?
    .into_json()
    .ok()
}

fn show(app: &AppHandle, message: &Message) {
    let body = if message.text.is_empty() {
        message.title.clone()
    } else {
        message.text.clone()
    };
    let _ = app
        .notification()
        .builder()
        .title(&message.title)
        .body(&body)
        .show();
}

/// Watch the queue for as long as the application runs.
pub fn watch(app: AppHandle, supervisor: Arc<Supervisor>) {
    std::thread::spawn(move || {
        // Whatever happened before this run started is history: on the
        // first answer only the current number is taken over, so a
        // restart does not replay old messages.
        let mut seen: Option<u64> = None;
        loop {
            if let Some(queue) = fetch(&supervisor, seen.unwrap_or(0)) {
                match seen {
                    // The service was restarted and counts from the
                    // beginning again. Follow it, or nothing would ever
                    // be shown again.
                    Some(last) if queue.number < last => seen = Some(queue.number),
                    None => seen = Some(queue.number),
                    Some(_) => {
                        for message in &queue.messages {
                            if message.wanted {
                                show(&app, message);
                            }
                            seen = Some(message.number);
                        }
                    }
                }
            }
            std::thread::sleep(EVERY);
        }
    });
}
