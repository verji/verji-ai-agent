use anyhow::Result;
use async_trait::async_trait;
use std::sync::Arc;
use tokio::sync::Mutex;
use tracing::{info, warn};

use crate::redis_client::RedisGraphClient;
use crate::responder::{Responder, ResponderContext, ResponderResult};

/// Verji AI Agent responder backed by LangGraph via Redis
/// This is the default responder (no prefix/codeword required)
pub struct VerjiAgentResponder {
    redis_client: Arc<Mutex<Option<RedisGraphClient>>>,
    redis_url: String,
}

impl VerjiAgentResponder {
    pub fn new() -> Self {
        let redis_url = std::env::var("REDIS_URL").unwrap_or_else(|_| "redis://localhost:6379".to_string());

        Self {
            redis_client: Arc::new(Mutex::new(None)),
            redis_url,
        }
    }

    /// Ensure Redis client is connected (lazy initialization)
    async fn ensure_connected(&self) -> Result<()> {
        let mut client_guard = self.redis_client.lock().await;

        if client_guard.is_none() {
            info!("Initializing Redis connection to vagent-graph");
            match RedisGraphClient::new(&self.redis_url).await {
                Ok(client) => {
                    *client_guard = Some(client);
                    info!("✅ Connected to vagent-graph via Redis");
                }
                Err(e) => {
                    warn!("Failed to connect to Redis: {}", e);
                    return Err(e);
                }
            }
        }

        Ok(())
    }
}

#[async_trait]
impl Responder for VerjiAgentResponder {
    fn name(&self) -> &str {
        "VerjiAgentResponder"
    }

    fn priority(&self) -> i32 {
        // Low priority - this is the default fallback responder
        10
    }

    async fn should_handle(&self, _context: &ResponderContext) -> bool {
        // Handle everything that reaches this point (default responder)
        true
    }

    async fn handle(&self, context: &ResponderContext) -> Result<ResponderResult> {
        info!(
            "🤖 VerjiAgent handling message: {}",
            context.message_body
        );

        // Try to connect to Redis if not connected
        if let Err(e) = self.ensure_connected().await {
            warn!("Redis unavailable, falling back to local echo: {}", e);
            let response = format!(
                "[Offline Mode - Redis unavailable]\nYou said: {}",
                context.message_body
            );
            return Ok(ResponderResult::Handled(Some(response)));
        }

        // Send query to vagent-graph via Redis with streaming support
        let mut client_guard = self.redis_client.lock().await;
        let client = client_guard.as_mut().expect("Redis client should be initialized");

        // Define progress callback
        // TODO: In the future, send these as typing indicators or message edits to Matrix
        let on_progress = |progress_msg: String| {
            info!("📊 Progress update: {}", progress_msg);
            // Future: context.room.typing_notice(true).await
            // Future: Or send/edit a message in the room
        };

        match client
            .query_with_streaming(
                context.message_body.clone(),
                context.room.room_id().to_string(),
                context.sender.clone(),
                on_progress,
            )
            .await
        {
            Ok(response) => {
                info!("✅ Received final response from vagent-graph");
                Ok(ResponderResult::Handled(Some(response)))
            }
            Err(e) => {
                warn!("Error querying vagent-graph: {}", e);
                let fallback = format!(
                    "[Error communicating with AI service]\nYou said: {}",
                    context.message_body
                );
                Ok(ResponderResult::Handled(Some(fallback)))
            }
        }
    }
}
