/**
 * Agency Config Loader
 * Loads and caches the agency-config.json file
 */

import { readFileSync } from "node:fs";
import type { AgencyConfig, ProjectConfig } from "./agency.types.js";

let cachedConfig: AgencyConfig | null = null;
let cachedConfigPath: string | null = null;
let lastLoadTime = 0;
const CACHE_TTL_MS = 60000; // Reload every 60 seconds
const DEFAULT_AGENCY_CONFIG_PATH = "/root/agency/agency-config.json";

export function getAgencyConfigPath(): string {
  return process.env.AGENCY_CONFIG_PATH || DEFAULT_AGENCY_CONFIG_PATH;
}

/**
 * Load agency configuration from /root/agency/agency-config.json
 * Uses 60-second caching to avoid filesystem reads on every request
 */
export function loadAgencyConfig(): AgencyConfig {
  const configPath = getAgencyConfigPath();
  const now = Date.now();
  if (cachedConfig && cachedConfigPath === configPath && now - lastLoadTime < CACHE_TTL_MS) {
    return cachedConfig;
  }

  try {
    const raw = readFileSync(configPath, "utf-8");
    cachedConfig = JSON.parse(raw) as AgencyConfig;
    cachedConfigPath = configPath;
    lastLoadTime = now;
    return cachedConfig;
  } catch (err) {
    console.error("Failed to load agency config:", err);
    throw new Error(`Agency config not found or invalid: ${configPath}`);
  }
}

/**
 * Validate Bearer token against MOLTBOT_GATEWAY_TOKEN env var
 */
export function validateAgencyToken(token: string | undefined): boolean {
  if (!token) return false;
  const expectedToken = process.env.MOLTBOT_GATEWAY_TOKEN || "";
  if (!expectedToken) {
    console.warn("MOLTBOT_GATEWAY_TOKEN not set in environment");
    return false;
  }
  return token === expectedToken;
}

/**
 * Get a specific project config by ID
 */
export function getProjectConfig(config: AgencyConfig, projectId: string): ProjectConfig | null {
  return config.projects.find((p) => p.id === projectId) || null;
}

/**
 * Validate that all requested projects exist
 */
export function validateProjects(
  config: AgencyConfig,
  projectIds: string[],
): { valid: boolean; invalidProjects: string[] } {
  const validIds = new Set(config.projects.map((p) => p.id));
  const invalidProjects = projectIds.filter((id) => !validIds.has(id));

  return {
    valid: invalidProjects.length === 0,
    invalidProjects,
  };
}

/**
 * Get all enabled projects (for when no specific projects are requested)
 */
export function getEnabledProjects(config: AgencyConfig): ProjectConfig[] {
  return config.projects;
}

/**
 * Clear cache (for testing or config reload)
 */
export function clearAgencyConfigCache(): void {
  cachedConfig = null;
  cachedConfigPath = null;
  lastLoadTime = 0;
}
