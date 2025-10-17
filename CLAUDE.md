# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Verji AI Agent is a production-ready Matrix chatbot combining Rust (matrix-rust-sdk) and Python (LangGraph) for intelligent, human-in-the-loop conversational AI.

**Architecture:**
- **Verji vAgent Bot** (`verji-vagent-bot/`): Matrix client handling message events, RBAC enforcement, session management, and HITL coordination
- **Verji vAgent Graph** (`verji-vagent-graph/`): LangGraph-based AI workflow orchestration with LLM integration and fine-grained access control
- **Redis**: Shared state store for sessions, checkpoints, and HITL tracking
- **HTTP/JSON**: Simple, debuggable communication between services with Server-Sent Events (SSE) for streaming
- **AccessControlProvider**: External RBAC service for authentication and authorization
- **Credential Registry**: User-specific credentials for external tools (to be built)

## Development Commands

### Primary Development Workflow (Tilt + Kubernetes)

**Tilt is the recommended way to develop locally** with hot reload and live updates.

```bash
# Prerequisites: minikube or kind cluster running
minikube start
# or: kind create cluster

# Copy environment variables
cp .env.example .env
# Edit .env with your Matrix credentials and API keys

# Start Tilt - this starts all services with hot reload
tilt up

# Tilt UI automatically opens at http://localhost:10350
# Features:
# - Python hot reload: < 1 sec (no rebuild needed)
# - Rust incremental compile: ~15 sec
# - Unified logs, metrics, and health status
# - Manual trigger buttons for common tasks

# Stop Tilt
tilt down
```

**Useful Tilt UI buttons:**
- **integration-tests**: Run full integration test suite
- **redis-flush**: Clear Redis cache/state
- **api-docs**: Open FastAPI Swagger documentation for the Graph API

**Edit workflow:**
1. Edit Python files → changes sync and reload automatically in < 1 sec
2. Edit Rust files → changes sync, incremental recompile in ~15 sec
3. View logs from all services in unified dashboard
4. No need to manually restart anything

### Running Tests

#### Unit Tests
```bash
# Rust tests
cd verji-vagent-bot
cargo test

# Python tests
cd verji-vagent-graph
poetry run pytest
```

#### Integration Tests
```bash
# Option 1: Click "integration-tests" button in Tilt UI (recommended)
# Option 2: Run manually (requires services running)
./scripts/test-integration.sh
```

### Code Quality

```bash
# Rust
cd verji-vagent-bot
cargo fmt                # Format code
cargo clippy             # Lint

# Python
cd verji-vagent-graph
poetry run black .       # Format code
poetry run ruff check .  # Lint
poetry run mypy src/     # Type check
```

### Alternative: Docker Compose (Production Deployment Only)

**⚠️ Docker Compose is NOT for local development** - use Tilt instead!

Docker Compose is only for:
- Production deployment
- Testing production builds
- CI/CD pipelines

