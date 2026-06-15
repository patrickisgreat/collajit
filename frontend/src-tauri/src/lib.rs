//! Tauri shell for collajit.
//!
//! On launch it starts the Python backend (`collajit-server`) so the bundled web
//! UI has an API to talk to, and shuts it down on exit. For local runs it finds
//! the project's `.venv/bin/collajit-server` by walking up from the executable;
//! a bundled PyInstaller sidecar can replace that for distribution.

use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::Manager;

/// Holds the spawned backend process so we can kill it on exit.
struct Backend(Mutex<Option<Child>>);

/// Walk up from the executable looking for a directory that contains
/// `.venv/bin/collajit-server`. Works for `tauri dev` and a locally-built .app
/// (both live under the repo). Returns that repo root.
fn find_repo_root() -> Option<PathBuf> {
    let mut dir = std::env::current_exe().ok()?;
    while dir.pop() {
        if dir.join(".venv/bin/collajit-server").exists() {
            return Some(dir.clone());
        }
    }
    None
}

/// Kill any backend left over from a previous run (e.g. after a force-quit) so the
/// fresh one can bind port 8756 — otherwise the app talks to stale, outdated code.
fn kill_stale_backends() {
    #[cfg(unix)]
    {
        let _ = Command::new("pkill").args(["-f", "bin/collajit-server"]).status();
    }
}

fn spawn_backend() -> Option<Child> {
    kill_stale_backends();
    // 1) A bundled sidecar next to the executable (distribution).
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let sidecar = dir.join("collajit-server");
            if sidecar.exists() {
                return Command::new(sidecar).spawn().ok();
            }
        }
    }
    // 2) The project venv (local dev / locally-built app). cwd = repo root so the
    //    backend's .env (ANTHROPIC_API_KEY) is picked up.
    let root = find_repo_root()?;
    Command::new(root.join(".venv/bin/collajit-server"))
        .current_dir(&root)
        .spawn()
        .ok()
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            app.manage(Backend(Mutex::new(spawn_backend())));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app_handle.try_state::<Backend>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}
