"""
Unit tests for LangGraph workflow nodes (graph.py).

Tests the individual node functions and overall workflow behavior.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from graph import VerjiAgent, AgentState
from schemas import RoomMessage


class TestAgentNodes:
    """Test individual workflow nodes."""

    @pytest.mark.asyncio
    async def test_analyze_node_emits_progress(self, agent_with_mock_llm, mock_emit_progress):
        """Test that _analyze_node emits progress message."""
        agent = agent_with_mock_llm
        state = {
            "messages": [HumanMessage(content="Test query")],
            "request_id": "req-123",
            "session_id": "!room:main:@user",
            "room_context": None,
        }

        result = await agent._analyze_node(state)

        # Should emit progress
        mock_emit_progress.assert_called_once_with(
            "req-123", "🔍 Analyzing your question..."
        )

        # Should return state unchanged
        assert result == state

    @pytest.mark.asyncio
    async def test_think_node_emits_progress(self, agent_with_mock_llm, mock_emit_progress):
        """Test that _think_node emits progress message."""
        agent = agent_with_mock_llm
        state = {
            "messages": [HumanMessage(content="Test query")],
            "request_id": "req-456",
            "session_id": "!room:main:@user",
            "room_context": None,
        }

        result = await agent._think_node(state)

        # Should emit progress
        mock_emit_progress.assert_called_once_with(
            "req-456", "🧠 Thinking about the best response..."
        )

        # Should return state unchanged
        assert result == state

    @pytest.mark.asyncio
    async def test_respond_node_emits_progress(self, agent_with_mock_llm, mock_emit_progress):
        """Test that _respond_node emits progress message."""
        agent = agent_with_mock_llm
        state = {
            "messages": [HumanMessage(content="Test query")],
            "request_id": "req-789",
            "session_id": "!room:main:@user",
            "room_context": None,
        }

        agent._mock_llm_ainvoke.return_value = AIMessage(content="Test response")
        await agent._respond_node(state)

        # Should emit progress
        mock_emit_progress.assert_called_once_with(
            "req-789", "✍️ Formulating answer..."
        )

    @pytest.mark.asyncio
    async def test_respond_node_calls_llm(self, agent_with_mock_llm):
        """Test that _respond_node calls the LLM."""
        agent = agent_with_mock_llm
        state = {
            "messages": [HumanMessage(content="What is Python?")],
            "request_id": "req-001",
            "session_id": "!room:main:@user",
            "room_context": None,
        }

        agent._mock_llm_ainvoke.return_value = AIMessage(content="Python is a programming language")

        result = await agent._respond_node(state)

        # Should call LLM
        assert agent._mock_llm_ainvoke.call_count == 1

        # Should return AIMessage in result
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert result["messages"][0].content == "Python is a programming language"

    @pytest.mark.asyncio
    async def test_respond_node_includes_room_context_as_system_message(self, agent_with_mock_llm):
        """Test that _respond_node prepends room_context as SystemMessage."""
        agent = agent_with_mock_llm
        room_context_text = "Recent room discussion:\n\nAlice: Hello"

        state = {
            "messages": [HumanMessage(content="User query")],
            "request_id": "req-001",
            "session_id": "!room:main:@user",
            "room_context": room_context_text,
        }

        agent._mock_llm_ainvoke.return_value = AIMessage(content="Response")

        await agent._respond_node(state)

        # Check LLM was called with SystemMessage + conversation messages
        call_args = agent._mock_llm_ainvoke.call_args
        messages_sent_to_llm = call_args[0][0]

        # First message should be SystemMessage with room context
        assert len(messages_sent_to_llm) >= 2
        assert isinstance(messages_sent_to_llm[0], SystemMessage)
        assert messages_sent_to_llm[0].content == room_context_text

        # Second message should be the HumanMessage
        assert isinstance(messages_sent_to_llm[1], HumanMessage)
        assert messages_sent_to_llm[1].content == "User query"

    @pytest.mark.asyncio
    async def test_respond_node_without_room_context(self, agent_with_mock_llm):
        """Test that _respond_node works without room_context."""
        agent = agent_with_mock_llm
        state = {
            "messages": [HumanMessage(content="User query")],
            "request_id": "req-001",
            "session_id": "!room:main:@user",
            "room_context": None,
        }

        agent._mock_llm_ainvoke.return_value = AIMessage(content="Response")

        await agent._respond_node(state)

        # Check LLM was called WITHOUT SystemMessage
        call_args = agent._mock_llm_ainvoke.call_args
        messages_sent_to_llm = call_args[0][0]

        # Should only have HumanMessage, no SystemMessage
        assert len(messages_sent_to_llm) == 1
        assert isinstance(messages_sent_to_llm[0], HumanMessage)

    @pytest.mark.asyncio
    async def test_respond_node_includes_conversation_history(self, agent_with_mock_llm):
        """Test that _respond_node includes all conversation messages."""
        agent = agent_with_mock_llm
        state = {
            "messages": [
                HumanMessage(content="First query"),
                AIMessage(content="First response"),
                HumanMessage(content="Second query"),
            ],
            "request_id": "req-001",
            "session_id": "!room:main:@user",
            "room_context": None,
        }

        agent._mock_llm_ainvoke.return_value = AIMessage(content="Second response")

        await agent._respond_node(state)

        # Check all messages were sent to LLM
        call_args = agent._mock_llm_ainvoke.call_args
        messages_sent_to_llm = call_args[0][0]

        assert len(messages_sent_to_llm) == 3
        assert messages_sent_to_llm[0].content == "First query"
        assert messages_sent_to_llm[1].content == "First response"
        assert messages_sent_to_llm[2].content == "Second query"


class TestGraphWorkflow:
    """Test the overall graph workflow."""

    @pytest.mark.asyncio
    async def test_process_method_returns_ai_response(self, agent_with_mock_llm):
        """Test that process() method returns the AI response."""
        agent = agent_with_mock_llm
        agent._mock_llm_ainvoke.return_value = AIMessage(content="This is my response")

        response = await agent.process(
            request_id="req-001",
            session_id="!room:main:@user",
            query="Test query",
            room_context=None,
        )

        assert response == "This is my response"

    @pytest.mark.asyncio
    async def test_process_method_emits_all_progress_messages(
        self, agent_with_mock_llm, mock_emit_progress
    ):
        """Test that process() emits progress at each node."""
        agent = agent_with_mock_llm
        agent._mock_llm_ainvoke.return_value = AIMessage(content="Response")

        await agent.process(
            request_id="req-001",
            session_id="!room:main:@user",
            query="Test",
            room_context=None,
        )

        # Should have emitted 3 progress messages (analyze, think, respond)
        assert mock_emit_progress.call_count == 3

        calls = [call[0] for call in mock_emit_progress.call_args_list]
        assert calls[0] == ("req-001", "🔍 Analyzing your question...")
        assert calls[1] == ("req-001", "🧠 Thinking about the best response...")
        assert calls[2] == ("req-001", "✍️ Formulating answer...")

    @pytest.mark.asyncio
    async def test_process_method_with_room_context(self, agent_with_mock_llm, sample_room_messages):
        """Test process() method with room_context."""
        agent = agent_with_mock_llm
        agent._mock_llm_ainvoke.return_value = AIMessage(content="Response based on context")

        response = await agent.process(
            request_id="req-001",
            session_id="!room:main:@user",
            query="What did Alice ask?",
            room_context=sample_room_messages,
        )

        assert response == "Response based on context"

        # Verify LLM received room context as SystemMessage
        call_args = agent._mock_llm_ainvoke.call_args
        messages_sent_to_llm = call_args[0][0]

        system_messages = [m for m in messages_sent_to_llm if isinstance(m, SystemMessage)]
        assert len(system_messages) == 1
        assert "Alice" in system_messages[0].content
        assert "weather" in system_messages[0].content.lower()

    @pytest.mark.asyncio
    async def test_process_method_builds_correct_input_state(self, agent_with_mock_llm, monkeypatch):
        """Test that process() builds input state correctly."""
        agent = agent_with_mock_llm

        # Spy on graph.ainvoke to check input_state
        original_ainvoke = agent.graph.ainvoke
        captured_input = None

        async def spy_ainvoke(input_state, config=None):
            nonlocal captured_input
            captured_input = input_state
            return await original_ainvoke(input_state, config=config)

        monkeypatch.setattr(agent.graph, "ainvoke", spy_ainvoke)
        agent._mock_llm_ainvoke.return_value = AIMessage(content="Response")

        await agent.process(
            request_id="req-123",
            session_id="!room:main:@user",
            query="Test query",
            room_context=None,
        )

        # Check input state structure
        assert captured_input is not None
        assert "messages" in captured_input
        assert "request_id" in captured_input
        assert "session_id" in captured_input
        assert "room_context" in captured_input

        assert captured_input["request_id"] == "req-123"
        assert captured_input["session_id"] == "!room:main:@user"
        assert len(captured_input["messages"]) == 1
        assert isinstance(captured_input["messages"][0], HumanMessage)
        assert captured_input["messages"][0].content == "Test query"

    @pytest.mark.asyncio
    async def test_process_method_handles_no_ai_response(self, agent_with_mock_llm, monkeypatch):
        """Test that process() returns fallback message when no AI response."""
        agent = agent_with_mock_llm

        # Mock the graph to return state with no AIMessage
        async def mock_ainvoke(input_state, config=None):
            return {
                "messages": [HumanMessage(content="Query")],
                "request_id": "req-001",
                "session_id": "!room:main:@user",
                "room_context": None,
            }

        monkeypatch.setattr(agent.graph, "ainvoke", mock_ainvoke)

        response = await agent.process(
            request_id="req-001",
            session_id="!room:main:@user",
            query="Test",
            room_context=None,
        )

        assert response == "I apologize, but I couldn't generate a response."

    @pytest.mark.asyncio
    async def test_process_extracts_last_ai_message(self, agent_with_mock_llm, monkeypatch):
        """Test that process() extracts the last AIMessage from final state."""
        agent = agent_with_mock_llm

        # Mock the graph to return multiple AIMessages
        async def mock_ainvoke(input_state, config=None):
            return {
                "messages": [
                    HumanMessage(content="Query 1"),
                    AIMessage(content="Response 1"),
                    HumanMessage(content="Query 2"),
                    AIMessage(content="Response 2"),
                ],
                "request_id": "req-001",
                "session_id": "!room:main:@user",
                "room_context": None,
            }

        monkeypatch.setattr(agent.graph, "ainvoke", mock_ainvoke)

        response = await agent.process(
            request_id="req-001",
            session_id="!room:main:@user",
            query="Test",
            room_context=None,
        )

        # Should extract last AIMessage
        assert response == "Response 2"


class TestAgentState:
    """Test AgentState TypedDict behavior."""

    def test_agent_state_has_required_fields(self):
        """Test that AgentState has all required fields."""
        from graph import AgentState

        # Check that AgentState has the expected keys
        # Note: TypedDict doesn't have instances, this is for documentation
        assert "messages" in AgentState.__annotations__
        assert "request_id" in AgentState.__annotations__
        assert "session_id" in AgentState.__annotations__
        assert "room_context" in AgentState.__annotations__

    def test_agent_state_messages_field_has_add_messages_annotation(self):
        """Test that messages field uses add_messages annotation."""
        from graph import AgentState
        from langgraph.graph.message import add_messages

        # Check that messages field has Annotated with add_messages
        messages_annotation = AgentState.__annotations__["messages"]

        # The annotation should be Annotated[Sequence[BaseMessage], add_messages]
        # We can check by inspecting the annotation metadata
        if hasattr(messages_annotation, "__metadata__"):
            assert add_messages in messages_annotation.__metadata__
