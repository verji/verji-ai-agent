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

    async def process_query(self, query: str, metadata: Dict[str, Any]) -> str:
        """
        Process a query from vagent-bot.

        For now, this is an echo POC. Later, this will invoke LangGraph.

        Args:
            query: The user's query text
            metadata: Additional metadata (room_id, user_id, etc.)

        Returns:
            The response text
        """
        logger.info(f"Processing query: {query}")
        logger.info(f"Metadata: {metadata}")

        # Echo POC: Just return the query with a prefix
        response = f"[Echo POC] You said: {query}"

        return response

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

            # Process the query (echo POC for now)
            response_text = await self.process_query(query, metadata)

            # Publish response back to vagent-bot
            response_message = {
                "request_id": request_id,
                "response": response_text,
                "status": "success",
            }

            await self.redis_client.publish(
                self.response_channel,
                json.dumps(response_message),
            )

            logger.info(f"Published response for request {request_id}")

        except Exception as e:
            logger.error(f"Error handling request: {e}", exc_info=True)
            # Publish error response
            if self.redis_client and message_data.get("request_id"):
                error_message = {
                    "request_id": message_data["request_id"],
                    "response": "Error processing your request",
                    "status": "error",
                    "error": str(e),
                }
                await self.redis_client.publish(
                    self.response_channel,
                    json.dumps(error_message),
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
