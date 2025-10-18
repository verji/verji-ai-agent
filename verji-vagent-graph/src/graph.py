"""
LangGraph workflow for Verji vAgent.

This module implements a simple conversational agent using LangGraph with OpenAI,
demonstrating streaming progress updates at each node.
"""

import logging
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    """State for the agent workflow."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    request_id: str


class VerjiAgent:
    """LangGraph-based conversational agent with streaming progress."""

    def __init__(self, emit_progress_callback):
        """
        Initialize the agent.

        Args:
            emit_progress_callback: Async function(request_id, content) to emit progress
        """
        self.emit_progress = emit_progress_callback
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.7,
            streaming=False,  # We'll handle streaming via progress updates
        )
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow."""
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

        return workflow.compile()

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
        """Generate response using LLM."""
        await self.emit_progress(
            state["request_id"],
            "✍️ Formulating answer..."
        )

        # Get the user's message
        user_message = state["messages"][-1].content

        # Call OpenAI LLM
        logger.info(f"[{state['request_id']}] Calling OpenAI...")
        response = await self.llm.ainvoke(state["messages"])

        # Add AI response to messages
        state["messages"].append(AIMessage(content=response.content))

        logger.info(f"[{state['request_id']}] LLM response: {response.content}")
        return state

    async def process(self, request_id: str, user_message: str) -> str:
        """
        Process a user message through the graph.

        Args:
            request_id: Unique request identifier
            user_message: The user's message

        Returns:
            The final AI response
        """
        # Create initial state
        initial_state = {
            "messages": [HumanMessage(content=user_message)],
            "request_id": request_id,
        }

        # Run the graph
        logger.info(f"[{request_id}] Starting graph execution")
        final_state = await self.graph.ainvoke(initial_state)

        # Extract the final AI message
        ai_messages = [msg for msg in final_state["messages"] if isinstance(msg, AIMessage)]
        if ai_messages:
            return ai_messages[-1].content
        else:
            return "I apologize, but I couldn't generate a response."
