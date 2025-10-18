"""
Unit tests for room context formatting (graph.py).

Tests the _format_room_context method which converts RoomMessage list
into a formatted string for the system message.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from graph import VerjiAgent
from schemas import RoomMessage


class TestRoomContextFormatting:
    """Test room context formatting logic."""

    @pytest.fixture
    def agent(self, mock_emit_progress, mock_checkpointer):
        """Create VerjiAgent instance for testing."""
        return VerjiAgent(
            emit_progress_callback=mock_emit_progress,
            checkpointer=mock_checkpointer,
        )

    def test_format_empty_room_context(self, agent, empty_room_context):
        """Test formatting empty room context returns None."""
        result = agent._format_room_context(empty_room_context)
        assert result is None

    def test_format_single_room_message(self, agent):
        """Test formatting single room message."""
        room_context = [
            RoomMessage(
                sender="@alice:matrix.org",
                content="Hello!",
                timestamp=1705000000,
                is_bot=False,
            )
        ]

        result = agent._format_room_context(room_context)
        assert result is not None
        assert "Recent room discussion:" in result
        assert "Alice: Hello!" in result
        assert "Answer the user's question" in result

    def test_format_multiple_room_messages(self, agent, sample_room_messages):
        """Test formatting multiple room messages."""
        result = agent._format_room_context(sample_room_messages)

        assert result is not None
        assert "Recent room discussion:" in result
        assert "Alice: What's the weather like?" in result
        assert "Assistant:" in result  # Bot messages show as "Assistant"
        assert "I don't have access to weather data." in result
        assert "Bob: Can you help me with Python?" in result

    def test_format_bot_messages_show_as_assistant(self, agent):
        """Test that bot messages are labeled as 'Assistant'."""
        room_context = [
            RoomMessage(
                sender="@vagent:matrix.org",
                content="I am the bot",
                timestamp=1705000000,
                is_bot=True,
            )
        ]

        result = agent._format_room_context(room_context)
        assert "Assistant: I am the bot" in result
        assert "@vagent" not in result  # Raw Matrix ID should not appear

    def test_format_extracts_names_from_matrix_ids(self, agent):
        """Test that sender names are extracted from Matrix IDs correctly."""
        room_context = [
            RoomMessage(
                sender="@alice:matrix.org",
                content="Message 1",
                timestamp=1705000000,
                is_bot=False,
            ),
            RoomMessage(
                sender="@bob:example.com",
                content="Message 2",
                timestamp=1705000001,
                is_bot=False,
            ),
            RoomMessage(
                sender="@charlie_the_great:server.net",
                content="Message 3",
                timestamp=1705000002,
                is_bot=False,
            ),
        ]

        result = agent._format_room_context(room_context)
        assert "Alice: Message 1" in result
        assert "Bob: Message 2" in result
        assert "Charlie_The_Great: Message 3" in result

    def test_format_preserves_message_order(self, agent):
        """Test that messages are formatted in the order they appear."""
        room_context = [
            RoomMessage(
                sender="@alice:matrix.org",
                content="First",
                timestamp=1705000000,
                is_bot=False,
            ),
            RoomMessage(
                sender="@bob:matrix.org",
                content="Second",
                timestamp=1705000001,
                is_bot=False,
            ),
            RoomMessage(
                sender="@charlie:matrix.org",
                content="Third",
                timestamp=1705000002,
                is_bot=False,
            ),
        ]

        result = agent._format_room_context(room_context)
        lines = result.split("\n")

        # Find the message lines (skip header and footer)
        message_lines = [line for line in lines if ": " in line and not line.startswith("Answer")]

        assert len(message_lines) == 3
        assert "First" in message_lines[0]
        assert "Second" in message_lines[1]
        assert "Third" in message_lines[2]

    def test_format_includes_header_and_footer(self, agent):
        """Test that formatted context includes header and instructional footer."""
        room_context = [
            RoomMessage(
                sender="@alice:matrix.org",
                content="Test",
                timestamp=1705000000,
                is_bot=False,
            )
        ]

        result = agent._format_room_context(room_context)
        lines = result.split("\n")

        # Should have header at the start
        assert lines[0] == "Recent room discussion:"
        assert lines[1] == ""  # Empty line after header

        # Should have instructional footer at the end
        assert "Answer the user's question based on the above context" in result

    def test_format_handles_special_characters_in_content(self, agent):
        """Test that special characters in message content are preserved."""
        room_context = [
            RoomMessage(
                sender="@alice:matrix.org",
                content="Test with special chars: @#$%^&*(){}[]|\\<>?",
                timestamp=1705000000,
                is_bot=False,
            )
        ]

        result = agent._format_room_context(room_context)
        assert "Test with special chars: @#$%^&*(){}[]|\\<>?" in result

    def test_format_handles_multiline_content(self, agent):
        """Test that multiline message content is preserved."""
        room_context = [
            RoomMessage(
                sender="@alice:matrix.org",
                content="Line 1\nLine 2\nLine 3",
                timestamp=1705000000,
                is_bot=False,
            )
        ]

        result = agent._format_room_context(room_context)
        assert "Line 1\nLine 2\nLine 3" in result

    def test_format_empty_string_content(self, agent):
        """Test formatting message with empty string content."""
        room_context = [
            RoomMessage(
                sender="@alice:matrix.org",
                content="",
                timestamp=1705000000,
                is_bot=False,
            )
        ]

        result = agent._format_room_context(room_context)
        assert "Alice: " in result  # Should still show sender even with empty content

    def test_format_none_room_context(self, agent):
        """Test that None room_context is handled (treated as empty)."""
        # When called with None, should not crash
        # Note: In actual code, this is protected by if not room_context check
        result = agent._format_room_context(None)
        assert result is None
