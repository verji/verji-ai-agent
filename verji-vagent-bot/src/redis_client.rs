use anyhow::{Context, Result};
use futures::StreamExt;
use redis::aio::ConnectionManager;
use redis::{AsyncCommands, Client};
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tracing::{debug, info, warn};
use uuid::Uuid;

/// Message sent to vagent-graph for processing
#[derive(Debug, Serialize, Deserialize)]
pub struct GraphRequest {
    pub request_id: String,
    pub query: String,
    pub metadata: RequestMetadata,
}

/// Metadata about the request
#[derive(Debug, Serialize, Deserialize)]
pub struct RequestMetadata {
    pub room_id: String,
    pub user_id: String,
    pub timestamp: u64,
}

/// Response received from vagent-graph
#[derive(Debug, Serialize, Deserialize)]
pub struct GraphResponse {
    pub request_id: String,
    pub response: String,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Redis client for communicating with vagent-graph
pub struct RedisGraphClient {
    connection: ConnectionManager,
    redis_url: String,
    request_channel: String,
    response_channel: String,
}

impl RedisGraphClient {
    /// Create a new Redis client
    pub async fn new(redis_url: &str) -> Result<Self> {
        info!("Connecting to Redis at {}", redis_url);

        let client = Client::open(redis_url).context("Failed to create Redis client")?;

        let connection = ConnectionManager::new(client)
            .await
            .context("Failed to create Redis connection manager")?;

        Ok(Self {
            connection,
            redis_url: redis_url.to_string(),
            request_channel: "vagent:requests".to_string(),
            response_channel: "vagent:responses".to_string(),
        })
    }

    /// Send a query to vagent-graph and wait for response
    pub async fn query(&mut self, query: String, room_id: String, user_id: String) -> Result<String> {
        let request_id = Uuid::new_v4().to_string();

        let request = GraphRequest {
            request_id: request_id.clone(),
            query: query.clone(),
            metadata: RequestMetadata {
                room_id,
                user_id,
                timestamp: std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_secs(),
            },
        };

        debug!("Sending request {} to vagent-graph", request_id);

        // Serialize and publish request
        let request_json = serde_json::to_string(&request).context("Failed to serialize request")?;

        self.connection
            .publish::<_, _, ()>(&self.request_channel, &request_json)
            .await
            .context("Failed to publish request to Redis")?;

        debug!("Request {} published, waiting for response...", request_id);

        // Subscribe to response channel and wait for our response
        let response = self
            .wait_for_response(&request_id)
            .await
            .context("Failed to get response from vagent-graph")?;

        if response.status == "error" {
            warn!(
                "vagent-graph returned error for request {}: {:?}",
                request_id, response.error
            );
            return Ok(format!("Error: {}", response.error.unwrap_or_else(|| "Unknown error".to_string())));
        }

        debug!("Received response for request {}", request_id);
        Ok(response.response)
    }

    /// Wait for a response with the given request_id
    async fn wait_for_response(&mut self, request_id: &str) -> Result<GraphResponse> {
        // Create a new pubsub connection for listening
        let client = Client::open(self.redis_url.as_str())
            .context("Failed to create Redis client for pubsub")?;
        let mut pubsub = client.get_async_pubsub().await?;

        pubsub.subscribe(&self.response_channel).await?;

        let timeout_duration = Duration::from_secs(30);
        let start_time = std::time::Instant::now();

        // Listen for messages
        let mut pubsub_stream = pubsub.on_message();

        loop {
            if start_time.elapsed() > timeout_duration {
                anyhow::bail!("Timeout waiting for response from vagent-graph");
            }

            // Use tokio::time::timeout to add timeout to the next message
            let message = match tokio::time::timeout(Duration::from_secs(1), pubsub_stream.next()).await {
                Ok(Some(msg)) => msg,
                Ok(None) => {
                    anyhow::bail!("Pubsub stream ended unexpectedly");
                }
                Err(_) => {
                    // Timeout elapsed, continue loop to check overall timeout
                    continue;
                }
            };

            let payload: String = message.get_payload()?;

            match serde_json::from_str::<GraphResponse>(&payload) {
                Ok(response) => {
                    if response.request_id == request_id {
                        return Ok(response);
                    }
                    // Not our message, keep waiting
                }
                Err(e) => {
                    warn!("Failed to parse response from Redis: {}", e);
                    continue;
                }
            }
        }
    }
}
