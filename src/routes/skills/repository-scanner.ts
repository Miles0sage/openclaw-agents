/**
 * API endpoint for Repository Scanner Skill
 * Agents call: POST /api/skills/repository-scanner
 *
 * Example request:
 * {
 *   "action": "analyze",
 *   "repos": ["https://github.com/Miles0sage/Barber-CRM.git"]
 * }
 */

import { Hono } from "hono";
import {
  analyzeRepository,
  analyzeRepositories,
  generateMarkdownSummary,
} from "../../skills/repository-scanner.js";

const app = new Hono();

/**
 * POST /api/skills/repository-scanner
 * Analyze one or more GitHub repositories
 */
app.post("/api/skills/repository-scanner", async (c) => {
  try {
    const { action, repos, url } = await c.req.json();

    if (!action || (!repos && !url)) {
      return c.json({ error: "Missing required fields: action and (repos or url)" }, 400);
    }

    let results;

    if (action === "analyze") {
      if (repos && Array.isArray(repos)) {
        // Batch analyze
        results = await analyzeRepositories(repos);
      } else if (url) {
        // Single analyze
        const analysis = await analyzeRepository(url);
        results = [analysis];
      } else {
        return c.json({ error: "Missing url or repos array" }, 400);
      }
    } else if (action === "analyze_and_summarize") {
      // Analyze + generate markdown summaries
      if (repos && Array.isArray(repos)) {
        const analyses = await analyzeRepositories(repos);
        results = analyses.map((a) => ({
          ...a,
          markdown: generateMarkdownSummary(a),
        }));
      } else if (url) {
        const analysis = await analyzeRepository(url);
        results = [
          {
            ...analysis,
            markdown: generateMarkdownSummary(analysis),
          },
        ];
      }
    } else {
      return c.json({ error: "Unknown action. Use: analyze or analyze_and_summarize" }, 400);
    }

    return c.json({
      status: "success",
      action,
      repos: repos || [url],
      results,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    return c.json(
      {
        status: "error",
        error: String(error),
      },
      500,
    );
  }
});

/**
 * GET /api/skills/repository-scanner/health
 * Check if skill is available
 */
app.get("/api/skills/repository-scanner/health", (c) => {
  return c.json({
    status: "healthy",
    skill: "repository-scanner",
    version: "1.0.0",
    capabilities: ["analyze", "analyze_and_summarize"],
    git_auth: "configured",
  });
});

/**
 * POST /api/skills/repository-scanner/batch
 * Batch analyze Miles Sage projects
 */
app.post("/api/skills/repository-scanner/batch", async (c) => {
  const milesProjects = [
    "https://github.com/Miles0sage/Barber-CRM.git",
    "https://github.com/Miles0sage/Delhi-Palce-.git",
    "https://github.com/Miles0sage/Mathcad-Scripts.git",
    "https://github.com/Miles0sage/concrete-canoe-project2026.git",
    "https://github.com/Miles0sage/moltbot-sandbox.git",
  ];

  try {
    const results = await analyzeRepositories(milesProjects);

    return c.json({
      status: "success",
      batch: "miles-sage-projects",
      total: results.length,
      succeeded: results.filter((r) => r.status === "analyzed").length,
      failed: results.filter((r) => r.status === "error").length,
      results,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    return c.json(
      {
        status: "error",
        error: String(error),
      },
      500,
    );
  }
});

export default app;
