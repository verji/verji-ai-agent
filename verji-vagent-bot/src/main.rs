use anyhow::{Context, Result};
use clap::Parser;
use matrix_sdk::{
    config::SyncSettings,
    room::Room as MatrixRoom,
    ruma::events::room::message::{MessageType, OriginalSyncRoomMessageEvent, RoomMessageEventContent},
    Client,
};
use std::{path::PathBuf, sync::Arc};
use tokio::sync::RwLock;
use tracing::{error, info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

mod client;
mod encryption;
mod responder;
mod responder_manager;
mod responders;
mod session;

use responder::ResponderContext;
use responder_manager::ResponderManager;
use responders::{PingPongResponder, VerjiAgentResponder};

#[derive(Parser, Debug)]
#[command(name = "verji-vagent-bot")]
#[command(about = "Verji vAgent Bot - Matrix bot with pluggable responders and E2EE support", long_about = None)]
struct Args {
    /// Clear the store directory before starting
    #[arg(long)]
    clear_store: bool,

    /// Reset all encryption (DESTRUCTIVE: creates fresh keys, old encrypted messages may be lost)
    #[arg(long)]
    reset_encryption: bool,
}

#[tokio::main]
async fn main() -> Result<()> {
    // Parse command-line arguments
    let args = Args::parse();

    // Initialize logging
    tracing_subscriber::registry()
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| {
            "verji_vagent_bot=info,matrix_sdk=warn".into()
        }))
        .with(tracing_subscriber::fmt::layer())
        .init();

    info!("🤖 Starting Verji vAgent Bot with Pluggable Responder Pattern");
    info!("Version: {}", env!("CARGO_PKG_VERSION"));

    // Show warning if reset_encryption is enabled
    if args.reset_encryption {
        warn!("⚠️  ⚠️  ⚠️  DESTRUCTIVE MODE: --reset-encryption enabled ⚠️  ⚠️  ⚠️");
        warn!("This will create FRESH encryption keys!");
        warn!("Old encrypted messages may become UNREADABLE!");
        warn!("Waiting 3 seconds... Press Ctrl+C to abort.");
        std::thread::sleep(std::time::Duration::from_secs(3));
        warn!("Proceeding with encryption reset...");
    }

    // Load environment variables
    dotenvy::dotenv().ok();

    // Get Matrix credentials from environment
    let homeserver = std::env::var("MATRIX_HOMESERVER")
        .context("MATRIX_HOMESERVER environment variable not set")?;
    let username = std::env::var("MATRIX_USER")
        .context("MATRIX_USER environment variable not set")?;
    let password = std::env::var("MATRIX_PASSWORD")
        .context("MATRIX_PASSWORD environment variable not set")?;
    let store_path = std::env::var("MATRIX_STORE_PATH")
        .unwrap_or_else(|_| "./matrix_store".to_string());
    let store_passphrase = password.clone();

    info!("Configuration:");
    info!("  Homeserver: {}", homeserver);
    info!("  Username: {}", username);
    info!("  Store path: {}", store_path);

    let store_path_buf = PathBuf::from(&store_path);

    // Clear store if requested
    if args.clear_store {
        client::clear_store(&store_path_buf).await?;
    }

    // Create store directory if needed
    if !store_path_buf.exists() {
        info!("Creating store directory: {}", store_path);
        std::fs::create_dir_all(&store_path_buf)
            .context("Failed to create store directory")?;
    }

    info!("🔌 Connecting to homeserver: {}", homeserver);

    // Session file path
    let session_file = store_path_buf.join("session.json");

    // Try to restore session or login fresh
    let (client, session_source) = if session_file.exists() && !args.clear_store {
        client::restore_or_login(
            &session_file,
            &homeserver,
            &username,
            &password,
            &store_path_buf,
            &store_passphrase,
        )
        .await?
    } else {
        client::fresh_login(
            &homeserver,
            &username,
            &password,
            &store_path,
            &store_path_buf,
            &store_passphrase,
            &session_file,
        )
        .await?
    };

    info!("📊 Session Status:");
    info!("  Source: {}", session_source);
    if let Some(user_id) = client.user_id() {
        info!("  User ID: {}", user_id);
    }
    if let Some(device_id) = client.device_id() {
        info!("  Device ID: {}", device_id);
    }

    // Setup/reset encryption if explicitly requested
    if args.reset_encryption {
        info!("🔐 Resetting encryption as requested");
        encryption::setup_encryption(&client, &store_path_buf, true, &password).await?;

        // Perform initial sync after encryption reset to stabilize SDK state
        info!("🔄 Performing initial sync after encryption reset...");
        let initial_sync_settings = SyncSettings::default()
            .timeout(std::time::Duration::from_secs(30));

        match client.sync_once(initial_sync_settings).await {
            Ok(_) => {
                info!("✅ Initial sync after reset completed");
                encryption::log_encryption_status(&client, "after reset sync").await;
            }
            Err(e) => {
                warn!("⚠️  Initial sync after reset failed: {}", e);
            }
        }
    } else {
        encryption::log_encryption_status(&client, "before sync").await;
    }

    // Initialize responder manager
    let responder_manager = Arc::new(RwLock::new(ResponderManager::new()));

    // Register responders (priority order: PingPong=100, VerjiAgent=10)
    info!("📝 Registering responders...");
    {
        let mut manager = responder_manager.write().await;
        manager.register(Arc::new(PingPongResponder::new()));
        manager.register(Arc::new(VerjiAgentResponder::new()));
    }

    info!(
        "✅ Registered {} responders",
        responder_manager.read().await.count()
    );

    // Register event handler with responder manager
    let responder_manager_clone = Arc::clone(&responder_manager);
    let client_clone = client.clone();

    client.add_event_handler(
        move |event: OriginalSyncRoomMessageEvent, room: MatrixRoom| {
            let responder_manager = Arc::clone(&responder_manager_clone);
            let client = client_clone.clone();

            async move {
                if let Err(e) = handle_message(event, room, responder_manager, client).await {
                    error!("Error handling message: {}", e);
                }
            }
        },
    );

    info!("📨 Event handlers registered");

    // Perform initial sync for new logins to set up encryption
    if session_source == "new_login" {
        info!("🔄 Performing initial sync for new login...");
        let initial_sync_settings = SyncSettings::default()
            .timeout(std::time::Duration::from_secs(10));

        match client.sync_once(initial_sync_settings).await {
            Ok(_) => {
                info!("✅ Initial sync completed");
                encryption::log_encryption_status(&client, "after initial sync").await;

                // Setup backups for new login
                if let Err(e) = encryption::setup_backup_only(&client, &store_path_buf).await {
                    warn!("⚠️  Failed to set up backups: {}", e);
                }
            }
            Err(e) => {
                warn!("⚠️  Initial sync failed: {}", e);
            }
        }
    }

    info!("🔄 Starting main sync loop...");
    info!("Bot is now running and ready to respond");

    // Start continuous syncing
    let sync_settings = SyncSettings::default();

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

