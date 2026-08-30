//! Showing and hiding the browser windows.
//!
//! Specification 5.3: the windows run hidden, can be shown and hidden at
//! any time without restarting the browser or reloading the page, and a
//! window must never push itself into the foreground.
//!
//! The service owns the wanted state and reports it together with the
//! process ids of an instance. This module is the only place that
//! touches windows.
//!
//! A browser run owns several windows, most of them helper windows that
//! are never meant to be seen. Therefore: hide only what is currently
//! visible, and show again only what was hidden here.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use serde::Deserialize;
use windows_sys::Win32::Foundation::{BOOL, HWND, LPARAM};
use windows_sys::Win32::System::Threading::GetCurrentProcessId;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GetWindow, GetWindowTextLengthW, GetWindowThreadProcessId, IsWindow,
    IsWindowVisible, ShowWindow, GW_OWNER, SW_HIDE, SW_SHOWNOACTIVATE,
};

use crate::supervisor::Supervisor;

/// How often the wanted state is enforced. Short enough that a window
/// which starts visible is hidden again before it is in the way.
const POLL_INTERVAL: Duration = Duration::from_millis(250);

#[derive(Deserialize, Clone)]
pub struct WantedWindow {
    pub role: String,
    #[serde(default)]
    pub pids: Vec<u32>,
    pub visible: bool,
}

#[derive(Deserialize)]
struct WantedWindows {
    windows: Vec<WantedWindow>,
}

struct Collector {
    pid: u32,
    found: Vec<isize>,
}

unsafe extern "system" fn collect(handle: HWND, param: LPARAM) -> BOOL {
    let collector = &mut *(param as *mut Collector);
    let mut owner: u32 = 0;
    GetWindowThreadProcessId(handle, &mut owner);
    if owner != collector.pid {
        return 1;
    }
    // Only real top level windows: no owned popups, nothing without a
    // caption.
    if !GetWindow(handle, GW_OWNER).is_null() {
        return 1;
    }
    if GetWindowTextLengthW(handle) == 0 {
        return 1;
    }
    collector.found.push(handle as isize);
    1
}

fn windows_of(pid: u32) -> Vec<isize> {
    if pid == 0 || pid == unsafe { GetCurrentProcessId() } {
        return Vec::new();
    }
    let mut collector = Collector {
        pid,
        found: Vec::new(),
    };
    unsafe {
        EnumWindows(Some(collect), &mut collector as *mut Collector as LPARAM);
    }
    collector.found
}

fn windows_of_all(pids: &[u32]) -> Vec<isize> {
    pids.iter().flat_map(|pid| windows_of(*pid)).collect()
}

fn alive(handle: isize) -> bool {
    unsafe { IsWindow(handle as HWND) != 0 }
}

fn visible(handle: isize) -> bool {
    unsafe { IsWindowVisible(handle as HWND) != 0 }
}

/// Hide every window of this instance that is currently visible and
/// return the handles that were hidden.
fn hide(pids: &[u32]) -> Vec<isize> {
    let mut hidden = Vec::new();
    for handle in windows_of_all(pids) {
        if !alive(handle) || !visible(handle) {
            continue;
        }
        unsafe {
            ShowWindow(handle as HWND, SW_HIDE);
        }
        hidden.push(handle);
    }
    hidden
}

/// Show the windows that were hidden here. Never activates them, so the
/// user keeps working where they were.
fn show(handles: &[isize]) {
    for handle in handles {
        if !alive(*handle) {
            continue;
        }
        unsafe {
            ShowWindow(*handle as HWND, SW_SHOWNOACTIVATE);
        }
    }
}

/// Number of currently visible top level windows of these processes.
/// Used by the user interface to show that hiding really happened.
pub fn visible_window_count(pids: &[u32]) -> usize {
    windows_of_all(pids)
        .into_iter()
        .filter(|handle| alive(*handle) && visible(*handle))
        .count()
}

fn read_wanted(supervisor: &Supervisor) -> Option<Vec<WantedWindow>> {
    let endpoint = supervisor.endpoint()?;
    let url = format!("http://127.0.0.1:{}/browser/windows", endpoint.port);
    let response = ureq::get(&url)
        .set("X-Auth-Token", &endpoint.token)
        .timeout(Duration::from_secs(2))
        .call()
        .ok()?;
    let parsed: WantedWindows = response.into_json().ok()?;
    Some(parsed.windows)
}

/// Enforce the wanted state in the background for as long as the
/// application runs.
pub fn enforce(supervisor: Arc<Supervisor>) {
    std::thread::spawn(move || {
        // Per instance: the windows this module hid.
        let mut hidden: HashMap<String, Vec<isize>> = HashMap::new();
        loop {
            if let Some(wanted) = read_wanted(&supervisor) {
                let mut roles: Vec<String> = Vec::new();
                for entry in wanted {
                    roles.push(entry.role.clone());
                    if entry.visible {
                        if let Some(handles) = hidden.remove(&entry.role) {
                            show(&handles);
                        }
                    } else {
                        let mut store = hidden.remove(&entry.role).unwrap_or_default();
                        store.retain(|handle| alive(*handle));
                        store.extend(hide(&entry.pids));
                        store.sort_unstable();
                        store.dedup();
                        hidden.insert(entry.role, store);
                    }
                }
                hidden.retain(|role, _| roles.contains(role));
            }
            std::thread::sleep(POLL_INTERVAL);
        }
    });
}
