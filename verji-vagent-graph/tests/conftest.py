"""
Pytest fixtures for verji-vagent-graph tests.

This module provides shared fixtures for testing the LangGraph workflow,
including mocked Redis, LLM responses, and common test data.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from typing import List
import sys
from pathlib import Path

# Add src to path so we can import modules
import os
os.environ["OPENAI_API_KEY"] = "sk-test-dummy-key-for-unit-tests"

# Set dummy OpenAI API key for testing (so ChatOpenAI can initialize)
import os
os.environ["OPENAI_API_KEY"] = "sk-test-dummy-key-for-unit-tests"

src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from schemas import RoomMessage, RequestMetadata, GraphRequest


@pytest.fixture
def sample_room_messages() -> List[RoomMessage]:
    """Sample room messages for testing."""
    return [
        RoomMessage(
            sender="@alice:matrix.org",
            content="What's the weather like?",
            timestamp=1705000000,
            is_bot=False,
        ),
        RoomMessage(
            sender="@vagent:matrix.org",
            content="I don't have access to weather data.",
            timestamp=1705000010,
            is_bot=True,
        ),
        RoomMessage(
            sender="@bob:matrix.org",
            content="Can you help me with Python?",
            timestamp=1705000020,
            is_bot=False,
        ),
    ]


@pytest.fixture
def sample_metadata() -> RequestMetadata:
    """Sample request metadata for testing."""
    return RequestMetadata(
        room_id="!abc123:matrix.org",
        user_id="@alice:matrix.org",
        timestamp=1705000030,
    )


@pytest.fixture
def sample_graph_request(sample_room_messages, sample_metadata) -> GraphRequest:
    """Sample GraphRequest for testing."""
    return GraphRequest(
        request_id="req-123",
        session_id="!abc123:matrix.org:main:@alice:matrix.org",
        query="What is Python?",
        room_context=sample_room_messages,
        metadata=sample_metadata,
    )


@pytest.fixture
def mock_redis_client():
    """Mock Redis client for testing."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=None)
    mock_client.set = AsyncMock(return_value=True)
    mock_client.setex = AsyncMock(return_value=True)
    mock_client.delete = AsyncMock(return_value=1)
    mock_client.exists = AsyncMock(return_value=0)
    mock_client.keys = AsyncMock(return_value=[])
    mock_client.publish = AsyncMock(return_value=1)
    return mock_client


@pytest.fixture
def mock_checkpointer():
    """Mock LangGraph checkpointer for testing."""
    from langgraph.checkpoint.base import CheckpointTuple, Checkpoint

    mock = AsyncMock()
    # Return None for aget (no saved checkpoint)
    mock.aget = AsyncMock(return_value=None)
    mock.aput = AsyncMock(return_value=None)
    mock.aget_tuple = AsyncMock(return_value=None)
    mock.aput_writes = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def mock_llm():
    """Mock ChatOpenAI LLM for testing."""
    mock = AsyncMock()
    mock.ainvoke = AsyncMock()
    return mock


@pytest.fixture
def mock_emit_progress():
    """Mock emit_progress callback for testing."""
    return AsyncMock()


@pytest.fixture
def empty_room_context() -> List[RoomMessage]:
    """Empty room context for testing."""
    return []


@pytest.fixture
def session_id_main() -> str:
    """Standard session ID for main thread."""
    return "!room123:matrix.org:main:@user:matrix.org"


@pytest.fixture
def session_id_thread() -> str:
    """Session ID for threaded conversation."""
    return "!room123:matrix.org:$thread456:@user:matrix.org"


@pytest.fixture
def agent_with_mock_llm(mock_emit_progress, monkeypatch):
    """Create VerjiAgent with a fully mocked LLM that can be controlled in tests."""
    from graph import VerjiAgent
    from langchain_core.messages import AIMessage
    from langchain_openai import ChatOpenAI

    # Create a mock LLM instance that will replace ChatOpenAI
    mock_llm = MagicMock(spec=ChatOpenAI)
    mock_ainvoke = AsyncMock(return_value=AIMessage(content="Default test response"))
    mock_llm.ainvoke = mock_ainvoke

    # Patch ChatOpenAI constructor to return our mock
    def mock_chat_openai_init(*args, **kwargs):
        return mock_llm

    monkeypatch.setattr("graph.ChatOpenAI", mock_chat_openai_init)

    # Now create the agent with NO checkpointer (simpler for unit tests)
    agent = VerjiAgent(
        emit_progress_callback=mock_emit_progress,
        checkpointer=None,  # No checkpointer for unit tests
    )

    # Store the mock on the agent for easy access in tests
    agent._mock_llm_ainvoke = mock_ainvoke

    return agent
