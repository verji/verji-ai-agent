# Verji AI Agent

A Matrix chatbot combining Rust (matrix-rust-sdk) and Python (LangGraph) for intelligent, human-in-the-loop conversational AI.

## Overview

This project implements a production-ready Matrix chatbot with the following architecture:

- **Rust Bot** (`rust-bot/`): Matrix client handling message events, session management, and HITL coordination
- **Python Service** (`python-service/`): LangGraph-based AI workflow orchestration with LLM integration
- **Redis**: Shared state store for sessions, checkpoints, and pubsub coordination
- **gRPC**: Type-safe bidirectional communication between Rust and Python services

## Features

- ✅ **Multi-room support**: Handle conversations across multiple Matrix rooms simultaneously
- ✅ **Session management**: Hierarchical session IDs (`room:thread:user`) with Redis persistence
- ✅ **Human-in-the-loop (HITL)**: Admin approval workflow for sensitive operations
- ✅ **LangGraph workflows**: Stateful, resumable AI agent workflows
- ✅ **Hot reload development**: Tilt-based local Kubernetes development with live updates
- ✅ **Type-safe IPC**: Protocol buffers ensure contract between Rust and Python
- ✅ **Production-ready**: Docker, Kubernetes manifests, health checks, and observability

## Quick Start

### Prerequisites

- **Rust** 1.75+
- **Python** 3.11+
- **Docker** & **Docker Compose**
- **Kubernetes** cluster (minikube, kind, or cloud provider)
- **Tilt** (for local development)
- **Protocol Buffers** compiler (`protoc`)

### Local Development (Docker Compose)

```bash
# 1. Clone repository
git clone https://github.com/verji/verji-ai-agent.git
cd verji-ai-agent

# 2. Set up environment
cp .env.example .env
# Edit .env with your Matrix credentials and API keys

# 3. Generate protobuf code
./scripts/gen-proto.sh

# 4. Start services
docker-compose up
```

### Local Development (Tilt + Kubernetes)

```bash
# 1. Start local Kubernetes cluster (if not already running)
minikube start
# or: kind create cluster

# 2. Set up environment
cp .env.example .env
# Edit .env with your credentials

# 3. Start Tilt
tilt up

# Tilt web UI opens at http://localhost:10350
# - Hot reload for Python (< 1 sec)
# - Incremental compile for Rust (~15 sec)
# - View logs, metrics, and health status
```

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for comprehensive technical documentation including:

- System architecture diagrams
- IPC protocol design (gRPC vs alternatives)
- Session management strategy
- HITL implementation patterns
- Complete code examples (Rust + Python)
- Deployment architecture (separate services vs spawn/fork)
- Tilt configuration for local development

## Project Structure

```
verji-ai-agent/
├── README.md                   # This file
├── ARCHITECTURE.md             # Comprehensive technical documentation
├── Tiltfile                    # Local K8s development configuration
├── docker-compose.yml          # Production Docker Compose
├── docker-compose.dev.yml      # Development Docker Compose
├── .env.example                # Environment variable template
├── proto/
│   └── chatbot.proto          # gRPC protocol buffer definitions
├── rust-bot/                  # Rust Matrix bot service
│   ├── Cargo.toml
│   ├── Dockerfile
│   ├── Dockerfile.dev         # Development image with hot reload
│   ├── src/
│   │   ├── main.rs            # Entry point
│   │   ├── session.rs         # Session management
│   │   ├── hitl.rs            # Human-in-the-loop handler
│   │   └── grpc_client.rs     # gRPC client to Python service
│   └── tests/
├── python-service/            # Python LangGraph service
│   ├── pyproject.toml         # Poetry dependencies
│   ├── Dockerfile
│   ├── Dockerfile.dev         # Development image with hot reload
│   ├── src/
│   │   ├── main.py            # Entry point
│   │   ├── grpc_server.py     # gRPC server implementation
│   │   ├── session_manager.py # Redis session management
│   │   └── langgraph_workflow.py # LangGraph workflow definitions
│   └── tests/
├── scripts/
│   ├── gen-proto.sh           # Generate Rust + Python code from .proto
│   ├── dev.sh                 # Quick start development environment
│   └── test-integration.sh    # Run integration tests
├── k8s/                       # Kubernetes manifests
│   ├── base/                  # Base manifests
│   └── overlays/              # Environment-specific overlays (dev, prod)
└── tests/
    └── integration/           # End-to-end integration tests
        ├── test_basic_flow.py
        └── test_hitl_flow.py
```

