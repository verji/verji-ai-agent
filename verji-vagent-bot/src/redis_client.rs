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

/// Type of message from vagent-graph
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum GraphMessageType {
    /// Progress notification (streamed during execution)
    Progress,
    /// Final response (graph completed successfully)
    FinalResponse,
    /// Human-in-the-loop request (graph paused, needs user input)
    HitlRequest,
    /// Error occurred during processing
    Error,
}

/// Message received from vagent-graph (streaming or final)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphMessage {
    pub request_id: String,
    pub message_type: GraphMessageType,
    pub content: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub metadata: Option<serde_json::Value>,
}

/// Legacy response type for backward compatibility
#[derive(Debug, Serialize, Deserialize)]
pub struct GraphResponse {
    pub request_id: String,
    pub response: String,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl From<GraphMessage> for GraphResponse {
    fn from(msg: GraphMessage) -> Self {
        let status = match msg.message_type {
            GraphMessageType::Error => "error",
            _ => "success",
        };

        GraphResponse {
            request_id: msg.request_id,
            response: msg.content.clone(),
            status: status.to_string(),
            error: if msg.message_type == GraphMessageType::Error {
                Some(msg.content)
            } else {
                None
            },
        }
    }
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

    /// Send a query to vagent-graph with streaming support
    ///
    /// The on_progress callback is called for each progress notification
    /// Returns the final response content
    pub async fn query_with_streaming<F>(
        &mut self,
        query: String,
        room_id: String,
        user_id: String,
        on_progress: F,
    ) -> Result<String>
    where
        F: Fn(String) + Send + 'static,
    {
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

        // IMPORTANT: Subscribe BEFORE publishing to avoid race condition
        // Create pubsub connection and subscribe to response channel first
        let client = Client::open(self.redis_url.as_str())
            .context("Failed to create Redis client for pubsub")?;
        let mut pubsub = client.get_async_pubsub().await?;
        pubsub.subscribe(&self.response_channel).await?;
        debug!("Subscribed to response channel before publishing request");

        // Now serialize and publish request
        let request_json = serde_json::to_string(&request).context("Failed to serialize request")?;

        self.connection
            .publish::<_, _, ()>(&self.request_channel, &request_json)
            .await
            .context("Failed to publish request to Redis")?;

        debug!("Request {} published, waiting for response...", request_id);

        // Wait for final response, calling on_progress for intermediate messages
        let final_message = self
            .wait_for_final_response_with_pubsub(&request_id, pubsub, on_progress)
            .await
            .context("Failed to get response from vagent-graph")?;

        match final_message.message_type {
            GraphMessageType::Error => {
                warn!(
                    "vagent-graph returned error for request {}: {}",
                    request_id, final_message.content
                );
                Ok(format!("Error: {}", final_message.content))
            }
            GraphMessageType::FinalResponse | GraphMessageType::HitlRequest => {
                debug!("Received final response for request {}", request_id);
                Ok(final_message.content)
            }
            GraphMessageType::Progress => {
                // This shouldn't happen (progress should not be returned as final)
                warn!("Received progress message as final response");
                Ok(final_message.content)
            }
        }
    }

    /// Send a query to vagent-graph and wait for response (legacy method without streaming)
    pub async fn query(&mut self, query: String, room_id: String, user_id: String) -> Result<String> {
        // Use streaming method with no-op callback
        self.query_with_streaming(query, room_id, user_id, |_| {}).await
    }

    /// Wait for final response, calling on_progress for intermediate progress messages
    async fn wait_for_final_response_with_pubsub<F>(
        &mut self,
        request_id: &str,
        mut pubsub: redis::aio::PubSub,
        on_progress: F,
    ) -> Result<GraphMessage>
    where
        F: Fn(String) + Send + 'static,
    {
        // Pubsub connection already subscribed before calling this function

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
            debug!("Received Redis message: {}", payload);

            // Try to parse as GraphMessage first (new format)
            if let Ok(graph_msg) = serde_json::from_str::<GraphMessage>(&payload) {
                debug!("Parsed GraphMessage: type={:?}, request_id={}", graph_msg.message_type, graph_msg.request_id);
                if graph_msg.request_id == request_id {
                    debug!("Request ID matches! Type: {:?}", graph_msg.message_type);
                    match graph_msg.message_type {
                        GraphMessageType::Progress => {
                            // Call progress callback and continue waiting
                            info!("📊 Progress: {}", graph_msg.content);
                            on_progress(graph_msg.content);
                            continue;
                        }
                        GraphMessageType::FinalResponse
                        | GraphMessageType::HitlRequest
                        | GraphMessageType::Error => {
                            // This is the final message, return it
                            return Ok(graph_msg);
                        }
                    }
                }
                // Not our message, keep waiting
                continue;
            }

            // Fall back to legacy GraphResponse format for backward compatibility
            match serde_json::from_str::<GraphResponse>(&payload) {
                Ok(response) => {
                    if response.request_id == request_id {
                        // Convert legacy response to GraphMessage
                        let message_type = if response.status == "error" {
                            GraphMessageType::Error
                        } else {
                            GraphMessageType::FinalResponse
                        };

                        return Ok(GraphMessage {
                            request_id: response.request_id,
                            message_type,
                            content: response.response,
                            metadata: None,
                        });
                    }
                }
                Err(e) => {
                    warn!("Failed to parse response from Redis: {}", e);
                    continue;
                }
            }
        }
    }

}
