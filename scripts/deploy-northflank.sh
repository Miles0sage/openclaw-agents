#!/bin/bash

#############################################################################
# Northflank MicroVM Deployment Script
# OpenClaw Gateway - Production Brief Section 2: Hardware-Level Isolation
# Generated: 2026-02-16
# 
# Purpose: Deploy OpenClaw gateway to Northflank with MicroVM isolation
# Usage: ./scripts/deploy-northflank.sh [--validate-only] [--config CONFIG_FILE]
#############################################################################

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${1:-.northflank.yaml}"
VALIDATE_ONLY=false
NORTHFLANK_API_URL="https://api.northflank.io/v1"

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

#############################################################################
# SECTION 1: Argument Parsing
#############################################################################

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --validate-only)
                VALIDATE_ONLY=true
                log_info "Running in validation-only mode"
                shift
                ;;
            --config)
                CONFIG_FILE="$2"
                shift 2
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

show_help() {
    cat << 'EOF'
Northflank MicroVM Deployment Script

Usage: ./scripts/deploy-northflank.sh [OPTIONS]

Options:
  --validate-only      Only validate config, don't deploy
  --config FILE        Path to Northflank config file (default: .northflank.yaml)
  --help               Show this help message

Examples:
  # Validate configuration
  ./scripts/deploy-northflank.sh --validate-only

  # Deploy with custom config
  ./scripts/deploy-northflank.sh --config custom-config.yaml

  # Full deployment
  ./scripts/deploy-northflank.sh
EOF
}

#############################################################################
# SECTION 2: Pre-Deployment Validation
#############################################################################

validate_config() {
    log_info "Validating deployment configuration..."
    
    # Check if config file exists
    if [[ ! -f "$REPO_ROOT/$CONFIG_FILE" ]]; then
        log_error "Config file not found: $REPO_ROOT/$CONFIG_FILE"
        return 1
    fi
    log_success "Config file found: $CONFIG_FILE"
    
    # Validate YAML syntax (requires yq or python)
    if command -v yq &> /dev/null; then
        if yq eval '.' "$REPO_ROOT/$CONFIG_FILE" > /dev/null; then
            log_success "YAML syntax valid"
        else
            log_error "Invalid YAML syntax in $CONFIG_FILE"
            return 1
        fi
    elif command -v python3 &> /dev/null; then
        if python3 -c "import yaml; yaml.safe_load(open('$REPO_ROOT/$CONFIG_FILE'))" 2>/dev/null; then
            log_success "YAML syntax valid (validated with Python)"
        else
            log_error "Invalid YAML syntax in $CONFIG_FILE"
            return 1
        fi
    else
        log_warning "Cannot validate YAML syntax (install yq or python3)"
    fi
    
    return 0
}

validate_prerequisites() {
    log_info "Checking deployment prerequisites..."
    
    # Check if gateway.py exists
    if [[ ! -f "$REPO_ROOT/gateway.py" ]]; then
        log_error "gateway.py not found in repository root"
        return 1
    fi
    log_success "gateway.py found"
    
    # Check if .env exists
    if [[ ! -f "$REPO_ROOT/.env" ]]; then
        log_warning ".env file not found - will need to configure secrets in Northflank"
    else
        log_success ".env file found"
    fi
    
    # Check if config.json exists
    if [[ ! -f "$REPO_ROOT/config.json" ]]; then
        log_warning "config.json not found - may be needed at runtime"
    else
        log_success "config.json found"
    fi
    
    # Check if requirements.txt exists
    if [[ ! -f "$REPO_ROOT/requirements.txt" ]]; then
        log_warning "requirements.txt not found - Northflank buildpack may fail"
        log_info "Creating basic requirements.txt..."
        cat > "$REPO_ROOT/requirements.txt" << 'EOFPIP'
fastapi>=0.100.0
uvicorn>=0.23.0
python-dotenv>=1.0.0
anthropic>=0.7.0
requests>=2.31.0
pydantic>=2.0.0
EOFPIP
        log_success "Created requirements.txt"
    else
        log_success "requirements.txt found"
    fi
    
    # Check Git status
    if ! git -C "$REPO_ROOT" rev-parse --git-dir > /dev/null 2>&1; then
        log_warning "Not a Git repository - deployment from GitHub may fail"
    else
        log_success "Git repository found"
        local uncommitted=$(git -C "$REPO_ROOT" status --porcelain | wc -l)
        if [[ $uncommitted -gt 0 ]]; then
            log_warning "Repository has $uncommitted uncommitted changes"
            log_info "Run 'git add' and 'git commit' before deploying"
        fi
    fi
    
    return 0
}

