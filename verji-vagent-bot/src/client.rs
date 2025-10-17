use anyhow::{Context, Result};
use matrix_sdk::{encryption::EncryptionSettings, Client};
use std::path::PathBuf;
use tracing::{info, warn};

use crate::session;

/// Build a new Matrix client with encryption settings
pub async fn build_client(
    homeserver: &str,
    store_path: &PathBuf,
    store_passphrase: &str,
) -> Result<Client> {
    Client::builder()
        .homeserver_url(homeserver)
        .sqlite_store(store_path, Some(store_passphrase))
        .with_encryption_settings(EncryptionSettings {
            auto_enable_cross_signing: false,
            backup_download_strategy:
                matrix_sdk::encryption::BackupDownloadStrategy::AfterDecryptionFailure,
            auto_enable_backups: false,
        })
        .build()
        .await
        .context("Failed to create Matrix client")
}

/// Restore session from file or fallback to fresh login
pub async fn restore_or_login(
    session_file: &PathBuf,
    homeserver: &str,
    username: &str,
    password: &str,
    store_path_buf: &PathBuf,
    store_passphrase: &str,
) -> Result<(Client, &'static str)> {
    info!("📁 Found saved session file, attempting to restore...");

    match session::load_session(session_file).await {
        Ok(full_session) => {
            info!("  Session file loaded successfully");
            info!("  Homeserver: {}", full_session.client_session.homeserver);
            info!("  User ID: {}", full_session.user_session.meta.user_id);
            info!("  Device ID: {}", full_session.user_session.meta.device_id);

            // Build client with saved homeserver and store
            let client =
                build_client(&full_session.client_session.homeserver, store_path_buf, store_passphrase).await?;

            // Restore the session
            client
                .restore_session(full_session.user_session)
                .await
                .context("Failed to restore session")?;

            info!("✅ Session restored successfully");
            Ok((client, "restored"))
        }
        Err(e) => {
            warn!("⚠️  Failed to load session file: {}", e);
            warn!("   Will perform fresh login");

            let store_path = store_path_buf.to_str().unwrap().to_string();
            fresh_login(
                homeserver,
                username,
                password,
                &store_path,
                store_path_buf,
                store_passphrase,
                session_file,
            )
            .await
        }
    }
}

/// Perform fresh login and save session
pub async fn fresh_login(
    homeserver: &str,
    username: &str,
    password: &str,
    store_path: &str,
    store_path_buf: &PathBuf,
    store_passphrase: &str,
    session_file: &PathBuf,
) -> Result<(Client, &'static str)> {
    info!("📝 Performing fresh login");

    // Build new client
    let client = build_client(homeserver, store_path_buf, store_passphrase).await?;

    // Login
    info!("🔐 Logging in as: {}", username);
    client
        .matrix_auth()
        .login_username(username, password)
        .initial_device_display_name("Verji vAgent Bot")
        .await
        .context("Failed to login")?;

    info!("✅ Successfully logged in");
    if let Some(user_id) = client.user_id() {
        info!("  User ID: {}", user_id);
    }
    if let Some(device_id) = client.device_id() {
        info!("  Device ID: {}", device_id);
    }

    // Save the session
    session::save_client_session(&client, session_file, homeserver, store_path).await?;

    Ok((client, "new_login"))
}

/// Clear the store directory with retry logic for Windows
pub async fn clear_store(store_path: &PathBuf) -> Result<()> {
    if !store_path.exists() {
        info!("🗑️  Store directory doesn't exist, nothing to clear");
        return Ok(());
    }

    info!("🗑️  Clearing store directory: {:?}", store_path);

    // Retry logic for Windows file locking
    let mut retries = 3;
    loop {
        match std::fs::remove_dir_all(store_path) {
            Ok(_) => {
                info!("✅ Store directory cleared");
                break;
            }
            Err(e) if retries > 0 => {
                warn!("  ⚠️  Failed to clear store (retrying...): {}", e);
                retries -= 1;
                std::thread::sleep(std::time::Duration::from_millis(100));
            }
            Err(e) => {
                return Err(e).context("Failed to remove store directory after retries");
            }
        }
    }

    std::thread::sleep(std::time::Duration::from_millis(50));
    Ok(())
}
