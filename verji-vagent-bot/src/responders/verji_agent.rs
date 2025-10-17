use anyhow::Result;
use async_trait::async_trait;
use tracing::info;

use crate::responder::{Responder, ResponderContext, ResponderResult};

/// Verji AI Agent responder backed by LangGraph
/// This is the default responder (no prefix/codeword required)
pub struct VerjiAgentResponder {
    // TODO: Add LangGraph client here
}

impl VerjiAgentResponder {
    pub fn new() -> Self {
        Self {}
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

        // TODO: Integrate with LangGraph
        // For now, return a placeholder response
        let response = format!(
            "Verji AI Agent (LangGraph integration coming soon)\nYou said: {}",
            context.message_body
        );

        Ok(ResponderResult::Handled(Some(response)))
    }
}
