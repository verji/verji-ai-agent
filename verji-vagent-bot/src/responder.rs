use anyhow::Result;
use async_trait::async_trait;
use matrix_sdk::{room::Room, Client};

/// Context provided to responders for handling messages
#[derive(Clone)]
pub struct ResponderContext {
    /// Matrix SDK client
    pub client: Client,
    /// The room where the message was received
    pub room: Room,
    /// User ID of the message sender
    pub sender: String,
    /// The actual message text
    pub message_body: String,
    /// Whether the bot was directly mentioned
    pub is_direct_mention: bool,
    /// List of all registered responders (name, priority)
    pub registered_responders: Vec<(String, i32)>,
}

/// Response from a responder
pub enum ResponderResult {
    /// Message was handled, optionally with a reply
    Handled(Option<String>),
    /// Message was not handled, pass to next responder
    NotHandled,
}

/// Core trait that all responders must implement
#[async_trait]
pub trait Responder: Send + Sync {
    /// Returns the name of this responder
    fn name(&self) -> &str;

    /// Returns the priority of this responder (higher = checked first)
    /// Default priority is 0
    fn priority(&self) -> i32 {
        0
    }

    /// Check if this responder should handle the message
    /// This is called first as a fast filter before handle()
    async fn should_handle(&self, context: &ResponderContext) -> bool;

    /// Handle the message and return a response
    /// Only called if should_handle() returns true
    async fn handle(&self, context: &ResponderContext) -> Result<ResponderResult>;
}