## Development Workflow

### Daily Development with Tilt

```bash
# Morning: Start cluster
tilt up

# Code - changes auto-sync!
# - Edit Python files → hot reload in < 1 sec
# - Edit Rust files → incremental recompile in ~15 sec

# Useful Tilt UI buttons:
# - "proto-compile" - Regenerate protobuf code
# - "integration-tests" - Run full test suite
# - "redis-flush" - Clear Redis cache

# End of day
tilt down
```

### Running Tests

```bash
# Unit tests - Rust
cd rust-bot
cargo test

# Unit tests - Python
cd python-service
poetry run pytest

# Integration tests (requires running services)
./scripts/test-integration.sh
```

### Regenerating Protocol Buffers

```bash
# After editing proto/chatbot.proto
./scripts/gen-proto.sh

# This generates:
# - rust-bot/src/proto/ (Rust gRPC code)
# - python-service/src/proto/ (Python gRPC code)
```

## Configuration

### Environment Variables

See [.env.example](./.env.example) for all configuration options.

**Key variables:**

- `MATRIX_HOMESERVER` - Matrix server URL
- `MATRIX_USER` - Bot username
- `MATRIX_PASSWORD` - Bot password
- `REDIS_URL` - Redis connection string
- `OPENAI_API_KEY` - OpenAI API key (for LLM)
- `ADMIN_ROOM_ID` - Matrix room for HITL approvals

### Matrix Bot Setup

1. Create a bot account on your Matrix homeserver
2. Create an admin room for HITL approvals
3. Invite the bot to rooms where it should respond
4. Configure credentials in `.env`

## Deployment

### Docker Compose (Simple)

```bash
# Production deployment
docker-compose -f docker-compose.yml up -d

# View logs
docker-compose logs -f
```

### Kubernetes (Production)

```bash
# Using kubectl with kustomize
kubectl apply -k k8s/overlays/prod

# Using Helm (if chart is created)
helm install verji-ai-agent ./helm/verji-ai-agent
```

## Monitoring & Observability

- **Health checks**: Both services expose health endpoints
  - Rust bot: `http://rust-bot:8080/health`
  - Python service: gRPC health probe on port 50051
- **Metrics**: Prometheus-compatible metrics (optional)
- **Logs**: Structured JSON logs to stdout (captured by K8s)
- **Tracing**: OpenTelemetry support (optional)

## Contributing

1. Create a feature branch from `main`
2. Make your changes with tests
3. Run linters and tests locally
4. Create PR with description
5. Wait for CI checks to pass

### Code Quality

```bash
# Rust
cd rust-bot
cargo fmt
cargo clippy
cargo test

# Python
cd python-service
poetry run black .
poetry run ruff check .
poetry run pytest
```

## License

[Add your license here]

## Support

- **Issues**: https://github.com/verji/verji-ai-agent/issues
- **Discussions**: https://github.com/verji/verji-ai-agent/discussions
- **Architecture docs**: See [ARCHITECTURE.md](./ARCHITECTURE.md)

## Roadmap

- [ ] Multi-LLM support (Anthropic Claude, local models)
- [ ] Voice message support
- [ ] Image/file handling
- [ ] Multi-language support
- [ ] Plugin system for custom actions
- [ ] Web dashboard for HITL approvals
- [ ] Conversation history export
- [ ] Fine-tuning dataset generation

---

**Built with ❤️ using Rust, Python, Matrix, and LangGraph**
