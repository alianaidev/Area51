#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Node.js
if [ -f "package.json" ]; then
  echo "Installing Node.js dependencies..."
  npm install --quiet
fi

# Python — pyproject.toml takes precedence; fall back to requirements.txt
if [ -f "pyproject.toml" ]; then
  if command -v poetry >/dev/null 2>&1 && [ -f "poetry.lock" ]; then
    echo "Installing Python dependencies (Poetry)..."
    poetry install --no-interaction
  else
    echo "Installing Python dependencies (pip)..."
    pip install -e ".[dev]" --quiet || pip install -e . --quiet
  fi
elif [ -f "requirements.txt" ]; then
  echo "Installing Python dependencies..."
  pip install -r requirements.txt --quiet
  [ -f "requirements-dev.txt" ] && pip install -r requirements-dev.txt --quiet
fi

# Ruby
if [ -f "Gemfile" ]; then
  echo "Installing Ruby dependencies..."
  bundle install --quiet
fi

# Go
if [ -f "go.mod" ]; then
  echo "Installing Go dependencies..."
  go mod download
fi

# Rust
if [ -f "Cargo.toml" ]; then
  echo "Installing Rust dependencies..."
  cargo fetch
fi

echo "Session start hook completed."