```bash
# Production deployment
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

**When to use Docker Compose vs Tilt:**
- **Tilt**: All local development (hot reload, fast feedback, live debugging)
- **Docker Compose**: Production deployment, testing production builds before release

## Architecture & Design Principles

### Service Communication
- **HTTP/JSON + SSE** is used for all Rust ↔ Python communication (NOT gRPC/Protobuf or WebSocket/JSON-RPC)
- **Rationale**: No performance bottleneck (LLM calls dominate latency), better debuggability, no code generation, ecosystem alignment
- Services run as **separate containers** (no spawning/forking)
- Both services (`verji-vagent-bot` and `verji-vagent-graph`) connect to shared **Redis** instance
- API defined in `verji-vagent-graph` using FastAPI with Server-Sent Events for streaming responses

### Session Management
Sessions use hierarchical IDs: `{room_id}:{thread_id}:{user_id}`

Examples:
- Main room: `!abc123:matrix.org:main:@user:matrix.org`
- Threaded: `!abc123:matrix.org:$thread456:@user:matrix.org`

**Redis keys:**
- Session state: `session:{session_id}`
- HITL pending: `hitl_pending:{session_id}`
- LangGraph checkpoints: Managed by LangGraph's Redis checkpointer

### Role-Based Access Control (RBAC)

Multi-layer RBAC enforces access to agents, tools, and documents:

**Layer 1: Bot (Coarse-Grained)**
- Validates user has access to agent via AccessControlProvider
- Gets `AcContext` with user's roles and accessible resource instances
- Silent denial if user lacks agent access (bot doesn't respond)
- Passes full `AcContext` to Graph in request body

**Layer 2: Graph (Fine-Grained)**
- Filters tools BEFORE LLM sees them (LLM only sees allowed tools)
- Enforces tool invocation access (defense in depth)
- Filters RAG documents by IDs, categories, and tags
- Calls Credential Registry for user-specific tool credentials

**Resource Naming:**
- Agents: `agent:verji_ai_agent`
- Tools: `tool:database_query`
- Documents: `document:doc_123`, `document_category:finance`, `document_tag:confidential`
- Entities (GraphRAG): `entity:customer_456`, `entity_type:customer`

**Key Points:**
- `AcContext.ActiveRoles` must be used for all access decisions
- AccessControlProvider handles its own caching (don't cache AcContext in Redis)
- Domain/tenant derived from Matrix room state event
- SuperUser bypasses all checks (reflected in roles/permissions)

### Human-in-the-Loop (HITL) Pattern

HITL asks the **same user** for clarification, confirmation, or additional input during workflow execution:

1. **verji-vagent-graph** reaches HITL node → saves checkpoint → streams `hitl_request` event via SSE → closes stream
2. **verji-vagent-bot** receives event, stores in Redis (`hitl_pending:{session_id}`)
3. **verji-vagent-bot** asks **user in same room**: "Confirm delete 1000 records? (yes/no)"
4. **User** responds: "yes" (seconds or minutes later)
5. **verji-vagent-bot** detects pending HITL, validates response, POSTs to `/api/v1/submit_feedback`
6. **verji-vagent-graph** loads checkpoint, resumes workflow, completes action

**Key points:**
- HITL asks the **user**, not a third-party admin
- Graph checkpoints and exits (doesn't block waiting for response)
- Bot checks Redis on every message to detect HITL responses
- Timeout: default 1 hour (configurable per request)
- After timeout, user's next message treated as new query

### State Persistence
- **Session state**: Redis with 24-hour TTL
- **LangGraph checkpoints**: Redis via `langgraph.checkpoint.redis.RedisSaver`
- **In-memory cache**: verji-vagent-bot maintains local cache of active sessions

## Code Structure

### HTTP API (verji-vagent-graph)
REST API with Server-Sent Events for streaming:
- `POST /api/v1/process_message`: Send message to LangGraph workflow, returns SSE stream
- `POST /api/v1/submit_feedback`: Submit HITL feedback
- `GET /health`: Health check endpoint
- `GET /docs`: FastAPI Swagger documentation

**Message types** (JSON schemas enforced via Rust structs and Python dataclasses):
- `BotMessage`, `BotResponse`, `HITLRequest`, `TextMessage`, `StreamChunk`, `ErrorMessage`

### Verji vAgent Bot Architecture (verji-vagent-bot/)
Expected modules (refer to [ARCHITECTURE.md](./ARCHITECTURE.md) for detailed examples):
- `main.rs`: Entry point, Matrix client setup, event loop
- `types.rs`: Shared JSON message types (serde)
- `session.rs`: Session management, Redis operations
- `rbac.rs`: AccessControlProvider integration, AcContext handling
- `hitl.rs`: HITL coordination, user response detection
- `http_client.rs`: HTTP/SSE client to verji-vagent-graph service

### Verji vAgent Graph Architecture (verji-vagent-graph/)
Expected modules:
- `main.py`: Entry point, FastAPI server startup
- `types.py`: Shared JSON message types (Pydantic/dataclasses)
- `api.py`: FastAPI route handlers with SSE streaming
- `session_manager.py`: Redis session operations
- `rbac.py`: RBAC enforcement, tool filtering, document filtering
- `credential_registry.py`: Client for Credential Registry service
- `langgraph_workflow.py`: LangGraph workflow definitions with HITL nodes

### LangGraph Workflow Pattern
LangGraph workflows should:
- Use `State` TypedDict with `session_id`, `ac_context`, `messages`, `available_tools`, `proposed_action`, `hitl_response`
- First node: Parse `AcContext` from request, filter available tools
- Planning node: Use filtered `available_tools` list (LLM only sees allowed tools)
- Tool invocation: Check access, get credentials from Credential Registry if needed
- HITL node: Send `hitl_request` event, checkpoint, and exit (don't wait)
- RAG node: Filter documents based on `AcContext` (IDs, categories, tags)
- Use Redis checkpointer: `RedisSaver(session_manager.redis)`

## Environment Configuration

Copy `.env.example` to `.env` and configure:

**Required:**
- `MATRIX_HOMESERVER`: Matrix server URL
- `MATRIX_USER`: Bot username (e.g., `@bot:matrix.org`)
- `MATRIX_PASSWORD`: Bot password
- `REDIS_URL`: Redis connection string
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`: LLM API keys
- `ACCESS_CONTROL_PROVIDER_URL`: AccessControlProvider service endpoint
- `CREDENTIAL_REGISTRY_URL`: Credential Registry service endpoint (when available)

