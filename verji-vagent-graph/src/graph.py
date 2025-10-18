"""
LangGraph workflow for Verji vAgent.

This module implements a conversational agent using LangGraph with OpenAI,
with checkpoint-based conversation memory and room context awareness.
"""

import logging
from typing import TypedDict, Annotated, Sequence, Optional, List
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.base import BaseCheckpointSaver

from schemas import RoomMessage

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    """State for the agent workflow."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    request_id: str
    session_id: str
    room_context: Optional[str]  # Formatted room context (ephemeral, not persisted)


class VerjiAgent:
    """LangGraph-based conversational agent with checkpoint memory and room context."""

    def __init__(self, emit_progress_callback, checkpointer: BaseCheckpointSaver):
        """
        Initialize the agent.

        Args:
            emit_progress_callback: Async function(request_id, content) to emit progress
            checkpointer: LangGraph checkpointer for conversation memory
        """
        self.emit_progress = emit_progress_callback
        self.checkpointer = checkpointer
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.7,
            streaming=False,  # We'll handle streaming via progress updates
        )
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow with checkpointer."""
        workflow = StateGraph(AgentState)

        # Add nodes
        workflow.add_node("analyze", self._analyze_node)
        workflow.add_node("think", self._think_node)
        workflow.add_node("respond", self._respond_node)

        # Define edges
        workflow.set_entry_point("analyze")
        workflow.add_edge("analyze", "think")
        workflow.add_edge("think", "respond")
        workflow.add_edge("respond", END)

        # Compile with checkpointer
        return workflow.compile(checkpointer=self.checkpointer)

    async def _analyze_node(self, state: AgentState) -> AgentState:
        """Analyze the user's question."""
        await self.emit_progress(
            state["request_id"],
            "🔍 Analyzing your question..."
        )
        logger.info(f"[{state['request_id']}] Analyzing: {state['messages'][-1].content}")
        return state

    async def _think_node(self, state: AgentState) -> AgentState:
        """Think about the best response."""
        await self.emit_progress(
            state["request_id"],
            "🧠 Thinking about the best response..."
        )
        logger.info(f"[{state['request_id']}] Thinking...")
        return state

    async def _respond_node(self, state: AgentState) -> AgentState:
        """Generate response using LLM with room context."""
        await self.emit_progress(
            state["request_id"],
            "✍️ Formulating answer..."
        )

        # Build LLM input with room context + conversation history
        llm_messages = []

        # Add room context as SystemMessage (NOT saved to checkpoint)
        if state.get("room_context"):
            llm_messages.append(SystemMessage(content=state["room_context"]))
            logger.info(f"[{state['request_id']}] Including room context in prompt")

        # Add conversation history from checkpoint
        llm_messages.extend(state["messages"])

        # Call OpenAI LLM
        logger.info(f"[{state['request_id']}] Calling OpenAI...")
        response = await self.llm.ainvoke(llm_messages)

        # Add AI response to messages (this WILL be saved to checkpoint)
        # Note: SystemMessage is NOT in state["messages"], so it won't be saved
        return {"messages": [AIMessage(content=response.content)]}

    def _format_room_context(self, room_context: List[RoomMessage]) -> Optional[str]:
        """
        Format room context into system message text.

        Args:
            room_context: List of room messages

        Returns:
            Formatted string or None if no context
        """
        if not room_context:
            return None

        lines = ["Recent room discussion:", ""]

        for msg in room_context:
            # Extract name from Matrix ID (@alice:matrix.org → Alice)
            sender_name = msg.sender.split(":")[0].lstrip("@").title()
            if msg.is_bot:
                sender_name = "Assistant"

            lines.append(f"{sender_name}: {msg.content}")

        lines.extend([
            "",
            "Answer the user's question based on the above context and conversation history."
        ])

        return "\n".join(lines)

    async def process(
        self,
        request_id: str,
        session_id: str,
        query: str,
        room_context: Optional[List[RoomMessage]] = None,
    ) -> str:
        """
        Process a user message through the graph with checkpoint persistence.

        Args:
            request_id: Unique request identifier
            session_id: Session ID for checkpoint isolation (format: room:thread:user)
            query: The user's query
            room_context: Optional list of recent room messages

        Returns:
            The final AI response
        """
        # Configuration for LangGraph (thread_id is used for checkpoint isolation)
        config = {
            "configurable": {
                "thread_id": session_id,
            }
        }

        # Format room context (ephemeral, not persisted)
        room_context_text = self._format_room_context(room_context) if room_context else None

        # Build input state
        # IMPORTANT: Only messages, request_id, session_id will persist in checkpoint
        # room_context is ephemeral (no annotation, overwrites each time)
        input_state = {
            "messages": [HumanMessage(content=query)],
            "request_id": request_id,
            "session_id": session_id,
            "room_context": room_context_text,  # Ephemeral field
        }

        # Run the graph (LangGraph will merge with checkpoint automatically)
        logger.info(f"[{request_id}] Starting graph execution with session {session_id}")
        logger.info(f"[{request_id}] Room context: {len(room_context) if room_context else 0} messages")

        final_state = await self.graph.ainvoke(input_state, config=config)

        # Extract the final AI message
        ai_messages = [msg for msg in final_state["messages"] if isinstance(msg, AIMessage)]
        if ai_messages:
            return ai_messages[-1].content
        else:
            return "I apologize, but I couldn't generate a response."
