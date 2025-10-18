# Conversation Context & Encrypted Checkpoints Architecture

**Status**: Implementation Ready
**Version**: 1.0
**Date**: 2025-01-18

---

## Table of Contents

1. [Overview](#1-overview)
2. [Core Concepts](#2-core-concepts)
3. [Data Flow](#3-data-flow)
4. [Encryption Architecture](#4-encryption-architecture)
5. [Implementation Details](#5-implementation-details)
6. [Security Analysis](#6-security-analysis)
7. [Configuration](#7-configuration)

---

## 1. Overview

### Purpose

This document describes the conversation context management and encryption strategy for Verji AI Agent, enabling:

- **Room Awareness**: Bot sees recent room discussion from all users
- **Conversation Memory**: Bot remembers multi-turn conversations with each specific user
- **Security**: Conversation state encrypted at rest in Redis
- **Scalability**: Bounded memory usage with TTL-based cleanup

### Key Design Principles

| Principle | Implementation | Benefit |
|-----------|----------------|---------|
| **Dual Context** | Room context (fresh) + Checkpoint (persistent) | Bot aware of room + remembers conversations |
| **Single Encryption Layer** | Python/LangGraph only | Simpler, checkpoint is authoritative |
| **Checkpoint as Source of Truth** | LangGraph manages conversation state | Consistent, automatic history |
| **Room Context Ephemeral** | Regenerated on each query | Always current, doesn't bloat checkpoints |
| **Encryption at Rest Only** | ChaCha20-Poly1305 for checkpoints | Protects persistent data, simple design |

---

## 2. Core Concepts

### 2.1 Two Types of Context

The AI agent has access to **two distinct types of context**, each serving a different purpose:

#### **Room Context** (Fresh, Ephemeral)

**What**: Recent messages from ALL users in the Matrix room

**Source**: Matrix API (`room.messages()`)

**Lifecycle**: Fetched fresh on every query, never persisted

**Format**:
```rust
pub struct RoomMessage {
    pub sender: String,        // "@alice:matrix.org"
    pub content: String,       // "We should use PostgreSQL"
    pub timestamp: u64,        // Unix timestamp
    pub is_bot: bool,          // true if sender is bot
}
```

**Purpose**: Provides the bot with situational awareness of what everyone in the room is discussing

**Example**:
```
Room #database-planning:
  Alice: "I think we should use PostgreSQL"
  Bob: "Good choice, it's ACID compliant"
  Carol: "Should we use RDS or self-hosted?"
  Alice: "Let's use RDS for easier maintenance"
```

When Dave asks "@bot what database did we choose?", the bot can answer "PostgreSQL with AWS RDS" by referencing the room context.

#### **Conversation History** (Persistent, Encrypted)

**What**: Past interactions between THIS specific user and the bot

**Source**: LangGraph checkpoint stored in Redis

**Lifecycle**: Persists for 24 hours (configurable TTL)

**Format**: LangChain messages (HumanMessage, AIMessage, ToolMessage)

**Purpose**: Enables multi-turn conversations, remembers user preferences, maintains context across sessions

**Example**:
```python
checkpoint_messages = [
    HumanMessage("Hello, I'm Alice"),
    AIMessage("Hi Alice! How can I help?"),
    HumanMessage("What's your name?"),
    AIMessage("I'm Verji AI Agent"),
    HumanMessage("What database did we choose?"),  # Current query
]
```

#### **Why Both?**

| Scenario | Room Context Needed? | Conversation History Needed? |
|----------|---------------------|------------------------------|
| "What database are we using?" | ✅ Yes (Alice mentioned PostgreSQL) | ❌ No (room discussion, not personal) |
| "What's my name?" | ❌ No | ✅ Yes (user said "I'm Alice" earlier) |
| "Why did we choose PostgreSQL?" | ✅ Yes (Bob explained ACID compliance) | ✅ Yes (context that user already knows choice) |

**Combined Power**: Bot sees room discussion AND remembers individual conversations.

---

### 2.2 Session ID Structure

**Format**: `{room_id}:{thread_id}:{user_id}`

**Examples**:
- Main room: `!abc123:matrix.org:main:@alice:matrix.org`
- Threaded conversation: `!abc123:matrix.org:$thread456:@bob:matrix.org`
- Direct message: `!dm789:matrix.org:main:@carol:matrix.org`

**Purpose**:
- Used as LangGraph `thread_id` for checkpoint persistence
- Ensures each (room, thread, user) combination has separate conversation history
- Alice and Bob in same room have different checkpoints

**Key Property**: Session isolation

```
Same room, different users:
  Session A: !room:main:@alice  ← Alice's checkpoint
  Session B: !room:main:@bob    ← Bob's checkpoint (separate)

Same user, different rooms:
  Session C: !room1:main:@alice  ← Alice in room1
  Session D: !room2:main:@alice  ← Alice in room2 (separate)
```

---

### 2.3 Checkpoint Lifecycle

```
┌─────────────────────────────────────────────────────────────┐
│              CHECKPOINT LIFECYCLE                           │
└─────────────────────────────────────────────────────────────┘

CREATE (First Message)
═══════════════════════
User: "Hello"
  ├─ Bot fetches room context (last 20 messages)
  ├─ Graph checks Redis: checkpoint:{session_id}:* → EMPTY
  ├─ Graph creates new checkpoint:
  │    {
  │      "messages": [
  │        {"type": "human", "content": "Hello"},
  │        {"type": "ai", "content": "Hi! How can I help?"}
  │      ]
  │    }
  └─ Saves to Redis (encrypted) with 24h TTL

UPDATE (Subsequent Messages)
═══════════════════════════════
User: "What's your name?"
  ├─ Bot fetches room context (fresh)
  ├─ Graph loads checkpoint → Has "Hello" conversation
  ├─ Graph appends new message:
  │    {
  │      "messages": [
  │        {"type": "human", "content": "Hello"},
  │        {"type": "ai", "content": "Hi! How can I help?"},
  │        {"type": "human", "content": "What's your name?"},
  │        {"type": "ai", "content": "I'm Verji AI Agent"}
  │      ]
  │    }
  └─ Updates Redis (re-encrypted) with refreshed 24h TTL

EXPIRE (After TTL)
═══════════════════
After 24 hours of inactivity:
  ├─ Redis automatically deletes checkpoint (TTL expired)
  ├─ Next message creates NEW checkpoint (fresh start)
  └─ Previous conversation history is gone

MANUAL DELETE (Optional)
═════════════════════════
User: "@bot forget our conversation"
  ├─ Bot deletes Redis key: checkpoint:{session_id}:*
  └─ Next message starts fresh
```

---

## 3. Data Flow

### 3.1 Complete Message Flow

```
┌────────────────────────────────────────────────────────────────┐
│         DETAILED REQUEST FLOW WITH CONTEXTS                    │
└────────────────────────────────────────────────────────────────┘

┌──────────────┐
│ Matrix Room  │  Room discussion:
│              │  - Alice: "Use PostgreSQL"
│ #database    │  - Bob: "Deploy to AWS"
│              │  - Carol: "What about security?"
└──────┬───────┘
       │ Matrix Client-Server API
       ↓
┌──────────────────────────────────────────────────────────────┐
│  STEP 1: Bot Receives Message                                │
├──────────────────────────────────────────────────────────────┤
│  User: "@bot what database did we choose?"                   │
│                                                               │
│  Bot Actions:                                                │
│  1. Extract: query, sender, room_id                         │
│  2. Fetch room context (Matrix API):                        │
│     room.messages(MessagesOptions::backward().limit(20))    │
│     → Returns last 20 room messages (all users)             │
│  3. Build session_id:                                        │
│     "!room123:matrix.org:main:@dave:matrix.org"             │
│  4. Build GraphRequest:                                      │
│     {                                                         │
│       "request_id": "uuid-123",                              │
│       "query": "what database did we choose?",               │
│       "session_id": "!room123:main:@dave",                   │
│       "room_context": [                                      │
│         {"sender": "@alice", "content": "Use PostgreSQL"...},│
│         {"sender": "@bob", "content": "Deploy to AWS"...},   │
│         ...18 more messages                                  │
│       ]                                                       │
│     }                                                         │
│  5. Publish to Redis pubsub: "vagent:requests"              │
└──────┬───────────────────────────────────────────────────────┘
       │ Redis Pubsub (ephemeral, in-memory, plaintext)
       ↓
┌──────────────────────────────────────────────────────────────┐
│  STEP 2: Graph Receives Request                              │
├──────────────────────────────────────────────────────────────┤
│  Graph Actions:                                              │
│  1. Parse request from Redis pubsub                         │
│  2. Extract session_id → use as thread_id                   │
│  3. Check Redis: checkpoint:{thread_id}:*                   │
│                                                               │
│  IF checkpoint EXISTS:                                       │
│  ├─ Load encrypted checkpoint from Redis 🔒                 │
│  ├─ Decrypt with ChaCha20-Poly1305                          │
│  ├─ Extract conversation history:                           │
│  │   [HumanMessage("Hello"), AIMessage("Hi!")...]           │
│  └─ IGNORE room_context (checkpoint has full conversation)  │
│                                                               │
│  IF checkpoint EMPTY:                                        │
│  ├─ No conversation history yet (first message)             │
│  └─ May use room_context to initialize (situational)        │
└──────┬───────────────────────────────────────────────────────┘
       ↓
┌──────────────────────────────────────────────────────────────┐
│  STEP 3: Build LLM Context                                   │
├──────────────────────────────────────────────────────────────┤
│  Graph builds message list for LLM:                         │
│                                                               │
│  messages = [                                                │
│    # 1. Room context (ephemeral, NOT from checkpoint)       │
│    SystemMessage("""                                         │
│      Recent room discussion:                                │
│                                                               │
│      Alice: Use PostgreSQL                                   │
│      Bob: Deploy to AWS                                      │
│      Carol: What about security?                             │
│                                                               │
│      Answer based on above context and your knowledge.      │
│    """),                                                     │
│                                                               │
│    # 2. Conversation history (from checkpoint if exists)    │
│    HumanMessage("Hello"),        # From checkpoint          │
│    AIMessage("Hi Dave!"),        # From checkpoint          │
│    HumanMessage("My role?"),     # From checkpoint          │
│    AIMessage("You're a dev"),    # From checkpoint          │
│                                                               │
│    # 3. Current query                                        │
│    HumanMessage("what database did we choose?")             │
│  ]                                                            │
│                                                               │
│  LLM Context Includes:                                       │
│  ✅ Recent room discussion (everyone's messages)            │
│  ✅ Past conversation with this user                        │
│  ✅ Current question                                         │
└──────┬───────────────────────────────────────────────────────┘
       ↓
┌──────────────────────────────────────────────────────────────┐
│  STEP 4: LangGraph Processing                                │
├──────────────────────────────────────────────────────────────┤
│  Graph executes workflow:                                    │
│                                                               │
│  ┌─────────────┐                                             │
│  │ analyze_node│ → Emit: "🔍 Analyzing..."                   │
│  └──────┬──────┘                                             │
│         ↓                                                     │
│  ┌─────────────┐                                             │
│  │ think_node  │ → Emit: "🧠 Thinking..."                    │
│  └──────┬──────┘                                             │
│         ↓                                                     │
│  ┌─────────────┐                                             │
│  │respond_node │ → Call OpenAI with full context            │
│  │             │ → Response: "You chose PostgreSQL with AWS" │
│  └──────┬──────┘                                             │
│         ↓                                                     │
│    Save checkpoint 🔒                                        │
└──────┬───────────────────────────────────────────────────────┘
       ↓
┌──────────────────────────────────────────────────────────────┐
│  STEP 5: Save Updated Checkpoint (Encrypted)                 │
├──────────────────────────────────────────────────────────────┤
│  Checkpoint content:                                         │
│  {                                                            │
│    "messages": [                                             │
│      {"type": "human", "content": "Hello"},                  │
│      {"type": "ai", "content": "Hi Dave!"},                  │
│      {"type": "human", "content": "My role?"},               │
│      {"type": "ai", "content": "You're a dev"},              │
│      {"type": "human", "content": "what database?"},         │
│      {"type": "ai", "content": "PostgreSQL with AWS"}        │
│    ]                                                          │
│  }                                                            │
│                                                               │
│  ⚠️ NOTE: SystemMessage (room context) NOT in checkpoint    │
│           It's regenerated fresh on next query               │
│                                                               │
│  Encryption Process:                                         │
│  1. Serialize checkpoint to JSON                            │
│  2. Derive thread key: PBKDF2(master_key, session_id)       │
│  3. Generate random 96-bit nonce                            │
│  4. Encrypt: ChaCha20-Poly1305(plaintext, nonce)            │
│  5. Store: Redis key checkpoint:{session_id}:latest         │
│  6. Set TTL: 86400 seconds (24 hours)                       │
└──────┬───────────────────────────────────────────────────────┘
       │
       ↓
┌──────────────────────────────────────────────────────────────┐
│  STEP 6: Return Response                                     │
├──────────────────────────────────────────────────────────────┤
│  Graph publishes to Redis pubsub "vagent:responses":        │
│  {                                                            │
│    "request_id": "uuid-123",                                 │
│    "message_type": "final_response",                         │
│    "content": "You chose PostgreSQL with AWS RDS"            │
│  }                                                            │
│                                                               │
│  Bot receives → sends to Matrix room                        │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 What Gets Persisted vs Ephemeral

```
┌────────────────────────────────────────────────────────────┐
│           PERSISTENCE BOUNDARIES                           │
└────────────────────────────────────────────────────────────┘

EPHEMERAL (In-Memory Only, Plaintext):
═══════════════════════════════════════
├─ Room context (Redis pubsub)
│  └─ Lifetime: Seconds (during request processing)
├─ Current query (Redis pubsub)
│  └─ Lifetime: Seconds
├─ Progress messages (Redis pubsub)
│  └─ Lifetime: Seconds
└─ Final response (Redis pubsub)
   └─ Lifetime: Seconds

⚠️ Redis pubsub is in-memory only, NOT written to RDB/AOF

PERSISTENT (Written to Disk, Encrypted):
═════════════════════════════════════════
├─ Conversation history (LangGraph checkpoint)
│  ├─ Contains: User messages, AI responses, tool results
│  ├─ Location: Redis keys checkpoint:{session_id}:*
│  ├─ Encryption: ChaCha20-Poly1305 (per-session key)
│  └─ Lifetime: 24 hours (TTL)
└─ HITL pause state (in checkpoint)
   ├─ Contains: Pending action, approval context
   └─ Encrypted same as conversation

NOT PERSISTED:
═══════════════
❌ Room context (regenerated fresh each query)
❌ SystemMessage (room context formatted as system prompt)
```

---

## 4. Encryption Architecture

### 4.1 Single Encryption Layer Design

**Decision**: Encrypt only LangGraph checkpoints (Python), not bot message cache

**Rationale**:
- ✅ Checkpoints are the authoritative source of conversation state
- ✅ Room context is ephemeral (fetched fresh from Matrix)
- ✅ Simpler: One encryption implementation instead of two
- ✅ LangGraph automatically manages checkpoint lifecycle

```
┌────────────────────────────────────────────────────────────┐
│        ENCRYPTION SCOPE                                    │
└────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  ENCRYPTED (ChaCha20-Poly1305 AEAD)                      │
├─────────────────────────────────────────────────────────┤
│  Redis Keys: checkpoint:{session_id}:*                  │
│                                                           │
│  Contents:                                               │
│  • User messages (HumanMessage)                          │
│  • AI responses (AIMessage)                              │
│  • Tool call results (ToolMessage)                       │
│  • Graph state variables                                │
│  • HITL pause state                                      │
│  • Metadata (timestamps, etc.)                           │
│                                                           │
│  Encryption: Per-session key derived from master         │
│  Lifetime: 24 hours (TTL)                                │
│  Storage: Redis RDB/AOF persistence                      │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  NOT ENCRYPTED (Ephemeral or Matrix-Managed)            │
├─────────────────────────────────────────────────────────┤
│  Redis Pubsub Channels: vagent:requests, responses      │
│  • Reason: In-memory only, not written to disk          │
│  • Contains: room_context, query, responses             │
│  • Mitigation: Use Redis TLS for transport security     │
│                                                           │
│  Matrix Room Messages:                                   │
│  • Managed by Matrix server                              │
│  • Use Matrix E2EE for encryption                        │
└─────────────────────────────────────────────────────────┘
```

### 4.2 Encryption Implementation

#### **Algorithm**: ChaCha20-Poly1305

**Why ChaCha20-Poly1305?**
- ✅ AEAD (Authenticated Encryption with Associated Data)
- ✅ Fast on all CPUs (no AES-NI dependency)
- ✅ 256-bit key, 96-bit nonce, 128-bit auth tag
- ✅ Industry standard (TLS 1.3, WireGuard, Signal)
- ✅ Constant-time (resistant to timing attacks)

**Properties**:
| Property | Value | Benefit |
|----------|-------|---------|
| Confidentiality | ChaCha20 stream cipher | Data unreadable without key |
| Integrity | Poly1305 MAC | Detects tampering/corruption |
| Authentication | AEAD construction | Prevents forgery |
| Nonce Size | 96 bits (12 bytes) | Safe for random generation |
| Key Size | 256 bits (32 bytes) | NIST recommended |

#### **Key Derivation**: PBKDF2-HMAC-SHA256

```python
# Master key (32 bytes, from environment)
master_key = base64.b64decode(os.getenv("CHECKPOINT_ENCRYPTION_KEY"))

# Derive per-session key
session_key = PBKDF2HMAC(
    algorithm=hashes.SHA256(),
    length=32,                     # 256-bit key
    salt=session_id.encode(),      # session_id as salt
    iterations=100_000,            # OWASP recommended minimum
).derive(master_key)
```

**Why PBKDF2?**
- ✅ Derives unique key per session from single master key
- ✅ Deterministic (same session_id → same key)
- ✅ One-way (can't recover master key from derived key)
- ✅ 100k iterations provides computational cost

**Session Isolation**:
```
Master Key: <32-byte secret>

Session A: !room1:main:@alice
  └─ Derived Key A = PBKDF2(master, "!room1:main:@alice")
     └─ Can decrypt checkpoints for Session A only

Session B: !room1:main:@bob
  └─ Derived Key B = PBKDF2(master, "!room1:main:@bob")
     └─ Can decrypt checkpoints for Session B only
     └─ CANNOT decrypt Session A (different derived key)
```

#### **Encryption Process**

```python
# Python: EncryptedRedisSaver.aput()

def encrypt_checkpoint(session_id: str, checkpoint_data: dict) -> bytes:
    """Encrypt checkpoint for storage in Redis."""

    # 1. Serialize checkpoint to JSON
    plaintext_json = json.dumps(checkpoint_data)
    plaintext_bytes = plaintext_json.encode('utf-8')

    # 2. Derive session-specific key
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=session_id.encode('utf-8'),
        iterations=100_000,
    )
    session_key = kdf.derive(MASTER_KEY)

    # 3. Generate random nonce (96 bits)
    nonce = os.urandom(12)  # Cryptographically secure random

    # 4. Encrypt with ChaCha20-Poly1305
    cipher = ChaCha20Poly1305(session_key)
    ciphertext_with_tag = cipher.encrypt(
        nonce=nonce,
        data=plaintext_bytes,
        associated_data=None
    )
    # ciphertext_with_tag = ciphertext || 16-byte Poly1305 tag

    # 5. Prepend nonce to ciphertext
    encrypted_data = nonce + ciphertext_with_tag
    # Format: [12-byte nonce][ciphertext][16-byte tag]

    # 6. Base64 encode for Redis storage
    return base64.b64encode(encrypted_data).decode('ascii')
```

#### **Decryption Process**

```python
# Python: EncryptedRedisSaver.aget()

def decrypt_checkpoint(session_id: str, encrypted_b64: str) -> dict:
    """Decrypt checkpoint from Redis."""

    # 1. Decode base64
    encrypted_data = base64.b64decode(encrypted_b64)

    # 2. Split nonce and ciphertext+tag
    nonce = encrypted_data[:12]               # First 12 bytes
    ciphertext_with_tag = encrypted_data[12:] # Rest

    # 3. Derive same session key (deterministic)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=session_id.encode('utf-8'),
        iterations=100_000,
    )
    session_key = kdf.derive(MASTER_KEY)

    # 4. Decrypt with ChaCha20-Poly1305
    cipher = ChaCha20Poly1305(session_key)
    try:
        plaintext_bytes = cipher.decrypt(
            nonce=nonce,
            data=ciphertext_with_tag,
            associated_data=None
        )
        # Automatically verifies Poly1305 tag
        # Raises InvalidTag if tampered/corrupted
    except InvalidTag:
        raise ValueError("Checkpoint tampered or corrupted!")

    # 5. Deserialize JSON
    plaintext_json = plaintext_bytes.decode('utf-8')
    checkpoint_data = json.loads(plaintext_json)

    return checkpoint_data
```

### 4.3 Security Properties

| Property | Implementation | Verification |
|----------|----------------|--------------|
| **Confidentiality** | ChaCha20 | Data unreadable without key |
| **Integrity** | Poly1305 MAC | Tampering detected on decrypt |
| **Authentication** | AEAD | Forgery impossible |
| **Per-Session Keys** | PBKDF2 derivation | Sessions can't decrypt each other |
| **Nonce Uniqueness** | Random 96-bit | Collision probability ~2^-96 |
| **Key Storage** | Environment variable | Never written to Redis/disk |
| **Key Rotation** | Supported | Re-encrypt with new master key |

### 4.4 Threat Model

#### **✅ Protected Against**

| Threat | Impact | Protection |
|--------|--------|------------|
| **Redis RDB dump theft** | High | Checkpoints encrypted, useless without key |
| **Redis AOF persistence leak** | High | Encrypted data only |
| **Backup leaks** | High | Encrypted checkpoints in backups |
| **HITL long-term storage** | Medium | State encrypted during pause (hours/days) |
| **Insider (Redis admin)** | Medium | Can access Redis but can't decrypt |
| **Checkpoint tampering** | Low | Poly1305 MAC detects modification |
| **Session crossover** | Low | Per-session keys prevent decryption |

#### **⚠️ NOT Protected Against**

| Threat | Mitigation | Risk Level |
|--------|------------|------------|
| **Redis pubsub sniffing** | Use Redis TLS (`rediss://`) | Low (requires network access) |
| **Memory dumps during processing** | None (LLM needs plaintext) | Low (requires server compromise) |
| **Master key compromise** | Secure key storage (vault/KMS), rotation | Critical |
| **Matrix server compromise** | Use Matrix E2EE rooms | Depends on Matrix trust |

#### **Defense in Depth**

```
Layer 1: Network Security
├─ Redis TLS (rediss://) for transport encryption
└─ Firewall rules (restrict Redis access)

Layer 2: Application Encryption (THIS DOCUMENT)
├─ ChaCha20-Poly1305 for checkpoint encryption
├─ Per-session key derivation
└─ Authenticated encryption (tamper detection)

Layer 3: Key Management
├─ Master key in secrets manager (not .env)
├─ Key rotation every 90 days
└─ Audit logging of key access

Layer 4: Infrastructure Security
├─ Redis persistence encryption (optional: LUKS/dm-crypt)
├─ Encrypted backups
└─ Access controls (RBAC)
```

---

## 5. Implementation Details

### 5.1 Rust Bot: Room Context Fetching

**File**: `verji-vagent-bot/src/responders/verji_agent.rs`

```rust
impl VerjiAgentResponder {
    async fn fetch_room_context(
        &self,
        room: &Room,
        limit: usize,
    ) -> Result<Vec<RoomMessage>> {
        use matrix_sdk::room::MessagesOptions;

        // Fetch last N messages from Matrix room
        let options = MessagesOptions::backward()
            .limit(limit as u16);

        match room.messages(options).await {
            Ok(messages) => {
                let bot_user_id = std::env::var("MATRIX_USER")
                    .unwrap_or_default();

                let mut context = Vec::new();

                // Process in reverse order (chronological)
                for event in messages.chunk.iter().rev() {
                    if let Ok(msg_event) = event.event.deserialize() {
                        // Only include text messages
                        if let Some(text) = extract_text_content(&msg_event) {
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
}
```

**Key Points**:
- Fetches last N messages (configurable, default 20)
- Filters out non-text messages (images, etc.)
- Tags bot's own messages (`is_bot: true`)
- Returns chronological order
- Non-fatal errors (returns empty vec)

### 5.2 Python Graph: Encrypted Checkpoint Saver

**File**: `verji-vagent-graph/src/encrypted_checkpoint.py`

```python
class EncryptedRedisSaver(AsyncRedisSaver):
    """Redis checkpoint saver with transparent encryption."""

    def __init__(self, redis_client, checkpoint_ttl: int = 86400):
        super().__init__(redis_client)
        self.master_key = self._load_master_key()
        self.checkpoint_ttl = checkpoint_ttl

    def _load_master_key(self) -> bytes:
        """Load encryption key from environment."""
        key_b64 = os.getenv("CHECKPOINT_ENCRYPTION_KEY")
        if not key_b64:
            raise ValueError("CHECKPOINT_ENCRYPTION_KEY not set!")

        key = base64.b64decode(key_b64)
        if len(key) != 32:
            raise ValueError(f"Key must be 32 bytes, got {len(key)}")

        return key

    def _derive_thread_key(self, thread_id: str) -> bytes:
        """Derive per-session encryption key."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=thread_id.encode('utf-8'),
            iterations=100_000,
        )
        return kdf.derive(self.master_key)

    def _encrypt_data(self, thread_id: str, plaintext: bytes) -> bytes:
        """Encrypt with ChaCha20-Poly1305."""
        key = self._derive_thread_key(thread_id)
        cipher = ChaCha20Poly1305(key)
        nonce = os.urandom(12)
        ciphertext = cipher.encrypt(nonce, plaintext, None)
        return nonce + ciphertext

    def _decrypt_data(self, thread_id: str, encrypted: bytes) -> bytes:
        """Decrypt with ChaCha20-Poly1305."""
        key = self._derive_thread_key(thread_id)
        cipher = ChaCha20Poly1305(key)
        nonce = encrypted[:12]
        ciphertext = encrypted[12:]
        return cipher.decrypt(nonce, ciphertext, None)

    async def aput(self, config, checkpoint, metadata, new_versions):
        """Encrypt and save checkpoint."""
        thread_id = config["configurable"]["thread_id"]

        # Serialize
        checkpoint_json = json.dumps(checkpoint, default=str)
        plaintext = checkpoint_json.encode('utf-8')

        # Encrypt
        encrypted_data = self._encrypt_data(thread_id, plaintext)
        encrypted_b64 = base64.b64encode(encrypted_data).decode('ascii')

        # Wrap
        encrypted_checkpoint = {
            "_encrypted": True,
            "data": encrypted_b64,
        }

        # Save via parent
        return await super().aput(
            config,
            encrypted_checkpoint,
            {**metadata, "_encrypted": True},
            new_versions
        )

    async def aget(self, config):
        """Load and decrypt checkpoint."""
        thread_id = config["configurable"]["thread_id"]

        checkpoint_tuple = await super().aget(config)
        if not checkpoint_tuple:
            return None

        if checkpoint_tuple.metadata.get("_encrypted"):
            encrypted_b64 = checkpoint_tuple.checkpoint["data"]
            encrypted_data = base64.b64decode(encrypted_b64)

            # Decrypt
            plaintext = self._decrypt_data(thread_id, encrypted_data)

            # Deserialize
            checkpoint_json = plaintext.decode('utf-8')
            decrypted_checkpoint = json.loads(checkpoint_json)

            # Return with decrypted checkpoint
            return CheckpointTuple(
                config=checkpoint_tuple.config,
                checkpoint=decrypted_checkpoint,
                metadata=checkpoint_tuple.metadata,
                parent_config=checkpoint_tuple.parent_config,
                pending_writes=checkpoint_tuple.pending_writes,
            )

        return checkpoint_tuple
```

### 5.3 Python Graph: Agent with Room Context

**File**: `verji-vagent-graph/src/graph.py`

```python
class AgentState(TypedDict):
    """State for the agent workflow."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    request_id: str
    room_context: Optional[str]  # Ephemeral, not saved to checkpoint


class VerjiAgent:
    """LangGraph agent with room context and encrypted checkpoints."""

    async def _respond_node(self, state: AgentState) -> AgentState:
        """Generate response using LLM with room context."""

        # Build LLM input
        llm_messages = []

        # Add room context as system message (NOT saved to state)
        if state.get("room_context"):
            llm_messages.append(SystemMessage(content=state["room_context"]))

        # Add conversation messages (WILL be saved to checkpoint)
        llm_messages.extend(state["messages"])

        # Call LLM with both contexts
        response = await self.llm.ainvoke(llm_messages)

        # Save only AI response to state (not SystemMessage)
        state["messages"] = state["messages"] + [
            AIMessage(content=response.content)
        ]

        # ✅ room_context NOT in messages, won't be saved to checkpoint

        return state

    async def process(
        self,
        request_id: str,
        session_id: str,
        user_message: str,
        room_context: Optional[List[Dict]] = None,
    ) -> str:
        """Process message with room context and checkpoint."""

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
            "messages": [HumanMessage(content=user_message)],
            "request_id": request_id,
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

    def _format_room_context(self, room_context: List[Dict]) -> str:
        """Format room context into system message."""
        lines = ["Recent room discussion:", ""]

        for msg in room_context:
            sender_name = msg["sender"].split(":")[0].lstrip("@").title()
            if msg.get("is_bot"):
                sender_name = "Assistant"

            lines.append(f"{sender_name}: {msg['content']}")

        lines.extend([
            "",
            "Answer the user's question based on the above context."
        ])

        return "\n".join(lines)
```

**Critical Design Point**: `room_context` is a **non-reducer field** in `AgentState`:
- `messages` has `add_messages` annotation → Persists and accumulates
- `room_context` has NO annotation → Overwrites each time, not persisted
- Result: Room context is regenerated fresh, conversation persists

---

## 6. Security Analysis

### 6.1 Data Classification

| Data | Sensitivity | Encrypted? | Storage | Lifetime |
|------|-------------|------------|---------|----------|
| Room context (fetch) | Medium | Matrix E2EE | Matrix server | Permanent |
| Room context (request) | Medium | No | Redis pubsub (ephemeral) | Seconds |
| User query | High | No | Redis pubsub (ephemeral) | Seconds |
| Conversation history | High | Yes (ChaCha20) | Redis keys | 24h |
| AI responses | High | Yes (ChaCha20) | Redis keys | 24h |
| Tool results | High | Yes (ChaCha20) | Redis keys | 24h |
| HITL state | High | Yes (ChaCha20) | Redis keys | 24h |
| Progress messages | Low | No | Redis pubsub (ephemeral) | Seconds |
| Encryption key | Critical | No | Environment variable | Permanent |

### 6.2 Compliance Considerations

#### **GDPR Requirements**

| Requirement | Implementation | Status |
|-------------|----------------|--------|
| **Encryption at rest** (Art. 32) | ChaCha20-Poly1305 for checkpoints | ✅ Compliant |
| **Data minimization** (Art. 5) | 24h TTL on checkpoints | ✅ Compliant |
| **Right to erasure** (Art. 17) | Need deletion API | ⚠️ TODO |
| **Data portability** (Art. 20) | Need export API | ⚠️ TODO |
| **Processing records** (Art. 30) | Need audit logging | ⚠️ TODO |

**Required Additions**:
```python
# DELETE /api/v1/session/{session_id}
async def delete_session(session_id: str):
    """Delete all data for a session (right to erasure)."""
    await redis.delete(f"checkpoint:{session_id}:*")
    return {"deleted": True}

# GET /api/v1/session/{session_id}/export
async def export_session(session_id: str):
    """Export session data (right to portability)."""
    checkpoint = await checkpointer.aget(config)
    return {"session_id": session_id, "data": checkpoint}
```

#### **SOC 2 Controls**

| Control | Implementation | Status |
|---------|----------------|--------|
| **CC6.1** Key Management | Master key in environment, rotation | ✅ |
| **CC6.7** Encryption at rest | ChaCha20-Poly1305 | ✅ |
| **CC7.2** Access logging | Need audit trail | ⚠️ TODO |

---

## 7. Configuration

### 7.1 Environment Variables

```bash
# .env (project root)

# ============================================================================
# Checkpoint Encryption (REQUIRED)
# ============================================================================
# Generate with: openssl rand -base64 32
# CRITICAL: Store in vault/KMS in production, not .env file
CHECKPOINT_ENCRYPTION_KEY=your-32-byte-base64-key-here

# Checkpoint TTL (seconds, default 24 hours)
CHECKPOINT_TTL=86400

# ============================================================================
# Room Context
# ============================================================================
# Number of recent room messages to fetch for context
ROOM_CONTEXT_LIMIT=20

# Optional: Max age of room messages (seconds)
# Only include messages from last N seconds
# ROOM_CONTEXT_MAX_AGE=86400

# ============================================================================
# Redis Configuration
# ============================================================================
REDIS_URL=redis://localhost:6379
# For production with TLS (recommended):
# REDIS_URL=rediss://redis.example.com:6379
```

### 7.2 Key Management

#### **Key Generation**

```bash
# Generate secure 32-byte encryption key
openssl rand -base64 32

# Output example:
# kX9v2+Jq8P7mN4wL1cR6tY5uS3hG8fD2aQ9zE4bV1xK=

# Add to .env (development) or secrets manager (production)
```

#### **Production Key Storage**

**❌ DON'T**: Store in `.env` file in production
**✅ DO**: Use secrets manager

```bash
# AWS Secrets Manager
aws secretsmanager create-secret \
  --name prod/verji/checkpoint-encryption-key \
  --secret-string "$(openssl rand -base64 32)"

# HashiCorp Vault
vault kv put secret/verji/checkpoint-key \
  value="$(openssl rand -base64 32)"

# Azure Key Vault
az keyvault secret set \
  --vault-name verji-vault \
  --name checkpoint-encryption-key \
  --value "$(openssl rand -base64 32)"
```

#### **Key Rotation**

```bash
#!/bin/bash
# scripts/rotate_checkpoint_keys.sh

# 1. Generate new key
NEW_KEY=$(openssl rand -base64 32)

# 2. Deploy with both keys
export CHECKPOINT_ENCRYPTION_KEY=$NEW_KEY
export OLD_CHECKPOINT_ENCRYPTION_KEY=$OLD_KEY

# 3. Run migration (decrypt with old, re-encrypt with new)
python scripts/migrate_checkpoints.py

# 4. Verify
python scripts/verify_encryption.py

# 5. Remove old key
unset OLD_CHECKPOINT_ENCRYPTION_KEY
```

**Rotation Frequency**: Every 90 days (recommended)

---

## Appendix: Testing Checklist

### Encryption Tests

- [ ] `test_encrypt_decrypt_cycle()` - Basic encryption works
- [ ] `test_session_isolation()` - Sessions can't decrypt each other
- [ ] `test_tampering_detection()` - Poly1305 detects modifications
- [ ] `test_checkpoint_encrypted_on_disk()` - Verify Redis contains encrypted data

### Context Tests

- [ ] `test_room_context_not_in_checkpoint()` - Room context excluded from checkpoint
- [ ] `test_room_context_refreshes()` - Room context is fresh on each query
- [ ] `test_conversation_persists()` - Checkpoint survives across messages
- [ ] `test_checkpoint_ttl()` - Checkpoint expires after 24h

### Integration Tests

- [ ] `test_full_conversation_flow()` - End-to-end with room context + checkpoint
- [ ] `test_bot_restart_recovery()` - Conversation survives bot restart
- [ ] `test_hitl_with_encrypted_checkpoint()` - HITL pause/resume works

---

**Status**: Ready for implementation
**Next Steps**: See main implementation plan for week-by-week tasks
