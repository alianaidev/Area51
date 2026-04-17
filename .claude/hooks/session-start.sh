#!/bin/bash
set -euo pipefail

# Only run in remote (web) environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Node.js / npm
if [ -f "$PROJECT_DIR/package.json" ]; then
  echo "Installing Node.js dependencies..."
  cd "$PROJECT_DIR"
  npm install
fi

# Python / pip
if [ -f "$PROJECT_DIR/requirements.txt" ]; then
  echo "Installing Python dependencies (requirements.txt)..."
  pip install -r "$PROJECT_DIR/requirements.txt" --quiet
fi

if [ -f "$PROJECT_DIR/requirements-dev.txt" ]; then
  echo "Installing Python dev dependencies..."
  pip install -r "$PROJECT_DIR/requirements-dev.txt" --quiet
fi

# Python / pyproject.toml (Poetry or PEP 517)
if [ -f "$PROJECT_DIR/pyproject.toml" ]; then
  cd "$PROJECT_DIR"
  if command -v poetry &>/dev/null && [ -f "$PROJECT_DIR/poetry.lock" ]; then
    echo "Installing Python dependencies (Poetry)..."
    poetry install --no-interaction
  else
    echo "Installing Python dependencies (pip)..."
    pip install -e ".[dev]" --quiet 2>/dev/null || pip install -e . --quiet
  fi
fi

# Ruby / Bundler
if [ -f "$PROJECT_DIR/Gemfile" ]; then
  echo "Installing Ruby dependencies..."
  cd "$PROJECT_DIR"
  bundle install --quiet
fi

# Go
if [ -f "$PROJECT_DIR/go.mod" ]; then
  echo "Installing Go dependencies..."
  cd "$PROJECT_DIR"
  go mod download
fi

# Rust / Cargo
if [ -f "$PROJECT_DIR/Cargo.toml" ]; then
  echo "Fetching Rust dependencies..."
  cd "$PROJECT_DIR"
  cargo fetch
fi

echo "Session start hook completed."
