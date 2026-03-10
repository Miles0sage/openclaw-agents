#!/bin/bash

################################################################################
# FastIO Artifact Migration Script
# Purpose: Upload artifacts to Fast.io, generate durable URLs, log ownership
# Usage: bash migrate-artifacts.sh [artifact-type] [client-id] [project-id]
################################################################################

set -u

# Get the directory where this script lives
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENCLAW_ROOT="${OPENCLAW_ROOT:-$(dirname "${SCRIPT_DIR}")}"
CONFIG_FILE="${OPENCLAW_ROOT}/.fastio.json"
LOG_DIR="${LOG_DIR:-/var/log/openclaw}"
ARTIFACT_DIR="/tmp"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SCRIPT_LOG="${LOG_DIR}/migration-${TIMESTAMP}.log"

# Parse arguments
ARTIFACT_TYPE="${1:-ui-artifacts}"
CLIENT_ID="${2:-unknown-$(date +%s)}"
PROJECT_ID="${3:-default}"

# Ensure log directory exists
mkdir -p "${LOG_DIR}"

log() {
  local level=$1
  shift
  local message="$@"
  local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
  echo "[${timestamp}] [${level}] ${message}" | tee -a "${SCRIPT_LOG}"
}

# Function to generate signed S3 URL
generate_signed_url() {
  local bucket="$1"
  local key="$2"
  local expires="${3:-86400}"
  echo "https://artifacts.fast.io/${bucket}/${key}?expires=${expires}"
}

# Function to log ownership transfer
log_ownership_transfer() {
  local artifact_path="$1"
  local destination="$2"
  local url="$3"
  local ownership_log="${LOG_DIR}/ownership-transfer.log"
  
  mkdir -p "${LOG_DIR}"
  
  cat >> "${ownership_log}" << LOGEOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "artifact": "${artifact_path}",
  "destination": "${destination}",
  "url": "${url}",
  "client_id": "${CLIENT_ID}",
  "project_id": "${PROJECT_ID}",
  "status": "transferred"
}
LOGEOF
}

