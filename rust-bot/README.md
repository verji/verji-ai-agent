# Rust Bot

Matrix client service built with matrix-rust-sdk and tonic (gRPC).

## Responsibilities
- Connect to Matrix homeserver
- Handle message events from Matrix rooms
- Extract session IDs and forward messages to Python service via gRPC
- Handle HITL coordination with admin room
- Manage session state in Redis

## Development
\`\`\`bash
cd rust-bot
cargo build
cargo test
cargo run
\`\`\`
