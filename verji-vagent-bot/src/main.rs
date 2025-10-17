use anyhow::{Context, Result};
use matrix_sdk::{
    config::SyncSettings,
    encryption::EncryptionSettings,
    ruma::events::room::message::{MessageType, RoomMessageEventContent, OriginalSyncRoomMessageEvent},
    Client, EncryptionState, Room,
};
use std::path::PathBuf;
use tracing::{debug, error, info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize logging
    tracing_subscriber::registry()
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| {
            "verji_vagent_bot=info,matrix_sdk=warn".into()
        }))
        .with(tracing_subscriber::fmt::layer())
        .init();

    info!("🤖 Starting Verji vAgent Bot (POC - Echo Mode with E2EE)");
    info!("Version: {}", env!("CARGO_PKG_VERSION"));

    // Load environment variables from .env file
    dotenvy::dotenv().ok();
    debug!("Environment variables loaded");

    // Get Matrix credentials from environment
    let homeserver = std::env::var("MATRIX_HOMESERVER")
        .context("MATRIX_HOMESERVER environment variable not set")?;
    let username = std::env::var("MATRIX_USER")
        .context("MATRIX_USER environment variable not set")?;
    let password = std::env::var("MATRIX_PASSWORD")
        .context("MATRIX_PASSWORD environment variable not set")?;

    // Get optional store path for session persistence
    let store_path = std::env::var("MATRIX_STORE_PATH")
        .unwrap_or_else(|_| "./matrix_store".to_string());

    info!("Configuration:");
    info!("  Homeserver: {}", homeserver);
    info!("  Username: {}", username);
    info!("  Store path: {}", store_path);

    // Create store path if it doesn't exist
    let store_path_buf = PathBuf::from(&store_path);
    if !store_path_buf.exists() {
        info!("Creating store directory: {}", store_path);
        std::fs::create_dir_all(&store_path_buf)
            .context("Failed to create store directory")?;
    }

    info!("🔌 Connecting to homeserver: {}", homeserver);

    // Create Matrix client with session persistence and encryption
    let client = Client::builder()
        .homeserver_url(&homeserver)
        .sqlite_store(&store_path_buf, None)
        .with_encryption_settings(EncryptionSettings {
            auto_enable_cross_signing: true,
            backup_download_strategy: matrix_sdk::encryption::BackupDownloadStrategy::AfterDecryptionFailure,
            auto_enable_backups: true,
        })
        .build()
        .await
        .context("Failed to create Matrix client")?;

    debug!("Matrix client created successfully");

    // Check if we have a valid session already
    let needs_login = client.user_id().is_none();

    if !needs_login {
        info!("✓ Restored session from store");
        let user_id = client.user_id().context("User ID not found")?;
        if let Some(device_id) = client.device_id() {
            info!("  User ID: {}", user_id);
            info!("  Device ID: {}", device_id);
        }
    } else {
        // Login with credentials
        info!("🔐 Logging in as: {}", username);
        client
            .matrix_auth()
            .login_username(&username, &password)
            .initial_device_display_name("Verji vAgent Bot")
            .await
            .context("Failed to login")?;

        info!("✓ Successfully logged in");
        let user_id = client.user_id().context("User ID not found")?;
        if let Some(device_id) = client.device_id() {
            info!("  User ID: {}", user_id);
            info!("  Device ID: {}", device_id);
            info!("  Session persisted to: {}", store_path);
        }
    }

    // Check encryption status
    let encryption = client.encryption();
    info!("🔐 Encryption status:");
    if let Some(status) = encryption.cross_signing_status().await {
        info!("  Cross-signing status: {:?}", status);
    } else {
        info!("  Cross-signing: not available");
    }
    info!("  Backups enabled: auto (when keys available)");

    // Register event handler for room messages
    client.add_event_handler(
        |event: OriginalSyncRoomMessageEvent, room: Room| async move {
            on_room_message(event, room).await;
        },
    );

    info!("📨 Event handlers registered");
    info!("🔄 Starting sync loop...");
    info!("Bot is now running and ready to echo messages");

    // Start syncing with full state to ensure we get room encryption info
    let sync_settings = SyncSettings::default().full_state(true);

    match client.sync(sync_settings).await {
        Ok(_) => {
            info!("Sync completed normally");
            Ok(())
        }
        Err(e) => {
            error!("Sync loop failed: {}", e);
            Err(e).context("Sync loop failed")
        }
    }
}

/// Event handler for room messages
async fn on_room_message(event: OriginalSyncRoomMessageEvent, room: Room) {
    let room_id = room.room_id();
    let sender = &event.sender;
    let content = &event.content;
    let own_user_id = room.own_user_id();

    // Log room information
    let room_name = room.display_name().await.ok();
    debug!(
        room_id = %room_id,
        room_name = ?room_name,
        "Processing message event"
    );

    // Check if room is encrypted (matrix-sdk 0.14+ uses EncryptionState enum)
    let encryption_state = room.encryption_state();
    let is_encrypted = matches!(encryption_state, EncryptionState::Encrypted);
    debug!(
        room_id = %room_id,
        encryption_state = ?encryption_state,
        is_encrypted = is_encrypted,
        "Room encryption status"
    );

    // Ignore messages from ourselves to prevent echo loops
    if sender == own_user_id {
        debug!(
            room_id = %room_id,
            "Ignoring message from self"
        );
        return;
    }

    // Extract message content
    let MessageType::Text(text_content) = &content.msgtype else {
        debug!(
            room_id = %room_id,
            message_type = ?content.msgtype,
            "Ignoring non-text message"
        );
        return;
    };

    let message_body = &text_content.body;

    info!(
        room_id = %room_id,
        sender = %sender,
        is_encrypted = is_encrypted,
        message_len = message_body.len(),
        "📥 Received message: {}",
        message_body
    );

    // Echo the message back
    let echo_content = RoomMessageEventContent::text_plain(format!(
        "Echo: {}",
        message_body
    ));

    debug!(
        room_id = %room_id,
        is_encrypted = is_encrypted,
        "Sending echo response"
    );

    match room.send(echo_content).await {
        Ok(_response) => {
            info!(
                room_id = %room_id,
                is_encrypted = is_encrypted,
                "✅ Successfully sent echo to room"
            );
        }
        Err(e) => {
            error!(
                room_id = %room_id,
                error = %e,
                error_debug = ?e,
                is_encrypted = is_encrypted,
                "❌ Failed to send echo message"
            );

            // Log additional context for encryption errors
            if is_encrypted {
                warn!(
                    room_id = %room_id,
                    "Failed to send to encrypted room - may need key verification"
                );
            }
        }
    }
}
