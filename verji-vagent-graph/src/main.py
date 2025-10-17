"""
Verji vAgent Graph Service - Echo POC

This service listens for queries from vagent-bot via Redis and echoes them back.
In the future, this will be replaced with actual LangGraph-based AI processing.
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict

import redis.asyncio as redis

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class VAgentGraph:
    """Main service class for the vAgent Graph service."""

    def __init__(self):
        """Initialize the service."""
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        self.request_channel = "vagent:requests"
        self.response_channel = "vagent:responses"
        self.redis_client: redis.Redis | None = None
        self.pubsub: redis.client.PubSub | None = None

    async def connect(self):
        """Connect to Redis."""
        logger.info(f"Connecting to Redis at {self.redis_url}")
        self.redis_client = await redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        self.pubsub = self.redis_client.pubsub()
        await self.pubsub.subscribe(self.request_channel)
        logger.info(f"Subscribed to channel: {self.request_channel}")

    async def disconnect(self):
        """Disconnect from Redis."""
        if self.pubsub:
            await self.pubsub.unsubscribe(self.request_channel)
            await self.pubsub.close()
        if self.redis_client:
            await self.redis_client.close()
        logger.info("Disconnected from Redis")

    async def emit_progress(self, request_id: str, content: str) -> None:
        """
        Emit a progress notification for streaming updates.

        Args:
            request_id: The request ID to associate with this progress update
            content: The progress message content
        """
        message = {
            "request_id": request_id,
            "message_type": "progress",
            "content": content,
        }
        await self.redis_client.publish(
            self.response_channel,
            json.dumps(message),
        )
        logger.debug(f"Emitted progress for request {request_id}: {content}")

    async def emit_final_response(self, request_id: str, content: str) -> None:
        """
        Emit the final response.

        Args:
            request_id: The request ID to associate with this response
            content: The final response content
        """
        message = {
            "request_id": request_id,
            "message_type": "final_response",
            "content": content,
        }
        await self.redis_client.publish(
            self.response_channel,
            json.dumps(message),
        )
        logger.info(f"Emitted final response for request {request_id}")

    async def emit_error(self, request_id: str, error_message: str) -> None:
        """
        Emit an error response.

        Args:
            request_id: The request ID to associate with this error
            error_message: The error message
        """
        message = {
            "request_id": request_id,
            "message_type": "error",
            "content": error_message,
        }
        await self.redis_client.publish(
            self.response_channel,
            json.dumps(message),
        )
        logger.error(f"Emitted error for request {request_id}: {error_message}")

    async def process_query(self, request_id: str, query: str, metadata: Dict[str, Any]) -> None:
        """
        Process a query from vagent-bot with streaming support.

        This demonstrates progress streaming. In production, this will invoke LangGraph.

        Args:
            request_id: The request ID for correlation
            query: The user's query text
            metadata: Additional metadata (room_id, user_id, etc.)
        """
        logger.info(f"Processing query: {query}")
        logger.info(f"Metadata: {metadata}")

        try:
            # Simulate multi-step processing with progress updates
            await self.emit_progress(request_id, "🔍 Analyzing your question...")
            await asyncio.sleep(0.5)  # Simulate work

            await self.emit_progress(request_id, "🧠 Thinking about the best response...")
            await asyncio.sleep(0.5)  # Simulate work

            await self.emit_progress(request_id, "✍️ Formulating answer...")
            await asyncio.sleep(0.5)  # Simulate work

            # Echo POC: Return the query with a prefix
            response = f"[Echo POC with Streaming] You said: {query}"

            # Emit final response
            await self.emit_final_response(request_id, response)

        except Exception as e:
            logger.error(f"Error processing query: {e}", exc_info=True)
            await self.emit_error(request_id, f"Failed to process query: {str(e)}")

    async def handle_request(self, message_data: Dict[str, Any]):
        """
        Handle an incoming request from vagent-bot.

        Expected message format:
        {
            "request_id": "unique-id",
            "query": "user query text",
            "metadata": {
                "room_id": "!room:server",
                "user_id": "@user:server",
                "timestamp": 1234567890
            }
        }
        """
        try:
            request_id = message_data.get("request_id")
            query = message_data.get("query", "")
            metadata = message_data.get("metadata", {})

            if not request_id:
                logger.error("Missing request_id in message")
                return

            logger.info(f"Handling request {request_id}")

            # Process the query with streaming support
            await self.process_query(request_id, query, metadata)

        except Exception as e:
            logger.error(f"Error handling request: {e}", exc_info=True)
            # Emit error message
            if message_data.get("request_id"):
                await self.emit_error(
                    message_data["request_id"],
                    f"Error processing your request: {str(e)}"
                )

    async def run(self):
        """Main run loop - listen for requests and process them."""
        logger.info("🚀 vAgent Graph service starting...")

        try:
            await self.connect()

            logger.info("✅ Service ready - listening for requests")

            # Listen for messages
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        # Process each request in a background task
                        asyncio.create_task(self.handle_request(data))
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to decode message: {e}")
                    except Exception as e:
                        logger.error(f"Error processing message: {e}", exc_info=True)

        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            sys.exit(1)
        finally:
            await self.disconnect()
            logger.info("Service stopped")


async def main():
    """Entry point for the service."""
    service = VAgentGraph()
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())
