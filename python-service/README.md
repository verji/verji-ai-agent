# Python Service

LangGraph-based AI workflow service with gRPC server.

## Responsibilities
- Receive messages from Rust bot via gRPC
- Execute LangGraph workflows
- Integrate with LLMs (OpenAI, Anthropic)
- Manage HITL nodes in workflows
- Store checkpoints in Redis

## Development
\`\`\`bash
cd python-service
poetry install
poetry run python -m src.main
\`\`\`