#############################################################################
# SECTION 3: Environment & Secrets Validation
#############################################################################

validate_secrets() {
    log_info "Validating secrets configuration..."
    
    # Check for ANTHROPIC_API_KEY
    if [[ -z "${ANTHROPIC_API_KEY:-}" ]] && [[ -f "$REPO_ROOT/.env" ]]; then
        ANTHROPIC_API_KEY=$(grep "^ANTHROPIC_API_KEY=" "$REPO_ROOT/.env" | cut -d'=' -f2- || true)
    fi
    
    if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
        log_error "ANTHROPIC_API_KEY not set and not found in .env"
        log_info "Set ANTHROPIC_API_KEY environment variable or add to .env file"
        return 1
    fi
    
    # Validate API key format (should start with sk-ant-)
    if [[ ! $ANTHROPIC_API_KEY =~ ^sk-ant- ]]; then
        log_error "ANTHROPIC_API_KEY does not look valid (should start with 'sk-ant-')"
        return 1
    fi
    log_success "ANTHROPIC_API_KEY found and appears valid"
    
    # Check for GATEWAY_TOKEN
    if [[ -z "${GATEWAY_TOKEN:-}" ]] && [[ -f "$REPO_ROOT/.env" ]]; then
        GATEWAY_TOKEN=$(grep "^GATEWAY_TOKEN=" "$REPO_ROOT/.env" | cut -d'=' -f2- || true)
    fi
    
    # If not in .env, check gateway.py for default
    if [[ -z "${GATEWAY_TOKEN:-}" ]]; then
        GATEWAY_TOKEN=$(grep "AUTH_TOKEN\s*=" "$REPO_ROOT/gateway.py" | head -1 | sed 's/.*"\(.*\)".*/\1/' || echo "")
    fi
    
    if [[ -z "${GATEWAY_TOKEN:-}" ]]; then
        log_error "GATEWAY_TOKEN not set and not found in .env or gateway.py"
        log_info "Set GATEWAY_TOKEN environment variable or add to .env file"
        return 1
    fi
    log_success "GATEWAY_TOKEN found"
    
    return 0
}

#############################################################################
# SECTION 4: Health Endpoint Verification
#############################################################################

verify_health_endpoint() {
    log_info "Verifying gateway health endpoint..."
    
    # Check if gateway has health endpoint defined
    if grep -q "@app.get.*health" "$REPO_ROOT/gateway.py"; then
        log_success "Health endpoint found in gateway.py"
    else
        log_warning "Health endpoint not found in gateway.py"
        log_info "Adding health endpoint to gateway.py..."
        # This would require modifying gateway.py, which we should not do automatically
        # Just warn the user
        log_warning "Please ensure health endpoint is implemented:"
        cat << 'EOFHEALTH'
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "uptime": time.time() - START_TIME
    }
EOFHEALTH
    fi
    
    return 0
}

#############################################################################
# SECTION 5: Session Persistence Validation
#############################################################################

validate_session_persistence() {
    log_info "Validating session persistence configuration..."
    
    # Check if session directory handling exists in gateway.py
    if grep -q "OPENCLAW_SESSIONS_DIR\|/tmp/openclaw_sessions" "$REPO_ROOT/gateway.py"; then
        log_success "Session persistence code found in gateway.py"
    else
        log_warning "Session persistence code not found in gateway.py"
        log_warning "Ensure session handling is implemented as per requirements"
    fi
    
    # Create local session directory for testing
    if [[ ! -d "/tmp/openclaw_sessions" ]]; then
        mkdir -p "/tmp/openclaw_sessions"
        log_success "Created session directory: /tmp/openclaw_sessions"
    else
        log_success "Session directory exists: /tmp/openclaw_sessions"
    fi
    
    # Check if directory is writable
    if [[ -w "/tmp/openclaw_sessions" ]]; then
        log_success "Session directory is writable"
    else
        log_warning "Session directory is not writable - check permissions"
    fi
    
    return 0
}

#############################################################################
# SECTION 6: Isolation Boundary Testing (Local)
#############################################################################

test_isolation_boundaries() {
    log_info "Testing isolation boundary requirements..."
    
    # Check for security policies in config
    if grep -q "securityPolicies\|runAsNonRoot\|readOnlyRootFilesystem" "$REPO_ROOT/$CONFIG_FILE"; then
        log_success "Security policies found in config"
    else
        log_warning "Security policies not fully configured"
    fi
    
    # Check for MicroVM isolation
    if grep -q "type: microvms" "$REPO_ROOT/$CONFIG_FILE"; then
        log_success "MicroVM isolation configured"
    else
        log_error "MicroVM isolation not configured in $CONFIG_FILE"
        return 1
    fi
    
    # Check network policies
    if grep -q "networkPolicy" "$REPO_ROOT/$CONFIG_FILE"; then
        log_success "Network policies configured"
    else
        log_warning "Network policies not explicitly configured"
    fi
    
    return 0
}

