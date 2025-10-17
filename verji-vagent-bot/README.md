# Verji vAgent Bot

Matrix bot service written in Rust using matrix-rust-sdk.

## Current Status: POC - Echo Bot

This is a minimal proof-of-concept that:
- Connects to a Matrix homeserver
- Listens for messages in joined rooms
- Echoes back any message it receives (except its own messages)

## Prerequisites

- Rust 1.75 or later
- A Matrix account for the bot
- Access to a Matrix homeserver

## Setup

1. **Create `.env` file** from the example:
   ```bash
   cp .env.example .env
   ```

2. **Configure Matrix credentials** in `.env`:
   ```bash
   MATRIX_HOMESERVER=https://matrix.org
   MATRIX_USER=@your-bot:matrix.org
   MATRIX_PASSWORD=your-password-here
   ```

3. **Invite the bot** to a Matrix room where you want to test it

## Running

```bash
# Development mode with logging
RUST_LOG=verji_vagent_bot=info cargo run

# Or just
cargo run
```

## Testing

1. Start the bot
2. Send a message in a room where the bot is present
3. The bot should respond with: `Echo: [your message]`

## What's Next

This POC will be extended with:
- RBAC integration (AccessControlProvider)
- HTTP client for Graph API communication
- Session management with Redis
- HITL (Human-in-the-Loop) coordination
- Proper error handling and retries

## Logging

Set the `RUST_LOG` environment variable to control logging:

```bash
# Info level for bot, warn for matrix-sdk
RUST_LOG=verji_vagent_bot=info,matrix_sdk=warn cargo run

# Debug everything
RUST_LOG=debug cargo run
```
