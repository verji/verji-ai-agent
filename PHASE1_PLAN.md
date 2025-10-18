# Phase 1: Conversation Context (No Encryption)

**Branch**: `taj/conversation-context`
**Goal**: Implement dual context system and conversation memory WITHOUT encryption
**Rationale**: Validate flow and functionality before adding encryption complexity

---

## What We're Building in Phase 1

### ✅ In Scope

1. **Room Context Fetching**
   - Rust bot fetches last N messages from Matrix room
   - Pass room context to graph via Redis pubsub
   - Python graph formats room context as SystemMessage

2. **Conversation Memory (Unencrypted)**
   - LangGraph checkpoints stored in Redis (plaintext)
   - Multi-turn conversations work
   - Checkpoint TTL (24 hours)
   - Session ID structure implemented

3. **Dual Context Integration**
   - LLM sees both room context AND conversation history
   - Room context NOT persisted in checkpoint
   - Conversation history persists across messages

### ❌ Out of Scope (Phase 2)

- ❌ Encryption (ChaCha20-Poly1305, PBKDF2)
- ❌ Tool management (ToolNode, RBAC)
- ❌ HITL workflow
- ❌ Credential injection
- ❌ AccessControlProvider integration

---

## Phase 1 Architecture

### Data Flow

```
┌──────────────┐
│ Matrix Room  │  Alice: "Use PostgreSQL"
│ #database    │  Bob: "Deploy to AWS"
└──────┬───────┘
       │
       ↓
┌─────────────────────────────────────────────────────────┐
│  RUST BOT                                               │
├─────────────────────────────────────────────────────────┤
│  1. Receive: "@bot what database?"                      │
│  2. Fetch room context:                                 │
│     room.messages(backward().limit(20))                 │
│     → Returns [Alice: "Use PostgreSQL", Bob: ...]       │
│  3. Build session_id:                                   │
│     "{room_id}:main:{user_id}"                          │
│  4. Publish to Redis:                                   │
│     {                                                    │
│       "session_id": "!room:main:@dave",                 │
│       "query": "what database?",                        │
│       "room_context": [                                 │
│         {"sender": "@alice", "content": "Use PG"...},   │
│         {"sender": "@bob", "content": "AWS"...}         │
│       ]                                                  │
│     }                                                    │
└─────────────────────────────────────────────────────────┘
       │ Redis Pubsub (plaintext)
       ↓
┌─────────────────────────────────────────────────────────┐
│  PYTHON GRAPH                                           │
├─────────────────────────────────────────────────────────┤
│  1. Receive request from Redis                          │
│  2. Extract session_id → use as thread_id               │
│  3. Load checkpoint (PLAINTEXT from Redis):             │
│     [HumanMessage("Hello"), AIMessage("Hi!")...]        │
│  4. Format room context as SystemMessage                │
│  5. Build LLM messages:                                 │
│     [                                                    │
│       SystemMessage("Room: Alice said X, Bob said Y"),  │
│       HumanMessage("Hello"),  # From checkpoint         │
│       AIMessage("Hi!"),       # From checkpoint         │
│       HumanMessage("what database?")  # Current query   │
│     ]                                                    │
│  6. Call OpenAI                                         │
│  7. Save checkpoint (PLAINTEXT) with TTL                │
│  8. Return response                                     │
└─────────────────────────────────────────────────────────┘
       │
       ↓
┌─────────────────────────────────────────────────────────┐
│  RUST BOT                                               │
│  9. Send response to Matrix room                        │
└─────────────────────────────────────────────────────────┘
```

### Key Differences from Full Implementation

| Feature | Phase 1 (This Branch) | Phase 2 (Later) |
|---------|----------------------|-----------------|
| **Checkpoints** | Plaintext in Redis | Encrypted with ChaCha20 |
| **Saver** | `AsyncRedisSaver` (built-in) | `EncryptedRedisSaver` (custom) |
| **Room Context** | ✅ Implemented | ✅ Same |
| **Conversation Memory** | ✅ Implemented | ✅ Same (just encrypted) |
| **Tools** | ❌ Not implemented | ToolNode with RBAC |
| **HITL** | ❌ Not implemented | Checkpoint-based approval |

---

## Implementation Tasks

### Task 1: Rust - Add RoomMessage Type
**File**: `verji-vagent-bot/src/types.rs`