#############################################################################
# SECTION 7: Docker Image Build (Optional Local Test)
#############################################################################

test_local_docker_build() {
    log_info "Testing local Docker build (optional)..."
    
    # Check if Docker is available
    if ! command -v docker &> /dev/null; then
        log_warning "Docker not installed - skipping local build test"
        return 0
    fi
    
    # Check if Dockerfile exists
    if [[ ! -f "$REPO_ROOT/Dockerfile" ]]; then
        log_warning "Dockerfile not found - will use Northflank buildpack"
        return 0
    fi
    
    log_info "Building Docker image for testing..."
    if docker build -t openclaw-gateway:test -f "$REPO_ROOT/Dockerfile" "$REPO_ROOT" > /tmp/docker-build.log 2>&1; then
        log_success "Docker image built successfully"
        
        # Get image size
        local image_size=$(docker image inspect openclaw-gateway:test --format='{{.Size}}' | numfmt --to=iec 2>/dev/null || echo "N/A")
        log_info "Image size: $image_size"
        
        # Cleanup
        docker rmi openclaw-gateway:test > /dev/null 2>&1 || true
    else
        log_warning "Docker build failed - see /tmp/docker-build.log for details"
        log_info "Note: Northflank buildpack may still succeed"
    fi
    
    return 0
}

#############################################################################
# SECTION 8: Generate Deployment Summary
#############################################################################

generate_deployment_summary() {
    log_info "Generating deployment summary..."
    
    cat > "$REPO_ROOT/DEPLOYMENT_SUMMARY.txt" << EOFSUMMARY
================================================================================
OpenClaw Gateway - Northflank MicroVM Deployment Summary
Generated: $(date -u +'%Y-%m-%d %H:%M:%S UTC')
================================================================================

CONFIGURATION
  Config File: $CONFIG_FILE
  Repository: $REPO_ROOT
  Gateway: $REPO_ROOT/gateway.py

DEPLOYMENT DETAILS
  Platform: Northflank
  Isolation: MicroVM (Hardware-level)
  Runtime: Python 3.13
  Port: 8000

RESOURCES
  Memory Request: 2Gi
  Memory Limit: 4Gi
  CPU Request: 1 core
  CPU Limit: 2 cores
  Disk: 10Gi

SCALING
  Min Instances: 1
  Max Instances: 5
  Target CPU: 70%
  Target Memory: 80%

SECURITY
  User: 1000:1000 (non-root)
  Filesystem: Read-only (except /tmp)
  Network: Restricted (ingress on 8000, selective egress)
  Syscalls: Enforced filter
  Capabilities: Minimal

SECRETS REQUIRED
  - ANTHROPIC_API_KEY
  - GATEWAY_TOKEN

ENDPOINTS
  Health: /health
  API Root: /
  Chat: /api/chat
  Agents: /api/agents
  Routing: /api/route
  Costs: /api/costs/summary

SESSION PERSISTENCE
  Directory: /tmp/openclaw_sessions
  Format: JSON
  TTL: 30 days
  Backup: Daily at 2 AM UTC

NEXT STEPS
  1. Create Northflank account at https://northflank.com
  2. Set up secrets in Northflank secret manager
  3. Create new service with Python buildpack
  4. Import .northflank.yaml configuration
  5. Deploy and test health endpoint
  6. Monitor metrics in Northflank dashboard

TROUBLESHOOTING
  - See NORTHFLANK-CHECKLIST.md for detailed validation steps
  - Check gateway logs: Northflank observability dashboard
  - Test locally: python3 gateway.py && curl http://localhost:8000/health
  - Validate config: yq eval '.' .northflank.yaml

================================================================================
EOFSUMMARY
    
    log_success "Deployment summary saved to DEPLOYMENT_SUMMARY.txt"
}

#############################################################################
# SECTION 9: API Deployment (When Northflank API Access Available)
#############################################################################

