# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Status

This repository is newly initialized and does not yet contain source code.

## Claude Code Configuration

A `SessionStart` hook is configured in `.claude/hooks/session-start.sh`. It runs automatically in Claude Code on the web (`CLAUDE_CODE_REMOTE=true`) and installs dependencies for whichever package manager is detected (npm, pip, poetry, bundler, go, cargo).

To update the hook for a specific stack once source code is added, edit `.claude/hooks/session-start.sh` and keep only the relevant package manager block.

---

## Active Project: Rocket Ship Prop

### Overview
A full-scale (or large-scale) rocket ship built as a prop / presentation piece. The structural frame is built from PEX pipe and standard PEX fittings. The exterior panels are cardboard.

### Current Design Task: 3D Printed Door Hinges
Designing parametric 3D-printed hinges for the rocket ship door.

**Key decisions made:**
- Print material: PETG
- Mounting to door panel: Screw holes (user has cardboard-specific screws sourced from MakerWorld — file to be shared)
- Hinge attaches to PEX frame via a saddle on the frame plate
- Spec must be fully parametric so dimensions can be adjusted per iteration

**Key dimensions / constraints:**
- Pin A to Pin B spread on center knuckle: 22–24mm (exact value depends on PEX saddle depth — lock in after first test print)
- Pin type: not yet finalized — default assumption is 3mm steel rod, bore at 3.1–3.2mm for slip fit in PETG

**Open decisions:**
- Pin type (captured vs. friction-fit rod vs. through-bolt) — defaulting to 3mm steel rod until confirmed
- Cardboard screw file from MakerWorld not yet shared — needed to finalize mounting hole specs

### Test Print Strategy
Before printing full hinges, isolate the center knuckle + one barrel from each plate as a small test piece (~20 min print). Verify pin clearance and rotation feel before committing to full PETG print.

**Orientation note:** Print barrels horizontal (knuckle standing vertical) for best bore roundness — bore parallel to layer lines prints rounder than across them.
