use anyhow::Result;
use matrix_sdk::Client;
use std::path::PathBuf;
use tracing::{info, warn};

/// Setup encryption keys (cross-signing and backups) with optional reset
pub async fn setup_encryption(
    client: &Client,
    store_path: &PathBuf,
    reset: bool,
    password: &str,
) -> Result<()> {
    let encryption = client.encryption();

    info!("🔐 Setting up encryption...");

    // If reset is requested, force new keys
    if reset {
        warn!("🔄 ⚠️  RESET MODE: Creating fresh encryption keys...");
        warn!("  ⚠️  This will override any existing keys on the server");
        warn!("  ⚠️  Existing encrypted messages may become unreadable");
        warn!("  ⚠️  Old recovery keys will no longer work");

        // Disable and delete existing recovery and backups
        info!("  Disabling existing recovery and backups...");

        match encryption.recovery().disable().await {
            Ok(_) => info!("  ✅ Recovery disabled successfully"),
            Err(e) => warn!("  ⚠️  Could not disable recovery: {}", e),
        }

        match encryption.backups().disable_and_delete().await {
            Ok(_) => info!("  ✅ Backup deleted from server"),
            Err(e) => warn!("  ⚠️  Could not delete backup: {}", e),
        }
    }

    // Check cross-signing status
    let cross_signing_status = encryption.cross_signing_status().await;

    match cross_signing_status {
        Some(status) => {
            info!("  Cross-signing status: {:?}", status);

            // If cross-signing is not fully set up, bootstrap it with UIAA
            if !status.has_master || !status.has_self_signing || !status.has_user_signing {
                info!("  Cross-signing not fully set up, bootstrapping with UIAA...");

                // First attempt: call with None to get UIAA challenge
                match encryption.bootstrap_cross_signing(None).await {
                    Ok(_) => {
                        info!("  ✅ Cross-signing bootstrapped without UIAA");
                    }
                    Err(e) => {
                        // Check if this is a UIAA error
                        if let Some(uiaa_info) = e.as_uiaa_response() {
                            info!("  Received UIAA challenge, providing password authentication...");

                            use matrix_sdk::ruma::api::client::uiaa;

                            let user_id = client
                                .user_id()
                                .ok_or_else(|| anyhow::anyhow!("No user_id available"))?;

                            let mut password_auth = uiaa::Password::new(
                                uiaa::UserIdentifier::UserIdOrLocalpart(user_id.to_string()),
                                password.to_string(),
                            );
                            password_auth.session = uiaa_info.session.clone();

                            match encryption
                                .bootstrap_cross_signing(Some(uiaa::AuthData::Password(
                                    password_auth,
                                )))
                                .await
                            {
                                Ok(_) => {
                                    info!("  ✅ Cross-signing bootstrapped with password auth");
                                }
                                Err(e2) => {
                                    warn!("  ⚠️  Failed to bootstrap cross-signing: {}", e2);
                                }
                            }
                        } else {
                            warn!("  ⚠️  Failed to bootstrap cross-signing: {}", e);
                        }
                    }
                }
            } else {
                info!("  ✅ Cross-signing is fully set up");
            }
        }
        None => {
            info!("  Cross-signing not available");
        }
    }

    // Setup key backups and recovery
    setup_recovery_and_backups(client, store_path, reset).await?;

    // Log final encryption status
    log_encryption_status(client, "setup complete").await;

    Ok(())
}

/// Setup recovery and backups
async fn setup_recovery_and_backups(
    client: &Client,
    store_path: &PathBuf,
    reset: bool,
) -> Result<()> {
    let encryption = client.encryption();
    let recovery = encryption.recovery();
    let state = recovery.state();

    info!("  Setting up key backups and recovery...");
    info!("  Recovery state: {:?}", state);

    // If reset mode or recovery is disabled, try to enable it
    if reset || state == matrix_sdk::encryption::recovery::RecoveryState::Disabled {
        if reset {
            info!("  Creating fresh backup with new recovery key...");
        } else {
            info!("  Checking for existing backup on server...");
        }

        // In reset mode, we deleted the backup above, so just create new one
        if reset {
            create_new_recovery(client, store_path).await?;
        } else {
            // Normal mode - check if backup exists
            match encryption.backups().exists_on_server().await {
                Ok(true) => {
                    info!("  📦 Backup already exists on server");
                    info!("  Note: Cannot create new recovery key when backup exists");
                    info!("  💡 Tip: Use --reset-encryption to delete and recreate");
                }
                Ok(false) => {
                    info!("  No existing backup found, creating new one...");
                    create_new_recovery(client, store_path).await?;
                }
                Err(e) => {
                    warn!("  ⚠️  Failed to check backup status: {}", e);
                }
            }
        }
    } else {
        info!("  ✅ Recovery already enabled");
    }

    Ok(())
}

/// Create new recovery key and enable backups
async fn create_new_recovery(client: &Client, store_path: &PathBuf) -> Result<()> {
    let recovery = client.encryption().recovery();

    match recovery.enable().await {
        Ok(recovery_key) => {
            info!("  ✅ Recovery and backups enabled successfully");

            // Save recovery key to file
            let recovery_key_path = store_path.join("recovery_key.txt");
            match std::fs::write(&recovery_key_path, &recovery_key) {
                Ok(_) => {
                    info!("  ✅ Recovery key saved to: {:?}", recovery_key_path);
                    info!("  🔑 Recovery key: {}", recovery_key);
                    info!("     ⚠️  IMPORTANT: Save this recovery key securely!");
                }
                Err(e) => {
                    warn!("  ⚠️  Failed to save recovery key to file: {}", e);
                    info!("  🔑 Recovery key: {}", recovery_key);
                    info!("     ⚠️  IMPORTANT: Save this recovery key securely!");
                }
            }
        }
        Err(e) => {
            warn!("  ⚠️  Failed to enable recovery: {}", e);
            info!("     This is non-fatal, encryption will still work");
        }
    }

    Ok(())
}

/// Setup only backups and recovery (assumes cross-signing is already set up)
pub async fn setup_backup_only(client: &Client, store_path: &PathBuf) -> Result<()> {
    setup_recovery_and_backups(client, store_path, false).await
}

/// Log encryption status
pub async fn log_encryption_status(client: &Client, label: &str) {
    info!("🔐 Encryption status {}:", label);
    let encryption = client.encryption();

    if let Some(status) = encryption.cross_signing_status().await {
        info!(
            "  Cross-signing: master={}, self={}, user={}",
            status.has_master, status.has_self_signing, status.has_user_signing
        );

        if !status.has_master || !status.has_self_signing || !status.has_user_signing {
            info!("  Note: Cross-signing handled automatically by SDK");
        } else {
            info!("  ✅ Cross-signing fully configured");
        }
    }

    match encryption.backups().state() {
        matrix_sdk::encryption::backups::BackupState::Enabled => {
            info!("  ✅ Backups are enabled");
        }
        state => {
            info!("  Backup state: {:?}", state);
        }
    }
}