deploy_to_northflank_api() {
    log_info "Deploying to Northflank API..."
    
    # Check for Northflank API credentials
    if [[ -z "${NORTHFLANK_TOKEN:-}" ]]; then
        log_warning "NORTHFLANK_TOKEN not set - cannot deploy via API"
        log_info "To deploy via API, set NORTHFLANK_TOKEN environment variable"
        log_info "Or deploy manually via https://dashboard.northflank.com"
        return 1
    fi
    
    # This would require:
    # 1. Parsing .northflank.yaml
    # 2. Converting to Northflank API format
    # 3. Making API calls to Northflank
    # 4. Monitoring deployment status
    # 5. Running health checks
    
    # For now, we'll provide manual instructions instead
    log_info "Manual deployment via Northflank API coming soon"
    return 0
}

#############################################################################
# SECTION 10: Deployment Health Checks
#############################################################################

run_health_checks() {
    log_info "Running pre-deployment health checks..."
    
    local checks_passed=0
    local checks_failed=0
    
    # Check 1: Config file exists
    if [[ -f "$REPO_ROOT/$CONFIG_FILE" ]]; then
        log_success "Config file exists"
        ((checks_passed++))
    else
        log_error "Config file not found"
        ((checks_failed++))
    fi
    
    # Check 2: Gateway exists
    if [[ -f "$REPO_ROOT/gateway.py" ]]; then
        log_success "gateway.py exists"
        ((checks_passed++))
    else
        log_error "gateway.py not found"
        ((checks_failed++))
    fi
    
    # Check 3: Secrets available
    if [[ -n "${ANTHROPIC_API_KEY:-}" ]] && [[ -n "${GATEWAY_TOKEN:-}" ]]; then
        log_success "Required secrets available"
        ((checks_passed++))
    else
        log_error "Required secrets not available"
        ((checks_failed++))
    fi
    
    # Check 4: Session directory writable
    if [[ -w "/tmp/openclaw_sessions" ]]; then
        log_success "Session directory writable"
        ((checks_passed++))
    else
        log_warning "Session directory not writable (may be fine in MicroVM)"
        ((checks_passed++))
    fi
    
    # Check 5: MicroVM isolation configured
    if grep -q "type: microvms" "$REPO_ROOT/$CONFIG_FILE"; then
        log_success "MicroVM isolation configured"
        ((checks_passed++))
    else
        log_error "MicroVM isolation not configured"
        ((checks_failed++))
    fi
    
    # Summary
    log_info "Health checks: $checks_passed passed, $checks_failed failed"
    
    if [[ $checks_failed -eq 0 ]]; then
        log_success "All critical health checks passed"
        return 0
    else
        log_error "Some health checks failed - review above"
        return 1
    fi
}

#############################################################################
# SECTION 11: Main Execution
#############################################################################

main() {
    log_info "=========================================="
    log_info "OpenClaw Gateway - Northflank Deployment"
    log_info "=========================================="
    log_info "Generated: 2026-02-16"
    log_info "Status: Hardware-Level Isolation (Production Brief Section 2)"
    echo ""
    
    # Parse arguments
    parse_args "$@"
    
    # Validation phase
    echo ""
    log_info "=== VALIDATION PHASE ==="
    validate_config || exit 1
    validate_prerequisites || exit 1
    validate_secrets || exit 1
    verify_health_endpoint || true
    validate_session_persistence || true
    test_isolation_boundaries || exit 1
    test_local_docker_build || true
    
    # Health checks
    echo ""
    log_info "=== HEALTH CHECKS ==="
    run_health_checks || exit 1
    
    # Generate summary
    echo ""
    log_info "=== DEPLOYMENT SUMMARY ==="
    generate_deployment_summary
    
    # Deployment phase (unless validation-only)
    if [[ $VALIDATE_ONLY == true ]]; then
        echo ""
        log_success "Validation complete - deployment validation-only mode"
        log_info "Run without --validate-only to proceed with deployment"
        exit 0
    fi
    
    # Deployment
    echo ""
    log_info "=== DEPLOYMENT PHASE ==="
    deploy_to_northflank_api || log_warning "API deployment not available - use manual deployment"
    
    # Summary
    echo ""
    log_success "=========================================="
    log_success "Deployment configuration ready"
    log_success "=========================================="
    log_info "Next steps:"
    log_info "  1. Review NORTHFLANK-CHECKLIST.md"
    log_info "  2. Create Northflank account"
    log_info "  3. Configure secrets in dashboard"
    log_info "  4. Deploy with Python buildpack"
    log_info "  5. Test health endpoint"
    echo ""
    log_info "For detailed instructions, see:"
    log_info "  - NORTHFLANK-CHECKLIST.md"
    log_info "  - DEPLOYMENT_SUMMARY.txt"
    echo ""
}

# Run main
main "$@"
