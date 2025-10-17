use anyhow::Result;
use async_trait::async_trait;

use crate::responder::{Responder, ResponderContext, ResponderResult};

/// Simple ping-pong responder for health checks
pub struct PingPongResponder;

impl PingPongResponder {
    pub fn new() -> Self {
        Self
    }
}

#[async_trait]
impl Responder for PingPongResponder {
    fn name(&self) -> &str {
        "PingPongResponder"
    }

    fn priority(&self) -> i32 {
        100 // High priority for simple commands
    }

    async fn should_handle(&self, context: &ResponderContext) -> bool {
        let msg = context.message_body.trim().to_lowercase();
        msg == "ping" || msg == "!ping"
    }

    async fn handle(&self, _context: &ResponderContext) -> Result<ResponderResult> {
        Ok(ResponderResult::Handled(Some("Pong!".to_string())))
    }
}
