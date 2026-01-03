#!/bin/bash
# XFeed + Claude Code tmux session
# Creates a split pane with X feed ticker on top, Claude Code below

SESSION_NAME="claude-xfeed"
XFEED_DIR="$HOME/Documents/Claude Code Projects/xfeed"

# Kill existing session if it exists
tmux kill-session -t "$SESSION_NAME" 2>/dev/null

# Create new session (this will be the main Claude pane)
tmux new-session -d -s "$SESSION_NAME" -n main

# Split and create 2-line ticker pane at the top (-b = before/above)
tmux split-window -v -b -l 2 -t "$SESSION_NAME"

# Top pane (0.0) is now the 2-line ticker pane
tmux send-keys -t "$SESSION_NAME:0.0" "cd \"$XFEED_DIR\" && source .venv/bin/activate && xfeed ticker --compact" Enter

# Bottom pane (0.1) is the main Claude pane - select it as active
tmux select-pane -t "$SESSION_NAME:0.1"
tmux send-keys -t "$SESSION_NAME:0.1" "claude" Enter

# Attach to session
tmux attach-session -t "$SESSION_NAME"
