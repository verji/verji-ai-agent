# Verji vAgent Bot

Matrix client service built with matrix-rust-sdk and tonic (gRPC).

## Responsibilities
- Connect to Matrix homeserver
- Handle message events from Matrix rooms
- Extract session IDs and forward messages to verji-vagent-graph via gRPC
- Handle HITL coordination with admin room
- Manage session state in Redis

## Development
\`\`\`bash
cd verji-vagent-bot
cargo build
cargo test
cargo run
\`\`\`