**What to Add**:
```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RoomMessage {
    pub sender: String,        // "@alice:matrix.org"
    pub content: String,       // Message text
    pub timestamp: u64,        // Unix timestamp
    pub is_bot: bool,          // true if sender is bot
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GraphRequest {
    pub request_id: String,
    pub query: String,
    pub session_id: String,
    pub room_context: Vec<RoomMessage>,  // NEW: room context
}
```

**Success Criteria**:
- ✅ `RoomMessage` struct compiles
- ✅ `GraphRequest` includes `room_context` field
- ✅ Serialization works (test with `serde_json`)

---

### Task 2: Rust - Fetch Room Context from Matrix
**File**: `verji-vagent-bot/src/responders/verji_agent.rs`

**What to Add**:
```rust
impl VerjiAgentResponder {
    async fn fetch_room_context(
        &self,
        room: &Room,
        limit: usize,
    ) -> Result<Vec<RoomMessage>> {
        use matrix_sdk::room::MessagesOptions;

        let options = MessagesOptions::backward().limit(limit as u16);

        match room.messages(options).await {
            Ok(messages) => {
                let bot_user_id = std::env::var("MATRIX_USER")
                    .unwrap_or_default();

                let mut context = Vec::new();

                // Process in reverse (chronological order)
                for event in messages.chunk.iter().rev() {
                    if let Ok(msg_event) = event.event.deserialize() {
                        if let Some(text) = self.extract_text_content(&msg_event) {
                            let sender = msg_event.sender().to_string();

                            context.push(RoomMessage {
                                sender: sender.clone(),
                                content: text,
                                timestamp: msg_event
                                    .origin_server_ts()
                                    .as_secs()
                                    .into(),
                                is_bot: sender == bot_user_id,
                            });
                        }
                    }
                }

                Ok(context)
            }
            Err(e) => {
                warn!("Failed to fetch room context: {}", e);
                Ok(Vec::new())  // Non-fatal, continue without context
            }
        }
    }

    fn extract_text_content(&self, event: &MessageEvent) -> Option<String> {
        // Extract text from message event
        // Filter out images, files, etc.
        match event.content() {
            MessageType::Text(text) => Some(text.body.clone()),
            _ => None,
        }
    }
}
```

**Integration**: Modify existing `respond()` method to call `fetch_room_context()` before sending to graph.

**Success Criteria**:
- ✅ Fetches last 20 messages from room
- ✅ Filters out non-text messages
- ✅ Returns chronological order (oldest first)
- ✅ Marks bot's own messages with `is_bot: true`
- ✅ Non-fatal error (returns empty vec on failure)

---

### Task 3: Rust - Build Session ID
**File**: `verji-vagent-bot/src/responders/verji_agent.rs`

**What to Add**:
```rust
fn build_session_id(
    room_id: &str,
    user_id: &str,
    thread_id: Option<&str>,
) -> String {
    let thread = thread_id.unwrap_or("main");
    format!("{}:{}:{}", room_id, thread, user_id)
}
```

**Usage**:
```rust
let session_id = build_session_id(
    room.room_id().as_str(),
    event.sender().as_str(),
    None,  // TODO: Extract thread_id from event.relates_to
);
```

**Success Criteria**:
- ✅ Format: `{room_id}:{thread_id}:{user_id}`
- ✅ Default thread is "main"
- ✅ Session ID is unique per (room, user) combination

---

### Task 4: Rust - Include Room Context in Request
**File**: `verji-vagent-bot/src/redis_client.rs`

**What to Modify**:
```rust
pub async fn query_with_streaming<F>(
    &mut self,
    query: String,
    room_id: String,
    user_id: String,
    room_context: Vec<RoomMessage>,  // NEW parameter
    on_progress: F,
) -> Result<String>
where
    F: Fn(String) + Send + 'static,
{
    let request_id = Uuid::new_v4().to_string();
    let session_id = format!("{}:main:{}", room_id, user_id);

    let request = GraphRequest {
        request_id: request_id.clone(),
        query,
        session_id,
        room_context,  // NEW: include room context
    };

    let request_json = serde_json::to_string(&request)?;

    // ... rest of the method
}
```

**Success Criteria**:
- ✅ `room_context` included in Redis pubsub message
- ✅ JSON serialization works
- ✅ Graph receives room context

---

### Task 5: Python - Update Request Type
**File**: `verji-vagent-graph/src/types.py`

