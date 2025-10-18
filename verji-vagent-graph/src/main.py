"""
Verji vAgent Graph Service - LangGraph with OpenAI

This service listens for queries from vagent-bot via Redis and processes them
using a LangGraph workflow with OpenAI LLM.
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict

import redis.asyncio as redis
from dotenv import load_dotenv
from pathlib import Path
from langgraph.checkpoint.redis import AsyncRedisSaver

from graph import VerjiAgent
from types import GraphRequest

# Load environment variables from .env file in project root
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

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
        self.checkpoint_client: redis.Redis | None = None
        self.checkpointer: AsyncRedisSaver | None = None
        self.pubsub: redis.client.PubSub | None = None
        self.agent: VerjiAgent | None = None

    async def connect(self):
        """Connect to Redis and initialize LangGraph agent."""
        logger.info(f"Connecting to Redis at {self.redis_url}")

        # Redis client for pubsub (decode_responses=True)
        self.redis_client = await redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        self.pubsub = self.redis_client.pubsub()
        await self.pubsub.subscribe(self.request_channel)
        logger.info(f"Subscribed to channel: {self.request_channel}")

        # Redis client for checkpoints (decode_responses=True for AsyncRedisSaver)
        self.checkpoint_client = await redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

        # Initialize checkpointer (PLAINTEXT for Phase 1)
        logger.info("Initializing AsyncRedisSaver (plaintext checkpoints)...")
        self.checkpointer = AsyncRedisSaver(self.checkpoint_client)
        logger.info("✅ Checkpointer initialized (unencrypted)")

        # Initialize LangGraph agent with emit_progress callback and checkpointer
        logger.info("Initializing LangGraph agent with OpenAI...")
        self.agent = VerjiAgent(
            emit_progress_callback=self.emit_progress,
            checkpointer=self.checkpointer,
        )
        logger.info("LangGraph agent initialized")

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

    async def process_query(self, request: GraphRequest) -> None:
        """
        Process a query from vagent-bot using LangGraph with streaming progress.

        Args:
            request: The GraphRequest containing query, session_id, room_context, etc.
        """
        logger.info(f"Processing query: {request.query}")
        logger.info(f"Session ID: {request.session_id}")
        logger.info(f"Room context: {len(request.room_context)} messages")

        try:
            # Process through LangGraph agent (it will emit progress updates)
            response = await self.agent.process(
                request_id=request.request_id,
                session_id=request.session_id,
                query=request.query,
                room_context=request.room_context,
            )

            # Emit final response
            await self.emit_final_response(request.request_id, response)

        except Exception as e:
            logger.error(f"Error processing query: {e}", exc_info=True)
            await self.emit_error(request.request_id, f"Failed to process query: {str(e)}")

    async def handle_request(self, message_data: Dict[str, Any]):
        """
        Handle an incoming request from vagent-bot.

        Expected message format:
        {
            "request_id": "unique-id",
            "session_id": "!room:main:@user",
            "query": "user query text",
            "room_context": [
                {
                    "sender": "@alice:matrix.org",
                    "content": "message text",
                    "timestamp": 1234567890,
                    "is_bot": false
                },
                ...
            ],
            "metadata": {
                "room_id": "!room:server",
                "user_id": "@user:server",
                "timestamp": 1234567890
            }
        }
        """
        try:
            # Parse request from message data
            request = GraphRequest.from_dict(message_data)

            if not request.request_id:
                logger.error("Missing request_id in message")
                return

            logger.info(f"Handling request {request.request_id}")

            # Process the query with streaming support
            await self.process_query(request)

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
