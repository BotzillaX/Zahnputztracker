//! Windows Credential Manager access.
//!
//! Secrets never touch a file on disk. The service token is kept here so
//! that a restarted user interface can re-attach to a service that is
//! still running (spec section 4).

use keyring::Entry;

const SERVICE: &str = "Zahnputztracker";

fn entry(key: &str) -> Result<Entry, String> {
    Entry::new(SERVICE, key).map_err(|e| e.to_string())
}

pub fn get(key: &str) -> Option<String> {
    entry(key).ok()?.get_password().ok()
}

pub fn set(key: &str, value: &str) -> Result<(), String> {
    entry(key)?.set_password(value).map_err(|e| e.to_string())
}

#[allow(dead_code)]
pub fn delete(key: &str) -> Result<(), String> {
    match entry(key)?.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(e.to_string()),
    }
}