**What to Add**:
```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class RoomMessage:
    sender: str
    content: str
    timestamp: int
    is_bot: bool

@dataclass
class GraphRequest:
    request_id: str
    query: str
    session_id: str
    room_context: List[RoomMessage]  # NEW field
```

**Success Criteria**:
- ✅ Dataclass matches Rust struct
- ✅ Deserialization works from Redis JSON

---

### Task 6: Python - Use AsyncRedisSaver (Unencrypted)
**File**: `verji-vagent-graph/src/main.py`

**What to Modify**:
```python
from langgraph.checkpoint.redis import AsyncRedisSaver
import redis.asyncio as redis

# Initialize Redis checkpointer (PLAINTEXT for Phase 1)
redis_client = redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379"),
    decode_responses=True
)

# Use built-in AsyncRedisSaver (no encryption)
checkpointer = AsyncRedisSaver(redis_client)

# Initialize agent with checkpointer
agent = VerjiAgent(
    emit_progress_callback=emit_progress,
    checkpointer=checkpointer
)
```

**Success Criteria**:
- ✅ Checkpointer saves to Redis
- ✅ Checkpoints persist across requests
- ✅ Can view checkpoint in redis-cli (plaintext)

---

### Task 7: Python - Format Room Context as SystemMessage
**File**: `verji-vagent-graph/src/graph.py`

**What to Modify**:
```python
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    request_id: str
    session_id: str
    room_context: Optional[str]  # Formatted room context (ephemeral)

class VerjiAgent:
    def _format_room_context(self, room_context: List[RoomMessage]) -> str:
        """Format room context into system message text."""
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

    async def _respond_node(self, state: AgentState) -> AgentState:
        """Generate response using LLM with room context."""

        # Build LLM input
        llm_messages = []

        # Add room context as SystemMessage (NOT saved to checkpoint)
        if state.get("room_context"):
            llm_messages.append(SystemMessage(content=state["room_context"]))

        # Add conversation history from checkpoint
        llm_messages.extend(state["messages"])

        # Call LLM
        response = await self.llm.ainvoke(llm_messages)

        # Return updated state (only AI response, NOT SystemMessage)
        return {"messages": [AIMessage(content=response.content)]}
```

**Key Design Point**: `room_context` is NOT in `messages` list, so it won't be saved to checkpoint.

**Success Criteria**:
- ✅ Room context formatted as readable text
- ✅ SystemMessage prepended to LLM input
- ✅ SystemMessage NOT in checkpoint
- ✅ Conversation history persists

---

### Task 8: Python - Update process() Method
**File**: `verji-vagent-graph/src/graph.py`

**What to Modify**:
```python
async def process(
    self,
    request_id: str,
    session_id: str,
    query: str,
    room_context: Optional[List[RoomMessage]] = None,
) -> str:
    """Process query with room context and checkpoint."""

    config = {
        "configurable": {
            "thread_id": session_id,
        }
    }

    # Format room context (ephemeral)
    room_context_text = None
    if room_context:
        room_context_text = self._format_room_context(room_context)

    # Build input state
    input_state = {
        "messages": [HumanMessage(content=query)],
        "request_id": request_id,
        "session_id": session_id,
        "room_context": room_context_text,  # Ephemeral field
    }

    # Process (LangGraph merges with checkpoint automatically)
    final_state = await self.graph.ainvoke(input_state, config=config)

    # Extract response
    ai_messages = [
        msg for msg in final_state["messages"]
        if isinstance(msg, AIMessage)
    ]

    return ai_messages[-1].content if ai_messages else "No response."
```

**Success Criteria**:
- ✅ Room context passed to graph
- ✅ Checkpoint loaded automatically by LangGraph
- ✅ Current query appended to checkpoint
- ✅ Response returned to bot

---

### Task 9: Python - Update Redis Handler
**File**: `verji-vagent-graph/src/main.py`

**What to Modify**:
```python
async def process_query(self, request_id: str, query: str, session_id: str, room_context: List[dict]):
    """Process query with room context and checkpoints."""

    # Emit progress
    await self.emit_progress(request_id, "🔍 Loading conversation history...")

    # Convert room_context dicts to RoomMessage objects
    room_messages = [
        RoomMessage(**msg) for msg in room_context
    ] if room_context else None

    # Process with agent
    response = await self.agent.process(
        request_id=request_id,
        session_id=session_id,
        query=query,
        room_context=room_messages
    )

    # Emit final response
    await self.emit_final_response(request_id, response)
```

