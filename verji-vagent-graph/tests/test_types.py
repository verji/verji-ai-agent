"""
Unit tests for type definitions (types.py).

Tests RoomMessage, RequestMetadata, GraphRequest serialization/deserialization
and edge cases.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from schemas import RoomMessage, RequestMetadata, GraphRequest


class TestRoomMessage:
    """Test RoomMessage dataclass."""

    def test_room_message_creation(self):
        """Test creating a RoomMessage with all fields."""
        msg = RoomMessage(
            sender="@alice:matrix.org",
            content="Hello world",
            timestamp=1705000000,
            is_bot=False,
        )
        assert msg.sender == "@alice:matrix.org"
        assert msg.content == "Hello world"
        assert msg.timestamp == 1705000000
        assert msg.is_bot is False

    def test_room_message_bot_flag(self):
        """Test RoomMessage with is_bot=True."""
        msg = RoomMessage(
            sender="@vagent:matrix.org",
            content="I am a bot",
            timestamp=1705000000,
            is_bot=True,
        )
        assert msg.is_bot is True

    def test_room_message_from_dict(self):
        """Test creating RoomMessage from dictionary."""
        data = {
            "sender": "@bob:matrix.org",
            "content": "Test message",
            "timestamp": 1234567890,
            "is_bot": False,
        }
        msg = RoomMessage(**data)
        assert msg.sender == "@bob:matrix.org"
        assert msg.content == "Test message"
        assert msg.timestamp == 1234567890
        assert msg.is_bot is False


class TestRequestMetadata:
    """Test RequestMetadata dataclass."""

    def test_request_metadata_creation(self):
        """Test creating RequestMetadata with all fields."""
        metadata = RequestMetadata(
            room_id="!abc123:matrix.org",
            user_id="@alice:matrix.org",
            timestamp=1705000000,
        )
        assert metadata.room_id == "!abc123:matrix.org"
        assert metadata.user_id == "@alice:matrix.org"
        assert metadata.timestamp == 1705000000

    def test_request_metadata_from_dict(self):
        """Test creating RequestMetadata from dictionary."""
        data = {
            "room_id": "!room:server",
            "user_id": "@user:server",
            "timestamp": 9999999,
        }
        metadata = RequestMetadata(**data)
        assert metadata.room_id == "!room:server"
        assert metadata.user_id == "@user:server"
        assert metadata.timestamp == 9999999


class TestGraphRequest:
    """Test GraphRequest dataclass and from_dict method."""

    def test_graph_request_creation(self, sample_room_messages, sample_metadata):
        """Test creating GraphRequest with all fields."""
        request = GraphRequest(
            request_id="req-123",
            session_id="!room:main:@user",
            query="What is Python?",
            room_context=sample_room_messages,
            metadata=sample_metadata,
        )
        assert request.request_id == "req-123"
        assert request.session_id == "!room:main:@user"
        assert request.query == "What is Python?"
        assert len(request.room_context) == 3
        assert request.metadata == sample_metadata

    def test_graph_request_from_dict_full(self):
        """Test GraphRequest.from_dict with complete data."""
        data = {
            "request_id": "req-456",
            "session_id": "!abc:main:@alice",
            "query": "Hello!",
            "room_context": [
                {
                    "sender": "@alice:matrix.org",
                    "content": "Hi there",
                    "timestamp": 1000,
                    "is_bot": False,
                },
                {
                    "sender": "@bot:matrix.org",
                    "content": "Hello",
                    "timestamp": 1001,
                    "is_bot": True,
                },
            ],
            "metadata": {
                "room_id": "!abc:matrix.org",
                "user_id": "@alice:matrix.org",
                "timestamp": 1002,
            },
        }

        request = GraphRequest.from_dict(data)
        assert request.request_id == "req-456"
        assert request.session_id == "!abc:main:@alice"
        assert request.query == "Hello!"
        assert len(request.room_context) == 2
        assert request.room_context[0].sender == "@alice:matrix.org"
        assert request.room_context[1].is_bot is True
        assert request.metadata.room_id == "!abc:matrix.org"

    def test_graph_request_from_dict_empty_room_context(self):
        """Test GraphRequest.from_dict with empty room_context."""
        data = {
            "request_id": "req-789",
            "session_id": "!room:main:@user",
            "query": "Test",
            "room_context": [],
            "metadata": {
                "room_id": "!room:server",
                "user_id": "@user:server",
                "timestamp": 5000,
            },
        }

        request = GraphRequest.from_dict(data)
        assert request.request_id == "req-789"
        assert len(request.room_context) == 0

    def test_graph_request_from_dict_missing_optional_fields(self):
        """Test GraphRequest.from_dict with missing optional fields (defaults)."""
        data = {
            "request_id": "req-999",
            "metadata": {
                "room_id": "!room:server",
                "user_id": "@user:server",
                "timestamp": 1000,
            },
        }

        request = GraphRequest.from_dict(data)
        assert request.request_id == "req-999"
        assert request.session_id == ""  # Default from get()
        assert request.query == ""  # Default from get()
        assert len(request.room_context) == 0  # Default empty list

    def test_graph_request_from_dict_missing_room_context_key(self):
        """Test GraphRequest.from_dict when room_context key is missing entirely."""
        data = {
            "request_id": "req-000",
            "session_id": "!room:main:@user",
            "query": "Test query",
            # room_context key is missing
            "metadata": {
                "room_id": "!room:server",
                "user_id": "@user:server",
                "timestamp": 2000,
            },
        }

        request = GraphRequest.from_dict(data)
        assert len(request.room_context) == 0  # Should default to empty list

    def test_graph_request_from_dict_missing_request_id_raises_error(self):
        """Test GraphRequest.from_dict raises KeyError when request_id is missing."""
        data = {
            # request_id is missing
            "session_id": "!room:main:@user",
            "query": "Test",
            "metadata": {
                "room_id": "!room:server",
                "user_id": "@user:server",
                "timestamp": 3000,
            },
        }

        with pytest.raises(KeyError):
            GraphRequest.from_dict(data)

    def test_graph_request_from_dict_invalid_room_message_raises_error(self):
        """Test GraphRequest.from_dict raises TypeError for invalid RoomMessage data."""
        data = {
            "request_id": "req-bad",
            "session_id": "!room:main:@user",
            "query": "Test",
            "room_context": [
                {
                    "sender": "@alice:matrix.org",
                    # Missing required fields: content, timestamp, is_bot
                }
            ],
            "metadata": {
                "room_id": "!room:server",
                "user_id": "@user:server",
                "timestamp": 4000,
            },
        }

        with pytest.raises(TypeError):
            GraphRequest.from_dict(data)

    def test_graph_request_from_dict_invalid_metadata_raises_error(self):
        """Test GraphRequest.from_dict raises TypeError for invalid metadata."""
        data = {
            "request_id": "req-bad-meta",
            "session_id": "!room:main:@user",
            "query": "Test",
            "room_context": [],
            "metadata": {
                # Missing required fields
                "room_id": "!room:server",
            },
        }

        with pytest.raises(TypeError):
            GraphRequest.from_dict(data)