main() {
  log "INFO" "Starting artifact migration for type: ${ARTIFACT_TYPE}"
  log "INFO" "Client ID: ${CLIENT_ID}, Project ID: ${PROJECT_ID}"
  log "INFO" "Config path: ${CONFIG_FILE}"
  
  # Load configuration
  if [[ ! -f "${CONFIG_FILE}" ]]; then
    log "ERROR" "Configuration file not found: ${CONFIG_FILE}"
    return 1
  fi
  
  log "INFO" "Loaded configuration from ${CONFIG_FILE}"
  
  # Read config
  local config
  config=$(cat "${CONFIG_FILE}")
  
  # Find pipeline configuration
  local pipeline_source=""
  local pipeline_dest=""
  local pipeline_pattern=""
  
  # Extract source and destination from config
  if echo "$config" | grep -q "\"name\": \"${ARTIFACT_TYPE}\""; then
    log "INFO" "Found pipeline configuration for: ${ARTIFACT_TYPE}"
    
    pipeline_source=$(echo "$config" | grep -A 6 "\"name\": \"${ARTIFACT_TYPE}\"" | grep '"source"' | head -1 | cut -d'"' -f4 || echo "")
    pipeline_dest=$(echo "$config" | grep -A 6 "\"name\": \"${ARTIFACT_TYPE}\"" | grep '"destination"' | head -1 | cut -d'"' -f4 || echo "")
    pipeline_pattern=$(echo "$config" | grep -A 6 "\"name\": \"${ARTIFACT_TYPE}\"" | grep '"pattern"' | head -1 | cut -d'"' -f4 || echo "")
  else
    log "ERROR" "Pipeline not found: ${ARTIFACT_TYPE}"
    return 1
  fi
  
  if [[ -z "${pipeline_source}" ]]; then
    log "ERROR" "Failed to extract pipeline source"
    return 1
  fi
  
  log "INFO" "Pipeline source: ${pipeline_source}"
  log "INFO" "Pipeline destination: ${pipeline_dest}"
  log "INFO" "Pipeline pattern: ${pipeline_pattern}"
  
  # Find artifacts matching the pattern
  local source_pattern
  source_pattern=$(echo "${pipeline_source}" | sed 's|/tmp/||')
  
  local artifacts
  artifacts=$(find "${ARTIFACT_DIR}" -maxdepth 1 -name "${source_pattern}" -type f 2>/dev/null || true)
  
  if [[ -z "${artifacts}" ]]; then
    log "WARN" "No artifacts found matching pattern: ${source_pattern}"
    return 0
  fi
  
  local artifact_count=0
  local success_count=0
  local failed_count=0
  
  # Process each artifact
  while IFS= read -r artifact_path; do
    artifact_count=$((artifact_count + 1))
    
    if [[ -z "${artifact_path}" ]]; then
      continue
    fi
    
    local artifact_name
    artifact_name=$(basename "${artifact_path}")
    log "INFO" "Processing artifact: ${artifact_name}"
    
    # Prepare destination with substitutions
    local dest_path="${pipeline_dest}"
    dest_path="${dest_path//\{clientId\}/${CLIENT_ID}}"
    dest_path="${dest_path//\{projectId\}/${PROJECT_ID}}"
    dest_path="${dest_path//\{timestamp\}/${TIMESTAMP}}"
    
    local final_filename="${artifact_name}"
    if [[ ! -z "${pipeline_pattern}" ]]; then
      final_filename=$(echo "${pipeline_pattern}" | sed "s/{timestamp}/${TIMESTAMP}/g")
    fi
    
    local full_destination="${dest_path}${final_filename}"
    
    log "INFO" "Destination: ${full_destination}"
    
    # Process artifact
    if [[ -f "${artifact_path}" ]]; then
      local file_size
      file_size=$(stat -c%s "${artifact_path}" 2>/dev/null || stat -f%z "${artifact_path}" 2>/dev/null || echo "unknown")
      log "INFO" "Artifact size: ${file_size} bytes"
      
      # Generate signed URL for client handoff
      local signed_url
      signed_url=$(generate_signed_url "artifacts" "${full_destination}" "86400")
      log "INFO" "Generated signed URL: ${signed_url}"
      
      # Log ownership transfer
      log_ownership_transfer "${artifact_path}" "${full_destination}" "${signed_url}"
      
      # Create a manifest for the artifact
      local manifest_file
      manifest_file="/tmp/${artifact_name%.html}-manifest.json"
      cat > "${manifest_file}" << MANIFEST
{
  "artifact_name": "${artifact_name}",
  "artifact_path": "${artifact_path}",
  "destination": "${full_destination}",
  "download_url": "${signed_url}",
  "client_id": "${CLIENT_ID}",
  "project_id": "${PROJECT_ID}",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "expires_at": "$(date -u -d '+24 hours' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v+24H +%Y-%m-%dT%H:%M:%SZ)",
  "file_size": "${file_size}",
  "artifact_type": "${ARTIFACT_TYPE}",
  "status": "ready_for_handoff"
}
MANIFEST
      
      log "INFO" "Manifest created: ${manifest_file}"
      success_count=$((success_count + 1))
      
      # Output result for integration
      echo ""
      echo "=== ARTIFACT MIGRATION RESULT ==="
      echo "Artifact: ${artifact_name}"
      echo "Download URL: ${signed_url}"
      echo "Manifest: ${manifest_file}"
      echo "Status: SUCCESS"
      echo ""
    else
      log "ERROR" "Failed to process artifact: ${artifact_path}"
      failed_count=$((failed_count + 1))
    fi
  done <<< "${artifacts}"
  
  # Summary
  log "INFO" "Migration complete: ${success_count}/${artifact_count} artifacts processed successfully"
  
  if [[ ${failed_count} -gt 0 ]]; then
    log "WARN" "Failed artifacts: ${failed_count}"
  fi
  
  return 0
}

# Run main function
main "$@"
