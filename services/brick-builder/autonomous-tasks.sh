#!/bin/bash
# Autonomous Brick Builder Enhancement Pipeline
# Run via: bash autonomous-tasks.sh
# Each task runs Claude Code headless to make specific improvements

PROJECT_DIR="./services/brick-builder"
LOG_DIR="$PROJECT_DIR/auto-logs"
mkdir -p "$LOG_DIR"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_DIR/pipeline.log"
}

run_task() {
  local task_name="$1"
  local prompt="$2"
  local log_file="$LOG_DIR/${task_name}.log"

  log "START: $task_name"

  claude -p "$prompt" \
    --output-format json \
    --max-tokens 16000 \
    2>&1 | tee "$log_file"

  local exit_code=$?
  if [ $exit_code -eq 0 ]; then
    log "DONE: $task_name (success)"
  else
    log "FAIL: $task_name (exit code $exit_code)"
  fi

  return $exit_code
}

rebuild_frontend() {
  log "Rebuilding frontend..."
  cd "$PROJECT_DIR/frontend"
  npx vite build --outDir ../frontend-dist 2>&1 | tee "$LOG_DIR/build.log"
  systemctl restart brick-builder
  log "Frontend rebuilt and service restarted"
}

# ============================================
# TASK 1: Add brick rotation support
# ============================================
run_task "rotation" "
Working directory: $PROJECT_DIR/frontend

Read these files first: src/store.js, src/components/LegoBrick.jsx, src/components/Sidebar.jsx

Add brick rotation support:
1. In store.js: Add a 'rotation' field (0, 90, 180, 270 degrees) to the store state. Add setRotation action.
2. In LegoBrick.jsx: Apply rotation to the brick mesh using the rotation value from each brick's data. When placing a brick, include the current rotation.
3. In Sidebar.jsx: Add a rotation button in the Tools section that cycles through 0/90/180/270.
4. In store.js placeBrick: Include current rotation in the brick object.
5. The R key should also cycle rotation (already handled in App.jsx keyboard shortcuts if you add it).

Keep changes minimal. Only edit the 3 files mentioned.
"

# ============================================
# TASK 2: Add grid snapping preview (ghost brick)
# ============================================
run_task "ghost-brick" "
Working directory: $PROJECT_DIR/frontend

Read these files first: src/components/Baseplate.jsx, src/components/Scene.jsx, src/store.js

Add a ghost/preview brick that shows where a brick will be placed:
1. Create a new component src/components/GhostBrick.jsx that:
   - Uses useStore to get selectedColor, selectedSize
   - Renders a semi-transparent brick (opacity 0.4) at the current hover position
   - Uses onPointerMove on the baseplate to track mouse position
   - Snaps to grid (round to nearest integer)
2. In Baseplate.jsx: Add onPointerMove handler that updates a 'hoverPosition' in store
3. In store.js: Add hoverPosition state and setHoverPosition action
4. In Scene.jsx: Render <GhostBrick /> inside BrickWorld

The ghost brick should disappear when not hovering over the baseplate. Don't show it in delete mode.
"

# ============================================
# TASK 3: Add build export (screenshot)
# ============================================
run_task "export" "
Working directory: $PROJECT_DIR/frontend

Read these files first: src/components/Scene.jsx, src/components/Sidebar.jsx

Add a 'Take Screenshot' button to the Sidebar:
1. In Scene.jsx: Add gl={{ preserveDrawingBuffer: true }} to the Canvas props (needed for screenshots)
2. In Sidebar.jsx: Add a 'Screenshot' button in the Tools section
3. The screenshot handler should:
   - Get the canvas element: document.querySelector('canvas')
   - Call canvas.toDataURL('image/png')
   - Create a download link and trigger it
   - File name: 'brick-build-TIMESTAMP.png'

Keep it simple - just a button that downloads a PNG of the current 3D view.
"

# ============================================
# TASK 4: Improve AI prompt generation
# ============================================
run_task "ai-prompts" "
Working directory: $PROJECT_DIR

Read prompts.py first.

Improve the AI prompts to generate better brick suggestions:
1. Add more context to the suggestion prompt about spatial relationships
2. Add a 'freestyle' mode prompt that generates a full build from just a text description (e.g., 'build a house')
3. Make sure the prompts emphasize returning valid JSON with correct coordinate values
4. Add color variety instructions - AI should use different colors, not just one

Only edit prompts.py. Keep the same function signatures.
"

# ============================================
# REBUILD after all tasks
# ============================================
rebuild_frontend

# ============================================
# FINAL: Commit everything
# ============================================
log "Committing all changes..."
cd ./
git add services/brick-builder/
git commit -m "Autonomous pipeline: rotation, ghost brick, screenshot, AI prompts

- Added brick rotation (0/90/180/270) with R key shortcut
- Ghost preview brick shows placement position
- Screenshot export button in toolbar
- Improved AI prompts for better suggestions

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"

log "=== PIPELINE COMPLETE ==="
