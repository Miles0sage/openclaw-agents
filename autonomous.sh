#!/usr/bin/env bash
# autonomous.sh — Launch Claude Code agents that persist after SSH disconnect
#
# Usage:
#   ./autonomous.sh "Build a landing page for XYZ client"
#   ./autonomous.sh "Research the best AI frameworks for agents" --timeout 60
#   ./autonomous.sh list          # See running agents
#   ./autonomous.sh output JOB_ID # Get agent output
#   ./autonomous.sh kill JOB_ID   # Kill an agent
#   ./autonomous.sh killall       # Kill all agents
#
# Agents run in tmux — they survive SSH disconnects.
# Reconnect anytime with: tmux attach -t openclaw-agents

SESSION="openclaw-agents"
LOG="./data/tmux_agents.log"
CLAUDE="/root/.local/bin/claude"
ALLOWED='--allowedTools "Bash(*)" "Read(*)" "Write(*)" "Edit(*)" "Glob(*)" "Grep(*)" "WebSearch(*)" "WebFetch(*)" "Agent(*)" "mcp__openclaw__*"'

# Ensure tmux session exists
tmux has-session -t "$SESSION" 2>/dev/null || tmux new-session -d -s "$SESSION" -n control

case "${1:-}" in
  list)
    echo "=== Running Agents ==="
    tmux list-windows -t "$SESSION" -F "#{window_name}  #{window_activity_string}  #{pane_pid}" 2>/dev/null || echo "No agents running"
    echo ""
    echo "Active output files:"
    ls -lt ./data/agent_outputs/openclaw-output-*.txt 2>/dev/null | head -10 || echo "  (none)"
    ;;

  output)
    JOB_ID="${2:?Usage: autonomous.sh output JOB_ID}"
    OUTPUT_FILE="./data/agent_outputs/openclaw-output-${JOB_ID}.txt"
    if [ -f "$OUTPUT_FILE" ]; then
      tail -100 "$OUTPUT_FILE"
    else
      echo "No output file for job $JOB_ID"
      echo "Try: autonomous.sh list"
    fi
    ;;

  kill)
    JOB_ID="${2:?Usage: autonomous.sh kill JOB_ID}"
    WINDOW="agent-${JOB_ID:0:20}"
    tmux kill-window -t "${SESSION}:${WINDOW}" 2>/dev/null && echo "Killed $JOB_ID" || echo "Agent $JOB_ID not found"
    ;;

  killall)
    COUNT=$(tmux list-windows -t "$SESSION" 2>/dev/null | grep -c "agent-" || echo 0)
    tmux kill-session -t "$SESSION" 2>/dev/null
    tmux new-session -d -s "$SESSION" -n control
    echo "Killed $COUNT agents. Session reset."
    ;;

  ""|--help|-h)
    echo "Usage: autonomous.sh <prompt> [--timeout MINUTES]"
    echo "       autonomous.sh list|output|kill|killall"
    echo ""
    echo "Examples:"
    echo '  ./autonomous.sh "Fix the login bug in Delhi Palace"'
    echo '  ./autonomous.sh "Research YC application tips" --timeout 60'
    echo '  ./autonomous.sh list'
    echo ""
    echo "Reconnect to see live output: tmux attach -t openclaw-agents"
    ;;

  *)
    # It's a prompt — spawn an agent
    PROMPT="$1"
    TIMEOUT_MIN=30

    # Parse --timeout flag
    if [ "${2:-}" = "--timeout" ]; then
      TIMEOUT_MIN="${3:-30}"
    fi

    # Generate job ID
    JOB_ID="auto-$(date +%s)-$$"
    OUTPUT_FILE="./data/agent_outputs/openclaw-output-${JOB_ID}.txt"
    PROMPT_FILE="./data/agent_outputs/openclaw-prompt-${JOB_ID}.txt"
    SCRIPT_FILE="./data/agent_outputs/openclaw-agent-${JOB_ID}.sh"

    # Save prompt to file (avoids shell escaping nightmares)
    echo "$PROMPT" > "$PROMPT_FILE"

    # Build agent script with continuation loop (matches tmux_spawner.py pattern)
    cat > "$SCRIPT_FILE" << 'AGENTSCRIPT'