**Optional:**
- `GRAPH_API_ENDPOINT`: verji-vagent-graph service endpoint (default: `http://verji-vagent-graph:8000`)
- `HTTP_PORT`: Python service port (default: `8000`)
- `RUST_LOG`: Rust logging level (default: `info,matrix_sdk=warn`)
- `LOG_LEVEL`: Python logging level (default: `info`)

## Deployment Architecture

**Services are deployed separately** (not spawned/forked):

```
Redis Container ← → verji-vagent-graph Container (HTTP :8000)
                    ↑ (HTTP/JSON + SSE)
                    verji-vagent-bot Container
```

Benefits:
- Independent restarts and scaling
- Clear resource limits per service
- Docker/K8s health checks per service
- Language-specific optimal runtimes

**Startup order:**
1. Redis
2. verji-vagent-graph (starts HTTP server on `:8000`)
3. verji-vagent-bot (connects to verji-vagent-graph and Matrix)

## Key Technical Details

### HTTP/JSON Communication
- **Server-Sent Events (SSE)**: Used for streaming responses including HITL flows
- **Human-readable**: JSON messages are easy to debug in logs and with `curl`
- **Connection**: verji-vagent-bot is HTTP client, verji-vagent-graph is HTTP/SSE server
- **Error handling**: Use standard HTTP status codes and JSON error responses
- **No code generation**: Direct serde/Pydantic usage for type safety within each service

### Redis Usage
1. **Session storage**: Persist session state with TTL
2. **LangGraph checkpoints**: Enable graph resumption after HITL
3. **HITL tracking**: Store pending HITL requests (`hitl_pending:{session_id}`)
4. **NOT used for**: AcContext caching (AccessControlProvider handles caching)

### Matrix Integration
- Uses `matrix-rust-sdk` 0.7
- Bot must be invited to rooms where it should respond
- Ignores its own messages (check `event.sender`)
- Supports threaded conversations via `relates_to.thread`
- Sends typing indicators during processing

## Testing Strategy

### Unit Tests
- **Rust**: Test session management, Redis operations, message parsing
  ```bash
  cd verji-vagent-bot && cargo test
  ```
- **Python**: Test LangGraph workflows, session manager, gRPC handlers
  ```bash
  cd verji-vagent-graph && poetry run pytest
  ```

### Integration Tests
Located in `tests/integration/`:
- `test_basic_flow.py`: End-to-end message flow
- `test_hitl_flow.py`: HITL approval workflow

**Run integration tests:**
```bash
# With Tilt running: Click "integration-tests" button in Tilt UI
# OR manually with services running:
tilt up  # Start services
./scripts/test-integration.sh
```

## Important Notes

