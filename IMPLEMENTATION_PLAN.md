# Implementation Plan: Conversation Context, Encryption & Tool Management

**Status**: Ready for Implementation
**Version**: 2.0
**Date**: 2025-01-18
**Estimated Duration**: 4 weeks

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture Summary](#2-architecture-summary)
3. [Implementation Phases](#3-implementation-phases)
4. [Week-by-Week Timeline](#4-week-by-week-timeline)
5. [Success Criteria](#5-success-criteria)
6. [Risk Mitigation](#6-risk-mitigation)

---

## 1. Overview

### What We're Building

A production-ready AI agent with:

1. **Dual Context System**
   - Room context: Recent discussion from all users (ephemeral)
   - Conversation history: Personal chat with bot (persistent, encrypted)

2. **Encrypted Checkpoint Storage**
   - ChaCha20-Poly1305 AEAD encryption
   - Per-session key isolation
   - 24-hour TTL on conversation state

3. **LangGraph Tool Management**
   - Automatic tool execution via ToolNode
   - RBAC-filtered tool access
   - HITL approval for dangerous operations
   - Progress reporting at each step

4. **Complete RBAC Integration**
   - Tool filtering before LLM sees them
   - Credential injection from Credential Registry
   - Audit logging for all access decisions

### What Changed from Original POC

| Component | Current (POC) | After Implementation |
|-----------|---------------|---------------------|
| **Context** | Single user query | Room context + conversation history |
| **Memory** | None (stateless) | 24h encrypted checkpoint memory |
| **Security** | No encryption | ChaCha20-Poly1305 encrypted at rest |
| **Tools** | None | RBAC-filtered tools with ToolNode |
| **HITL** | Not implemented | Checkpoint-based HITL approval |
| **Progress** | Basic 3-step demo | Real-time progress from each node |

### Current State

✅ **Complete**:
- Matrix bot with Redis pubsub communication
- Python LangGraph agent with OpenAI integration
- Basic 3-step progress reporting
- Session ID structure defined

⚠️ **TODO**:
- Room context fetching from Matrix
- Encrypted checkpoint storage
- Tool management with RBAC
- HITL workflow
- Multi-turn conversation memory

---

## 2. Architecture Summary

### Data Flow (After Implementation)

```
┌─────────────────────────────────────────────────────────────────┐
│  USER SENDS MESSAGE IN MATRIX ROOM                              │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ↓
┌─────────────────────────────────────────────────────────────────┐
│  RUST BOT (verji-vagent-bot)                                    │
├─────────────────────────────────────────────────────────────────┤
│  1. Fetch room context (last 20 messages from Matrix)           │
│  2. Build session_id: {room_id}:{thread_id}:{user_id}          │
│  3. Get AcContext from AccessControlProvider                    │
│  4. Publish to Redis pubsub:                                    │
│     {                                                            │
│       "session_id": "!room:main:@user",                         │
│       "query": "user message",                                  │
│       "room_context": [20 messages],                            │
│       "ac_context": {roles, permissions}                        │
│     }                                                            │
└─────────────────────┬───────────────────────────────────────────┘
                      │ Redis Pubsub (ephemeral)
                      ↓
┌─────────────────────────────────────────────────────────────────┐
│  PYTHON GRAPH (verji-vagent-graph)                              │
├─────────────────────────────────────────────────────────────────┤
│  Node 1: Filter Tools                                           │
│    - Parse AcContext                                            │
│    - Filter tools based on permissions                          │
│    - Bind filtered tools to LLM                                 │
│    - Emit: "🔍 Checking permissions..."                         │
│                                                                  │
│  Node 2: Agent Reasoning                                        │
│    - Load checkpoint (encrypted, from Redis)                    │
│    - Build context: room + conversation history                 │
│    - LLM decides: answer directly or call tools                 │
│    - Emit: "🧠 Thinking..."                                      │
│                                                                  │
│  Conditional Routing:                                           │
│    - No tool calls → END (return response)                      │
│    - Tool calls (safe) → Node 3                                 │
│    - Tool calls (dangerous) → Node 4                            │
│                                                                  │
│  Node 3: Execute Tools (ToolNode)                               │
│    - Automatically parse tool_calls                             │
│    - Execute tools in parallel                                  │
│    - Wrap results in ToolMessages                               │
│    - Loop back to Node 2                                        │
│                                                                  │
│  Node 4: HITL Approval                                          │
│    - Emit: "⚠️ Approval needed: delete_records(...)"           │
│    - Save checkpoint (encrypted)                                │
│    - EXIT (wait for user approval)                              │
│                                                                  │
│  Checkpoint Save (After Every Node):                            │
│    - Serialize state (messages, tool results)                   │
│    - Encrypt with ChaCha20-Poly1305                             │
│    - Store in Redis with 24h TTL                                │
└─────────────────────┬───────────────────────────────────────────┘
                      │ Redis Pubsub (ephemeral)
                      ↓
┌─────────────────────────────────────────────────────────────────┐
│  RUST BOT (verji-vagent-bot)                                    │
├─────────────────────────────────────────────────────────────────┤
│  5. Receive response via pubsub                                 │
│  6. Send to Matrix room                                         │
│  7. Check for pending HITL (if response type is hitl_request)   │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Single encryption layer (Python)** | Checkpoints are source of truth, simpler implementation |
| **Room context ephemeral** | Always fresh, doesn't bloat checkpoints, fetched from Matrix |
| **ToolNode for execution** | Automatic tool parsing/execution, maintains RBAC control |
| **Manual graph (not create_react_agent)** | Need custom RBAC, HITL, progress reporting |
| **ChaCha20-Poly1305** | Fast, authenticated, constant-time, industry standard |
| **PBKDF2 key derivation** | Per-session isolation, deterministic, one-way |

---

## 3. Implementation Phases

### Phase 1: Encryption Infrastructure (Week 1)

**Goal**: Implement encrypted checkpoint storage in Python

**Deliverables**:
- `EncryptedRedisSaver` class extending `AsyncRedisSaver`
- ChaCha20-Poly1305 encryption/decryption methods
- PBKDF2 key derivation per session
- Unit tests for encryption correctness
- Environment configuration for master key

**Files to Create/Modify**:
- NEW: `verji-vagent-graph/src/encrypted_checkpoint.py`
- MODIFY: `verji-vagent-graph/src/main.py` (use EncryptedRedisSaver)
- MODIFY: `.env.example` (add CHECKPOINT_ENCRYPTION_KEY)

**Success Criteria**:
- ✅ Checkpoint encrypted in Redis (verify with `redis-cli GET checkpoint:*`)
- ✅ Decrypt-encrypt cycle produces identical checkpoint
- ✅ Different sessions cannot decrypt each other's checkpoints
- ✅ Tampering detected (Poly1305 MAC verification fails)

### Phase 2: Room Context Fetching (Week 1-2)

**Goal**: Fetch room context from Matrix and pass to Graph

**Deliverables**:
- Rust function to fetch last N messages from Matrix room
- `RoomMessage` struct for serialization
- Integration with existing `query_with_streaming()`
- Configuration for room context limit

**Files to Create/Modify**:
- MODIFY: `verji-vagent-bot/src/types.rs` (add RoomMessage struct)
- MODIFY: `verji-vagent-bot/src/responders/verji_agent.rs` (fetch room context)
- MODIFY: `verji-vagent-bot/src/redis_client.rs` (include room_context in request)
- MODIFY: `.env.example` (add ROOM_CONTEXT_LIMIT)

**Success Criteria**:
- ✅ Bot fetches last 20 messages from Matrix room
- ✅ Room context included in Redis pubsub request
- ✅ Graph receives room_context in request payload
- ✅ Bot filters out non-text messages (images, etc.)

### Phase 3: LangGraph Tool Management (Week 2)

**Goal**: Implement RBAC-filtered tool execution with ToolNode

**Deliverables**:
- Updated `AgentState` with ac_context, room_context, available_tools
- Filter tools node (RBAC check)
- Agent node (LLM reasoning)
- ToolNode integration (automatic execution)
- Conditional routing (tools vs end)
- Mock tools for testing (search_database, send_email)

**Files to Create/Modify**:
- MODIFY: `verji-vagent-graph/src/graph.py` (rebuild workflow)
- NEW: `verji-vagent-graph/src/tools/` (tool implementations)
- NEW: `verji-vagent-graph/src/rbac.py` (RBAC checking logic)
- MODIFY: `verji-vagent-graph/pyproject.toml` (add langgraph.prebuilt)

**Success Criteria**:
- ✅ LLM only sees tools user has access to
- ✅ ToolNode automatically executes tool calls
- ✅ Tool results appear as ToolMessages in checkpoint
- ✅ Graph loops back to agent after tool execution
- ✅ User without tool access gets "Permission denied" message

### Phase 4: Multi-Turn Conversation & HITL (Week 3)

**Goal**: Enable conversation memory and HITL approval workflow

**Deliverables**:
- Room context formatting as SystemMessage
- Conversation history from checkpoint
- HITL node for dangerous tool approval
- Bot logic to detect HITL responses
- Checkpoint resume after approval

**Files to Create/Modify**:
- MODIFY: `verji-vagent-graph/src/graph.py` (add hitl_node, room context logic)
- MODIFY: `verji-vagent-bot/src/responders/verji_agent.rs` (detect HITL responses)
- NEW: `verji-vagent-bot/src/hitl.rs` (HITL state tracking)

**Success Criteria**:
- ✅ Bot remembers previous conversation across messages
- ✅ Room context appears in LLM prompt but not checkpoint
- ✅ Dangerous tool triggers HITL approval request
- ✅ User can approve/deny action
- ✅ Graph resumes from checkpoint after approval

### Phase 5: Testing & Documentation (Week 4)

**Goal**: Comprehensive testing and production readiness

**Deliverables**:
- Unit tests for encryption
- Unit tests for RBAC filtering
- Integration tests for full conversation flow
- Integration tests for HITL workflow
- Performance testing (checkpoint size, encryption speed)
- Production deployment guide
- Key rotation procedures

**Files to Create**:
- NEW: `verji-vagent-graph/tests/test_encryption.py`
- NEW: `verji-vagent-graph/tests/test_rbac.py`
- NEW: `tests/integration/test_conversation_memory.py`
- NEW: `tests/integration/test_hitl_workflow.py`
- NEW: `docs/DEPLOYMENT.md`
- NEW: `scripts/rotate_checkpoint_keys.sh`

**Success Criteria**:
- ✅ All unit tests pass (>95% coverage)
- ✅ All integration tests pass
- ✅ Checkpoint encryption verified on Redis disk
- ✅ Performance acceptable (<100ms encryption overhead)
- ✅ Documentation complete and reviewed

---

## 4. Week-by-Week Timeline

### Week 1: Encryption & Context

**Days 1-2: Encryption Infrastructure**
- [ ] Implement `EncryptedRedisSaver` class
- [ ] Add ChaCha20-Poly1305 encryption methods
- [ ] Add PBKDF2 key derivation
- [ ] Write encryption unit tests
- [ ] Generate and configure master key

**Days 3-4: Room Context Fetching**
- [ ] Add `RoomMessage` struct in Rust
- [ ] Implement `fetch_room_context()` in bot
- [ ] Integrate room context in Redis request
- [ ] Test room context retrieval

**Day 5: Integration & Testing**
- [ ] Test encrypted checkpoints in Redis
- [ ] Test room context end-to-end
- [ ] Verify checkpoint persistence across bot restarts

### Week 2: Tool Management

**Days 1-2: Tool Infrastructure**
- [ ] Update `AgentState` with new fields
- [ ] Implement `filter_tools_node`
- [ ] Implement `_has_tool_access` RBAC logic
- [ ] Create mock tools (search, email, delete)

**Days 3-4: ToolNode Integration**
- [ ] Rebuild LangGraph workflow with ToolNode
- [ ] Implement `agent_node` with room context
- [ ] Add conditional routing (`_should_continue`)
- [ ] Test tool execution loop

**Day 5: Testing & Refinement**
- [ ] Test RBAC filtering (user with/without access)
- [ ] Test parallel tool execution
- [ ] Test tool error handling
- [ ] Fix any issues

### Week 3: Conversation Memory & HITL

**Days 1-2: Conversation Memory**
- [ ] Format room context as SystemMessage
- [ ] Ensure checkpoint excludes SystemMessage
- [ ] Test multi-turn conversations
- [ ] Verify checkpoint TTL expiration

**Days 3-4: HITL Workflow**
- [ ] Implement `hitl_node` in Graph
- [ ] Implement HITL detection in Rust bot
- [ ] Create `hitl.rs` module
- [ ] Test HITL approval/denial flow

**Day 5: Integration Testing**
- [ ] Test full conversation flow with tools
- [ ] Test HITL with encrypted checkpoint resume
- [ ] Test edge cases (timeout, invalid approval)

### Week 4: Testing & Production Readiness

**Days 1-2: Comprehensive Testing**
- [ ] Write all unit tests
- [ ] Write all integration tests
- [ ] Run performance benchmarks
- [ ] Verify encryption on Redis disk

**Days 3-4: Documentation & Procedures**
- [ ] Write deployment guide
- [ ] Document key rotation procedure
- [ ] Create monitoring/alerting guide
- [ ] Review security checklist

**Day 5: Final Review & Deployment**
- [ ] Code review
- [ ] Security review
- [ ] Deploy to staging environment
- [ ] User acceptance testing
- [ ] Go/no-go decision for production

---

## 5. Success Criteria

### Functional Requirements

- [ ] **Dual Context**: Bot sees room discussion AND remembers personal conversations
- [ ] **Encryption**: All checkpoints encrypted at rest in Redis
- [ ] **Tool Management**: LLM only sees tools user has access to
- [ ] **HITL**: Dangerous tools require user approval before execution
- [ ] **Progress**: Real-time progress updates in Matrix room
- [ ] **TTL**: Checkpoints expire after 24 hours
- [ ] **Session Isolation**: Different users/rooms have separate checkpoints

### Non-Functional Requirements

- [ ] **Performance**: <500ms total latency for query (excluding LLM call)
- [ ] **Encryption Overhead**: <100ms for encrypt/decrypt operations
- [ ] **Memory**: Checkpoint size <100KB per session
- [ ] **Reliability**: Bot recovers from Redis/Matrix failures gracefully
- [ ] **Security**: Encryption verified, key rotation tested
- [ ] **Maintainability**: >90% code coverage, comprehensive docs

### User Experience

- [ ] User sees room context reflected in bot responses
- [ ] User can have multi-turn conversations with context
- [ ] User gets clear HITL approval prompts
- [ ] User sees progress at each workflow step
- [ ] User can continue conversation after bot restart

---

## 6. Risk Mitigation

### Technical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Checkpoint size too large** | High | Medium | Implement max message limit (e.g., 50 messages), test with long conversations |
| **Encryption performance** | Medium | Low | Benchmark early, optimize if needed (consider caching derived keys) |
| **ToolNode compatibility** | High | Low | Test with mock tools early, read LangGraph docs thoroughly |
| **HITL race conditions** | High | Medium | Implement proper locking in Redis, test concurrent requests |
| **Room context bloat** | Low | Medium | Limit to 20 messages, filter out large attachments |

### Security Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Master key compromise** | Critical | Low | Use secrets manager (Vault/KMS), never commit key to git, rotate every 90 days |
| **Redis pubsub sniffing** | Medium | Low | Use Redis TLS (`rediss://`), network segmentation |
| **Checkpoint tampering** | Medium | Very Low | Poly1305 MAC detects tampering, alert on verification failures |
| **Session crossover** | High | Very Low | Per-session key derivation prevents decryption, test session isolation |

### Operational Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Key rotation downtime** | High | Low | Implement dual-key migration, test rotation procedure |
| **Redis disk full** | High | Medium | Monitor disk usage, alert at 80%, implement checkpoint cleanup |
| **Bot restart loses context** | Low | High | Checkpoints survive restarts (tested in Phase 4) |
| **Matrix API rate limits** | Medium | Medium | Implement exponential backoff, cache room context |

---

## Appendix: Implementation Checklist

### Before Starting

- [ ] Read [CONTEXT_AND_ENCRYPTION.md](./CONTEXT_AND_ENCRYPTION.md) completely
- [ ] Review [CLAUDE.md](./CLAUDE.md) for project guidelines
- [ ] Ensure Tilt environment is running (`tilt up`)
- [ ] Verify OpenAI API key is configured
- [ ] Generate and set `CHECKPOINT_ENCRYPTION_KEY` in `.env`

### During Implementation

- [ ] Write tests BEFORE implementation (TDD approach)
- [ ] Commit after each completed task (atomic commits)
- [ ] Update [CHANGELOG.md](./CHANGELOG.md) weekly
- [ ] Run integration tests daily
- [ ] Monitor Tilt logs for errors

### After Completion

- [ ] All tests passing (unit + integration)
- [ ] Documentation reviewed and updated
- [ ] Security checklist completed
- [ ] Performance benchmarks recorded
- [ ] Deployment guide tested in staging
- [ ] User acceptance testing passed

---

**Ready to Start?** Begin with Week 1, Day 1: Encryption Infrastructure.

Refer to [CONTEXT_AND_ENCRYPTION.md](./CONTEXT_AND_ENCRYPTION.md) for detailed implementation examples and code snippets.