#!/usr/bin/env bash
unset CLAUDECODE
unset CLAUDE_CODE_SESSION
cd ./
echo "[AGENT_START] $(date)" >> LOG_PLACEHOLDER
echo "Agent JOB_PLACEHOLDER starting..."
> OUTPUT_PLACEHOLDER

MAX_CONTINUATIONS=5
ATTEMPT=0
FINAL_EXIT=1

while [ $ATTEMPT -lt $MAX_CONTINUATIONS ]; do
  ATTEMPT=$((ATTEMPT + 1))
  echo "[CONTINUATION $ATTEMPT/$MAX_CONTINUATIONS] $(date)"
  CLAUDE_PLACEHOLDER -p ALLOWED_PLACEHOLDER --max-turns 30 --output-format text "$(cat PROMPT_PLACEHOLDER)" 2>&1 | tee -a OUTPUT_PLACEHOLDER
  FINAL_EXIT=$?

  if [ $FINAL_EXIT -eq 0 ]; then
    echo "[AGENT_COMPLETED] Task finished on attempt $ATTEMPT"
    break
  fi

  if [ $FINAL_EXIT -eq 1 ] && [ $ATTEMPT -lt $MAX_CONTINUATIONS ]; then
    echo "[TURN_LIMIT_HIT] Continuing from where we left off..."
    PROGRESS=$(tail -80 OUTPUT_PLACEHOLDER)
    cat > PROMPT_PLACEHOLDER << CONTINUE_EOF
You were working on a task and hit the turn limit. Continue where you left off.

Your recent progress:
$PROGRESS

Continue the task. Do NOT restart from scratch. Pick up exactly where you stopped.
When fully done, output "TASK_COMPLETE" on the last line.
CONTINUE_EOF
  else
    echo "[AGENT_FAILED] Exit code $FINAL_EXIT on attempt $ATTEMPT"
    break
  fi
done

echo ""
echo "[AGENT_EXIT code=$FINAL_EXIT attempts=$ATTEMPT]"
echo "[AGENT_DONE] job=JOB_PLACEHOLDER exit=$FINAL_EXIT attempts=$ATTEMPT $(date)" >> LOG_PLACEHOLDER
echo "Agent finished. Pane stays open 5min for review..."
sleep 300
AGENTSCRIPT

    # Replace placeholders
    sed -i "s|LOG_PLACEHOLDER|$LOG|g" "$SCRIPT_FILE"
    sed -i "s|JOB_PLACEHOLDER|$JOB_ID|g" "$SCRIPT_FILE"
    sed -i "s|CLAUDE_PLACEHOLDER|$CLAUDE|g" "$SCRIPT_FILE"
    sed -i "s|ALLOWED_PLACEHOLDER|$ALLOWED|g" "$SCRIPT_FILE"
    sed -i "s|PROMPT_PLACEHOLDER|$PROMPT_FILE|g" "$SCRIPT_FILE"
    sed -i "s|OUTPUT_PLACEHOLDER|$OUTPUT_FILE|g" "$SCRIPT_FILE"
    chmod +x "$SCRIPT_FILE"

    # Build command with timeout
    if [ "$TIMEOUT_MIN" -gt 0 ]; then
      CMD="timeout $((TIMEOUT_MIN * 60)) bash $SCRIPT_FILE"
    else
      CMD="bash $SCRIPT_FILE"
    fi

    # Spawn in tmux
    WINDOW_NAME="agent-${JOB_ID:0:20}"
    tmux new-window -t "$SESSION" -n "$WINDOW_NAME" "$CMD"

    echo "Agent spawned!"
    echo "  Job ID:  $JOB_ID"
    echo "  Timeout: ${TIMEOUT_MIN}m"
    echo "  Output:  $OUTPUT_FILE"
    echo ""
    echo "Commands:"
    echo "  Watch live:    tmux attach -t $SESSION"
    echo "  Check output:  ./autonomous.sh output $JOB_ID"
    echo "  Kill agent:    ./autonomous.sh kill $JOB_ID"
    echo "  List all:      ./autonomous.sh list"
    ;;
esac
