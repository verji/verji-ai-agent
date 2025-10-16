#!/bin/bash
set -e

echo "Generating protocol buffer code..."

# Generate Rust code
echo "→ Generating Rust code..."
cd rust-bot
cargo build --features proto-gen 2>/dev/null || echo "Note: Run this after implementing build.rs"
cd ..

# Generate Python code
echo "→ Generating Python code..."
python -m grpc_tools.protoc \
  -I./proto \
  --python_out=./python-service/src \
  --grpc_python_out=./python-service/src \
  ./proto/chatbot.proto

echo "✓ Protocol buffer code generated successfully"
