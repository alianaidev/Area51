# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Status

This repository is newly initialized and does not yet contain source code.

## Claude Code Configuration

A `SessionStart` hook is configured in `.claude/hooks/session-start.sh`. It runs automatically in Claude Code on the web (`CLAUDE_CODE_REMOTE=true`) and installs dependencies for whichever package manager is detected (npm, pip, poetry, bundler, go, cargo).

To update the hook for a specific stack once source code is added, edit `.claude/hooks/session-start.sh` and keep only the relevant package manager block.
