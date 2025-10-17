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
# Standard run
cargo run

# With verbose logging
RUST_LOG=verji_vagent_bot=debug cargo run

# Clear store and start fresh (useful for device ID mismatch errors)
cargo run -- --clear-store

# ⚠️ DESTRUCTIVE: Reset encryption (creates fresh keys, old messages may be unreadable)
cargo run -- --clear-store --reset-encryption
```

### Troubleshooting

**Device ID Mismatch Error:**
If you see an error like `"account in the store doesn't match"`, this means the crypto store has data from a different device. Fix it by:

```bash
# Option 1: Use the --clear-store flag
cargo run -- --clear-store

# Option 2: Manually delete the store directory
rm -rf ./matrix_store  # or your custom MATRIX_STORE_PATH
cargo run
```

**Backup Already Exists Error:**
If the bot can't create new encryption keys because a backup already exists from a previous device:

```bash
# ⚠️ WARNING: This is DESTRUCTIVE and will create fresh keys
# Old encrypted messages may become unreadable!
# Use only if you've lost your old recovery key
cargo run -- --clear-store --reset-encryption
```

**What `--reset-encryption` does:**
- ⚠️ **DESTRUCTIVE OPERATION**
- Forces creation of fresh cross-signing keys
- Creates a new recovery key (saved to `matrix_store/recovery_key.txt`)
- Overrides existing keys on the server
- **Old encrypted messages may become unreadable**
- Use only if you've lost access to old recovery keys

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
