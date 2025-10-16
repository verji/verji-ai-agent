# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Verji AI Agent is a production-ready Matrix chatbot combining Rust (matrix-rust-sdk) and Python (LangGraph) for intelligent, human-in-the-loop conversational AI.

**Architecture:**
- **Verji vAgent Bot** (`verji-vagent-bot/`): Matrix client handling message events, session management, and HITL coordination
- **Verji vAgent Graph** (`verji-vagent-graph/`): LangGraph-based AI workflow orchestration with LLM integration
- **Redis**: Shared state store for sessions, checkpoints, and pubsub coordination
- **gRPC**: Type-safe bidirectional communication between services using Protocol Buffers

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
- **proto-compile**: Regenerate protobuf code after editing `proto/chatbot.proto`
- **integration-tests**: Run full integration test suite
- **redis-flush**: Clear Redis cache/state

**Edit workflow:**
1. Edit Python files → changes sync and reload automatically in < 1 sec
2. Edit Rust files → changes sync, incremental recompile in ~15 sec
3. View logs from all services in unified dashboard
4. No need to manually restart anything

### Protocol Buffers
```bash
# After editing proto/chatbot.proto, regenerate gRPC code:
# Option 1: Click "proto-compile" button in Tilt UI
# Option 2: Run manually
./scripts/gen-proto.sh

# Generates:
# - verji-vagent-bot/src/proto/ (Rust gRPC code)
# - verji-vagent-graph/src/proto/ (Python gRPC code)
```

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
- **gRPC** is used for all Rust ↔ Python communication (NOT WebSocket/JSON-RPC)
- Services run as **separate containers** (no spawning/forking)
- Both services (`verji-vagent-bot` and `verji-vagent-graph`) connect to shared **Redis** instance
- Protocol defined in `proto/chatbot.proto` - always regenerate after changes

### Session Management
Sessions use hierarchical IDs: `{room_id}:{thread_id}:{user_id}`

Examples:
- Main room: `!abc123:matrix.org:main:@user:matrix.org`
- Threaded: `!abc123:matrix.org:$thread456:@user:matrix.org`

**Redis keys:**
- Session state: `session:{session_id}`
- HITL pending: `hitl_pending:{session_id}`
- LangGraph checkpoints: Managed by LangGraph's Redis checkpointer

### Human-in-the-Loop (HITL) Pattern

The HITL workflow coordinates human approval for sensitive operations:

1. **verji-vagent-graph** (LangGraph) detects risky action → sends `HITLRequest` via gRPC
2. **verji-vagent-bot** posts question to admin Matrix room
3. **verji-vagent-bot** subscribes to Redis pubsub channel: `hitl:{session_id}`
4. **Admin** responds in Matrix room
5. **verji-vagent-bot** publishes response to Redis channel
6. **verji-vagent-graph** receives feedback, resumes LangGraph from checkpoint

**Key points:**
- Admin room ID configured via `ADMIN_ROOM_ID` environment variable
- Redis pubsub ensures async coordination between services
- LangGraph uses Redis checkpointer to persist state and resume after HITL

### State Persistence
- **Session state**: Redis with 24-hour TTL
- **LangGraph checkpoints**: Redis via `langgraph.checkpoint.redis.RedisSaver`
- **In-memory cache**: verji-vagent-bot maintains local cache of active sessions

## Code Structure

### Protocol Buffers (proto/chatbot.proto)
Defines the gRPC contract between services:
- `ChatbotService`: Main service with `ProcessMessage` (bidirectional stream), `SubmitHumanFeedback`, `HealthCheck`
- Message types: `BotMessage`, `BotResponse`, `HITLRequest`, `TextMessage`, `StreamChunk`, `ErrorMessage`

### Verji vAgent Bot Architecture (verji-vagent-bot/)
Expected modules (refer to [ARCHITECTURE.md](./ARCHITECTURE.md) for detailed examples):
- `main.rs`: Entry point, Matrix client setup, event loop
- `session.rs`: Session management, Redis operations
- `hitl.rs`: HITL coordination, admin room integration
- `grpc_client.rs`: gRPC client to verji-vagent-graph service