/// Handle incoming message by routing through responder manager
async fn handle_message(
    event: OriginalSyncRoomMessageEvent,
    room: MatrixRoom,
    responder_manager: Arc<RwLock<ResponderManager>>,
    client: Client,
) -> Result<()> {
    // Only handle text messages
    let MessageType::Text(text_content) = event.content.msgtype else {
        return Ok(());
    };

    let sender = event.sender.to_string();
    let message_body = text_content.body.clone();

    // Ignore bot's own messages
    if let Some(user_id) = client.user_id() {
        if sender == user_id.to_string() {
            return Ok(());
        }
    }

    // Detect if bot was mentioned
    let bot_user_id = client.user_id().map(|u| u.to_string()).unwrap_or_default();
    let is_direct_mention = message_body.contains(&bot_user_id)
        || message_body.to_lowercase().contains("vagent");

    info!("📨 Received message: {}", message_body);

    // Build context
    let manager = responder_manager.read().await;
    let registered_responders = manager.list_responders();

    let context = ResponderContext {
        client: client.clone(),
        room: room.clone(),
        sender,
        message_body,
        is_direct_mention,
        registered_responders,
    };

    // Process through responder manager
    if let Some(response) = manager.process_message(&context).await? {
        let content = RoomMessageEventContent::text_plain(&response);

        // Spawn the send operation in a separate task to avoid potential recursion issues
        // when encryption state has been reset
        let room_clone = room.clone();
        tokio::spawn(async move {
            match room_clone.send(content).await {
                Ok(_) => info!("✅ Sent response"),
                Err(e) => error!("Failed to send response: {}", e),
            }
        });
    }

    Ok(())
}