- **Use Tilt for development**: Tilt is the primary development workflow, NOT Docker Compose
- **Docker Compose for production only**: Use docker-compose.yml for production deployment or testing production builds
- **Tiltfile is the source of truth**: For local development configuration, refer to the Tiltfile
- **Never spawn/fork services**: Each service runs independently in its own container
- **HTTP/JSON not gRPC**: Services communicate via HTTP/JSON + SSE for simplicity and debuggability
- **RBAC is multi-layer**: Bot enforces agent access, Graph enforces tool/document access
- **Tool filtering**: Graph filters tools BEFORE LLM sees them (security + UX)
- **AcContext NOT cached in Redis**: AccessControlProvider handles caching
- **Session ID format**: Always use hierarchical format `room:thread:user`
- **HITL asks user, not admin**: User responds in same room/thread
- **HITL timeout**: Default 1 hour (3600 seconds), configurable per request
- **Redis TTL**: Sessions expire after 24 hours of inactivity
- **Dockerfile.dev files**: Used by Tilt for hot reload - don't modify regular Dockerfiles for dev
- **API documentation**: Access FastAPI Swagger docs at `http://localhost:8000/docs` when running

## Documentation References

- [README.md](./README.md): Project overview, quick start, features
- [ARCHITECTURE.md](./ARCHITECTURE.md): Comprehensive technical documentation with complete code examples
- `verji-vagent-bot/README.md`: Rust bot specific details
- `verji-vagent-graph/README.md`: Python service specific details

## Daily Development with Tilt

Tilt provides the best developer experience for this multi-service project:

### Morning Setup
```bash
# Start your Kubernetes cluster (if not running)
minikube start
# or: kind create cluster

# Start Tilt - this launches all services
tilt up

# Tilt UI opens at http://localhost:10350
# Wait for all resources to turn green (healthy)
```

### Coding
**Just edit files - Tilt handles the rest:**

- **Python changes** (`verji-vagent-graph/src/**/*.py`)
  - Files sync to container in < 1 sec
  - Service auto-reloads (no rebuild)
  - See changes immediately in logs

- **Rust changes** (`verji-vagent-bot/src/**/*.rs`)
  - Files sync to container
  - Incremental recompile in ~15 sec
  - Binary restarts automatically
  - Much faster than full Docker rebuild

### Using Tilt UI

**Resource view** (http://localhost:10350):
- **Green indicator**: Service healthy
- **Red indicator**: Error (click for logs)
- **Yellow indicator**: Building/starting

**Per-service logs:**
- Click any service name to view its logs
- Real-time streaming with syntax highlighting
- Search and filter capabilities

**Manual triggers:**
- **integration-tests**: Run test suite
- **redis-flush**: Clear all Redis data
- **api-docs**: Open FastAPI documentation

**Port forwards:**
- Redis: `localhost:6379`
- verji-vagent-graph HTTP: `localhost:8000`
- verji-vagent-bot metrics: `localhost:8080`

### End of Day
```bash
# Stop all services (keeps cluster running)
tilt down

# Or stop cluster entirely
minikube stop
```

### Troubleshooting

**Service won't start:**
1. Check logs in Tilt UI (click the service)
2. Verify `.env` file exists with correct credentials
3. Ensure Kubernetes cluster has enough resources

**Hot reload not working:**
1. Check Tilt logs for sync errors
2. Verify file paths match `live_update` sync patterns
3. Try manual restart: `tilt trigger <service-name>`

**Redis connection errors:**
1. Click "redis-flush" to clear stale data
2. Restart Redis: `kubectl delete pod -n chatbot-dev -l app=redis`

**Regenerate everything:**
```bash
tilt down
tilt up
```

## Contributing Guidelines

1. **Architecture decisions**: Refer to [ARCHITECTURE.md](./ARCHITECTURE.md) for rationale behind HTTP/JSON, RBAC, HITL, session management
2. **API changes**: Update types in `verji-vagent-bot/src/types.rs` and `verji-vagent-graph/src/types.py` to keep schemas in sync
3. **RBAC enforcement**: Bot checks agent access, Graph filters tools and documents
4. **Error handling**: Always handle Redis connection failures, HTTP timeouts, Matrix API errors, AccessControlProvider unavailability
5. **Logging**: Use structured logging (Rust: `tracing`, Python: built-in `logging`)
6. **Audit logging**: Log all access decisions (agent, tool, document access) with user_id and resource
7. **Type safety**: Use serde for Rust, Pydantic for Python to enforce JSON schemas
