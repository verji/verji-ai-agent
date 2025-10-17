use anyhow::{Context, Result};
use matrix_sdk::{
    config::SyncSettings,
    ruma::events::room::message::{
        MessageType, OriginalSyncRoomMessageEvent, RoomMessageEventContent,
    },
    Client,
};
use tracing::{error, info};
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

    info!("Starting Verji vAgent Bot (POC - Echo Mode)");

    // Load environment variables from .env file
    dotenvy::dotenv().ok();

    // Get Matrix credentials from environment
    let homeserver = std::env::var("MATRIX_HOMESERVER")
        .context("MATRIX_HOMESERVER environment variable not set")?;
    let username = std::env::var("MATRIX_USER")
        .context("MATRIX_USER environment variable not set")?;
    let password = std::env::var("MATRIX_PASSWORD")
        .context("MATRIX_PASSWORD environment variable not set")?;

    info!("Connecting to homeserver: {}", homeserver);

    // Create Matrix client
    let client = Client::builder()
        .homeserver_url(&homeserver)
        .build()
        .await
        .context("Failed to create Matrix client")?;

    // Login
    info!("Logging in as: {}", username);
    client
        .matrix_auth()
        .login_username(&username, &password)
        .initial_device_display_name("Verji vAgent Bot")
        .await
        .context("Failed to login")?;

    info!("✓ Successfully logged in");

    // Register event handler for room messages
    client.add_event_handler(on_room_message);

    info!("Starting sync loop...");

    // Start syncing
    let sync_settings = SyncSettings::default();
    client
        .sync(sync_settings)
        .await
        .context("Sync loop failed")?;

    Ok(())
}

/// Event handler for room messages
async fn on_room_message(event: OriginalSyncRoomMessageEvent, room: matrix_sdk::Room) {
    // Get the sender's user ID
    let sender = &event.sender;

    // Get our own user ID
    let own_user_id = room.own_user_id();

    // Ignore messages from ourselves to prevent echo loops
    if sender == own_user_id {
        return;
    }

    // Extract message content
    let MessageType::Text(text_content) = &event.content.msgtype else {
        // Only handle text messages for this POC
        return;
    };

    let message_body = &text_content.body;
    let room_id = room.room_id();

    info!(
        room_id = %room_id,
        sender = %sender,
        message = %message_body,
        "Received message"
    );

    // Echo the message back
    let echo_content = RoomMessageEventContent::text_plain(format!(
        "Echo: {}",
        message_body
    ));

    match room.send(echo_content).await {
        Ok(_) => {
            info!(
                room_id = %room_id,
                "✓ Echoed message back to room"
            );
        }
        Err(e) => {
            error!(
                room_id = %room_id,
                error = %e,
                "✗ Failed to send echo message"
            );
        }
    }
}
