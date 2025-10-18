"""Type definitions for vagent-graph service."""

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class RoomMessage:
    """A single message from a Matrix room."""

    sender: str  # "@alice:matrix.org"
    content: str  # Message text content
    timestamp: int  # Unix timestamp (seconds)
    is_bot: bool  # true if sender is the bot


@dataclass
class RequestMetadata:
    """Metadata about the request."""

    room_id: str
    user_id: str
    timestamp: int


@dataclass
class GraphRequest:
    """Request from vagent-bot to process a query."""

    request_id: str
    session_id: str  # "{room_id}:{thread_id}:{user_id}"
    query: str
    room_context: List[RoomMessage]
    metadata: RequestMetadata

    @classmethod
    def from_dict(cls, data: Dict) -> "GraphRequest":
        """Create GraphRequest from dict (from Redis JSON)."""
        room_context = [
            RoomMessage(**msg) for msg in data.get("room_context", [])
        ]
        metadata = RequestMetadata(**data.get("metadata", {}))

        return cls(
            request_id=data["request_id"],
            session_id=data.get("session_id", ""),
            query=data.get("query", ""),
            room_context=room_context,
            metadata=metadata,
        )