### Verji vAgent Graph Architecture (verji-vagent-graph/)
Expected modules:
- `main.py`: Entry point, gRPC server startup
- `grpc_server.py`: gRPC server implementation
- `session_manager.py`: Redis session operations
- `langgraph_workflow.py`: LangGraph workflow definitions with HITL nodes

### LangGraph Workflow Pattern
LangGraph workflows should:
- Use `State` TypedDict with `session_id`, `messages`, `proposed_action`, `approval`, `final_response`
- Implement conditional edges to route to HITL approval node for risky actions
- Use Redis checkpointer: `RedisSaver(session_manager.redis)`
- Send `HITLRequest` via gRPC when human approval needed
- Wait for feedback via Redis pubsub before resuming

## Environment Configuration

Copy `.env.example` to `.env` and configure:

**Required:**
- `MATRIX_HOMESERVER`: Matrix server URL
- `MATRIX_USER`: Bot username (e.g., `@bot:matrix.org`)
- `MATRIX_PASSWORD`: Bot password
- `ADMIN_ROOM_ID`: Matrix room for HITL approvals (e.g., `!adminroom:matrix.org`)
- `REDIS_URL`: Redis connection string
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`: LLM API keys

**Optional:**
- `GRPC_ENDPOINT`: verji-vagent-graph service endpoint (default: `http://verji-vagent-graph:50051`)
- `RUST_LOG`: Rust logging level (default: `info,matrix_sdk=warn`)
- `LOG_LEVEL`: Python logging level (default: `info`)

## Deployment Architecture

**Services are deployed separately** (not spawned/forked):

```
Redis Container ← → verji-vagent-graph Container
                    ↑ (gRPC)
                    verji-vagent-bot Container
```

Benefits:
- Independent restarts and scaling
- Clear resource limits per service
- Docker/K8s health checks per service
- Language-specific optimal runtimes

**Startup order:**
1. Redis
2. verji-vagent-graph (starts gRPC server on `:50051`)
3. verji-vagent-bot (connects to verji-vagent-graph and Matrix)

## Key Technical Details

### gRPC Communication
- **Bidirectional streaming**: Used for `ProcessMessage` to support HITL flows
- **Type safety**: Protocol buffers ensure contract between Rust and Python
- **Connection**: verji-vagent-bot is gRPC client, verji-vagent-graph is gRPC server
- **Error handling**: Use `ErrorMessage` response type for failures

### Redis Usage
1. **Session storage**: Persist session state with TTL
2. **LangGraph checkpoints**: Enable graph resumption after HITL
3. **Pubsub**: Coordinate HITL feedback between services (channel: `hitl:{session_id}`)

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
- **Always regenerate proto**: Run `./scripts/gen-proto.sh` after editing `proto/chatbot.proto` (or click "proto-compile" in Tilt UI)
- **Session ID format**: Always use hierarchical format `room:thread:user`
- **HITL timeout**: Default 1 hour (3600 seconds), configurable per request
- **Redis TTL**: Sessions expire after 24 hours of inactivity
- **Admin room security**: Only process HITL responses from configured `ADMIN_ROOM_ID`
- **Dockerfile.dev files**: Used by Tilt for hot reload - don't modify regular Dockerfiles for dev

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

- **Protocol changes** (`proto/chatbot.proto`)
  - Edit the `.proto` file
  - Click "proto-compile" in Tilt UI
  - Generated code updates automatically

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
- **proto-compile**: Regenerate gRPC code
- **integration-tests**: Run test suite
- **redis-flush**: Clear all Redis data

**Port forwards:**
- Redis: `localhost:6379`
- verji-vagent-graph gRPC: `localhost:50051`
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

1. **Architecture decisions**: Refer to [ARCHITECTURE.md](./ARCHITECTURE.md) for rationale behind gRPC, Redis, session management
2. **Protocol changes**: Update `proto/chatbot.proto` first, then regenerate code
3. **Error handling**: Always handle Redis connection failures, gRPC timeouts, Matrix API errors
4. **Logging**: Use structured logging (Rust: `tracing`, Python: built-in `logging`)
5. **Type safety**: Leverage Protocol Buffers for cross-service contracts
