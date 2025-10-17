use anyhow::Result;
use std::sync::Arc;
use tracing::{info, warn};

use crate::responder::{Responder, ResponderContext, ResponderResult};

/// Manages registration and routing of responders using Chain of Responsibility pattern
pub struct ResponderManager {
    responders: Vec<Arc<dyn Responder>>,
}

impl ResponderManager {
    /// Create a new empty responder manager
    pub fn new() -> Self {
        Self {
            responders: Vec::new(),
        }
    }

    /// Register a new responder
    /// Responders are automatically sorted by priority (highest first)
    pub fn register(&mut self, responder: Arc<dyn Responder>) {
        info!(
            "📝 Registering responder: {} (priority: {})",
            responder.name(),
            responder.priority()
        );
        self.responders.push(responder);

        // Sort by priority (highest first)
        self.responders
            .sort_by(|a, b| b.priority().cmp(&a.priority()));
    }

    /// Process a message through all registered responders
    /// Returns the response from the first responder that handles it, or None if no responder handles it
    pub async fn process_message(&self, context: &ResponderContext) -> Result<Option<String>> {
        info!(
            "📨 Processing message through {} responders",
            self.responders.len()
        );

        for responder in &self.responders {
            info!(
                "🔍 Checking responder: {} (priority: {})",
                responder.name(),
                responder.priority()
            );

            // Two-phase dispatch: check first, then handle
            if responder.should_handle(context).await {
                info!("✅ Responder '{}' will handle message", responder.name());

                match responder.handle(context).await? {
                    ResponderResult::Handled(response) => {
                        info!("✅ Message handled by responder: {}", responder.name());
                        return Ok(response);
                    }
                    ResponderResult::NotHandled => {
                        info!(
                            "⏭️  Responder '{}' returned NotHandled, trying next",
                            responder.name()
                        );
                        continue;
                    }
                }
            } else {
                info!("⏩ Responder '{}' declined to handle", responder.name());
            }
        }

        warn!("⚠️  No responder handled the message");
        Ok(None)
    }

    /// Get the number of registered responders
    pub fn count(&self) -> usize {
        self.responders.len()
    }

    /// List all registered responders with their priorities
    pub fn list_responders(&self) -> Vec<(String, i32)> {
        self.responders
            .iter()
            .map(|r| (r.name().to_string(), r.priority()))
            .collect()
    }
}

impl Default for ResponderManager {
    fn default() -> Self {
        Self::new()
    }
}