**Success Criteria**:
- ✅ Deserializes room_context from Redis
- ✅ Passes to agent.process()
- ✅ Returns response via pubsub

---

### Task 10: Configuration
**File**: `.env`

**What to Add**:
```bash
# Room Context
ROOM_CONTEXT_LIMIT=20

# Checkpoint TTL (24 hours)
CHECKPOINT_TTL=86400
```

**Success Criteria**:
- ✅ Environment variables loaded
- ✅ Room context limit configurable
- ✅ Checkpoint TTL configurable

---

## Testing Strategy

### Manual Testing

**Test 1: Room Context Fetching**
```bash
# In Matrix room:
User A: "We should use PostgreSQL"
User B: "Good choice, it's reliable"
User C: "@bot what database are we using?"

# Expected: Bot should respond mentioning PostgreSQL
# Verify: Check logs for room_context in request
```

**Test 2: Conversation Memory**
```bash
# In Matrix room:
User: "@bot my name is Alice"
Bot: "Hi Alice! How can I help?"

# Wait 5 seconds

User: "@bot what's my name?"
Bot: "Your name is Alice"  # Should remember from checkpoint

# Expected: Bot remembers previous conversation
# Verify: Check Redis for checkpoint key
```

**Test 3: Dual Context**
```bash
# In Matrix room:
User A: "Our project uses Python"
User B: "@bot what language are we using?"

# Expected: Bot responds "Python" (from room context)

User B: "@bot remember my favorite color is blue"
Bot: "Got it!"

User B: "@bot what's my favorite color?"
Bot: "Blue"  # From checkpoint, not room context

# Expected: Bot distinguishes room context from personal conversation
```

**Test 4: Checkpoint Persistence**
```bash
# In Matrix room:
User: "@bot hello"
Bot: "Hi!"

# Restart bot (kubectl delete pod or tilt restart)

User: "@bot do you remember me?"
Bot: "Yes, we were just talking"  # Loaded from checkpoint

# Expected: Conversation survives bot restart
# Verify: Checkpoint still in Redis after restart
```

### Verification Commands

```bash
# View checkpoint in Redis
redis-cli
> KEYS checkpoint:*
> GET checkpoint:!roomid:main:@userid:latest

# Should see JSON with messages (plaintext)

# Check TTL
> TTL checkpoint:!roomid:main:@userid:latest
# Should be ~86400 (24 hours in seconds)
```

---

## Success Criteria for Phase 1

- [ ] **Room Context**: Bot fetches last 20 messages from Matrix
- [ ] **Session ID**: Format `{room_id}:main:{user_id}` implemented
- [ ] **Checkpoints**: Saved to Redis in plaintext (visible in redis-cli)
- [ ] **Multi-Turn**: Bot remembers previous conversation
- [ ] **Dual Context**: LLM sees both room discussion AND personal chat
- [ ] **Persistence**: Conversation survives bot restart
- [ ] **TTL**: Checkpoints expire after 24 hours
- [ ] **No Room Context in Checkpoint**: SystemMessage not persisted
- [ ] **Manual Tests**: All 4 test scenarios pass

---

## What's Next (Phase 2)

After Phase 1 is complete and verified:

1. **Add Encryption**: Implement `EncryptedRedisSaver`
2. **Migrate Checkpoints**: Re-encrypt existing plaintext checkpoints
3. **Verify Encryption**: Checkpoints unreadable in redis-cli
4. **Add Tools**: Implement ToolNode with RBAC
5. **Add HITL**: Checkpoint-based approval workflow

**Phase 1 lays the foundation for everything else.**

---

## Estimated Timeline

| Task | Estimated Time |
|------|----------------|
| **Task 1-4**: Rust changes | 4-6 hours |
| **Task 5-9**: Python changes | 4-6 hours |
| **Task 10**: Configuration | 30 minutes |
| **Manual Testing**: All scenarios | 2-3 hours |
| **Bug Fixes**: Issues found during testing | 2-4 hours |
| **Total** | **12-20 hours** (2-3 days) |

---

## Ready to Start?

Review this plan, and if approved, we'll begin with **Task 1: Add RoomMessage Type**.

All code will be committed to branch `taj/conversation-context` for review before merging to `main`.
