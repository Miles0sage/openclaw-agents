#!/bin/bash
# GitHub Integration Examples
# Quick copy-paste examples for all common workflows

# ============================================================================
# 1. SUBMIT JOB WITH AUTO-DELIVERY
# ============================================================================

echo "1. Submit job with auto-delivery enabled:"
curl -X POST http://localhost:18789/api/intake \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Add dark mode support",
    "description": "Implement dark mode with system preference detection and manual toggle",
    "task_type": "feature_build",
    "priority": "P1",
    "budget_limit": 10.0,
    "contact_email": "client@example.com",
    "delivery_config": {
      "auto_pr": true,
      "repo": "miles0sage/my-project",
      "auto_merge": false
    }
  }'

# ============================================================================
# 2. SUBMIT JOB WITHOUT AUTO-DELIVERY
# ============================================================================

echo ""
echo "2. Submit job without auto-delivery (for complex tasks):"
curl -X POST http://localhost:18789/api/intake \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Refactor authentication system",
    "description": "Complete rewrite of auth module with better separation of concerns",
    "task_type": "feature_build",
    "priority": "P1",
    "budget_limit": 50.0
  }'

# ============================================================================
# 3. MONITOR JOB PROGRESS
# ============================================================================

echo ""
echo "3. Get job status (use job_id from intake response):"
curl http://localhost:18789/api/jobs/{job_id}

echo ""
echo "4. Get detailed job progress:"
curl http://localhost:18789/api/jobs/{job_id}/progress

# ============================================================================
# 4. MANUAL DELIVERY TO GITHUB
# ============================================================================

echo ""
echo "5. Manually deliver completed job to GitHub:"
curl -X POST http://localhost:18789/api/jobs/{job_id}/deliver-github \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "miles0sage/my-project",
    "base_branch": "main",
    "auto_merge": false
  }'

# ============================================================================
# 5. CHECK PR STATUS
# ============================================================================

echo ""
echo "6. Get PR status for a delivered job:"
curl http://localhost:18789/api/jobs/{job_id}/pr

# ============================================================================
# 6. LIST ALL DELIVERIES
# ============================================================================

echo ""
echo "7. List all deliveries:"
curl http://localhost:18789/api/deliveries

echo ""
echo "8. Filter deliveries by status:"
curl "http://localhost:18789/api/deliveries?status=merged"
curl "http://localhost:18789/api/deliveries?status=open"
curl "http://localhost:18789/api/deliveries?status=delivered"

# ============================================================================
# 7. GITHUB WEBHOOK SIMULATION
# ============================================================================

echo ""
echo "9. Simulate GitHub webhook (PR merged):"
curl -X POST http://localhost:18789/api/github/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "action": "closed",
    "pull_request": {
      "number": 42,
      "merged": true,
      "merged_by": {"login": "developer"},
      "merged_at": "2026-02-19T18:30:00Z",
      "state": "closed"
    },
    "repository": {
      "full_name": "miles0sage/my-project"
    }
  }'

# ============================================================================
# 8. INTAKE STATISTICS
# ============================================================================

echo ""
echo "10. Get intake statistics:"
curl http://localhost:18789/api/intake/stats

# ============================================================================
# COMMON WORKFLOWS
# ============================================================================

# WORKFLOW 1: Quick feature with auto-delivery
# 1. Submit job with delivery_config.auto_pr=true
# 2. Wait 2-5 minutes for job to complete
# 3. Check /api/jobs/{job_id}/pr to get PR URL
# 4. Review PR on GitHub, merge when ready

# WORKFLOW 2: Complex feature with manual delivery
# 1. Submit job WITHOUT delivery config
# 2. Wait 5-10 minutes for job to complete
# 3. Manually call /api/jobs/{job_id}/deliver-github with repo
# 4. Review PR on GitHub before merging

# WORKFLOW 3: Monitor all deliveries
# 1. Call /api/deliveries to list all PRs
# 2. Filter by status: open, merged, delivered
# 3. Use /api/jobs/{job_id}/pr for detailed status
# 4. GitHub webhooks auto-update merge status

# ============================================================================
# DEBUGGING
# ============================================================================

echo ""
echo "Debug: Check delivery records file:"
cat /tmp/openclaw_github_deliveries.json | python3 -m json.tool

echo ""
echo "Debug: Check intake jobs file:"
cat /tmp/openclaw_intake.json | python3 -m json.tool | head -100

echo ""
echo "Debug: Verify gh CLI is installed:"
gh --version

echo ""
echo "Debug: Verify GitHub authentication:"
gh auth status

echo ""
echo "Debug: Test gh CLI can access repos:"
gh repo view miles0sage/my-project

# ============================================================================
# NOTES
# ============================================================================

# Replace {job_id} with actual job ID from intake response
# Replace miles0sage/my-project with your actual GitHub repo
# Replace http://localhost:18789 with your deployment URL
# Add -u user:token for authentication if needed
# Add -k for insecure HTTPS connections

# For more details, see:
# - GITHUB_INTEGRATION_README.md (overview)
# - GITHUB_INTEGRATION.md (API docs)
# - GITHUB_INTEGRATION_SETUP.md (integration guide)
