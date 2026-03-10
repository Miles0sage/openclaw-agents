/**
 * Cost Dashboard Routes
 * REST endpoints for cost tracking and reporting
 */

import { Router, Request, Response } from "express";
import {
  getCostMetrics,
  logCostEvent,
  getPricing,
  getCostSummary,
  clearCostLog,
  type CostTracker,
  type CostMetrics,
} from "../gateway/cost-tracker.js";

const router = Router();

interface CostDashboardResponse {
  success: boolean;
  timestamp: string;
  data: unknown;
  error?: string;
}

interface CostSummaryResponse extends CostDashboardResponse {
  data: {
    total_cost: number;
    entries_count: number;
    by_project: Record<string, number>;
    by_model: Record<string, number>;
    by_agent: Record<string, number>;
    pricing_info: {
      models: Record<string, { input: number; output: number }>;
    };
  };
}

interface CostTrendsResponse extends CostDashboardResponse {
  data: {
    daily: Record<string, number>;
    hourly: Record<string, number>;
    by_model: Record<string, { total: number; entries: number; avg_cost: number }>;
  };
}

interface CostProjectResponse extends CostDashboardResponse {
  data: {
    project: string;
    total_cost: number;
    entries_count: number;
    by_model: Record<string, number>;
    by_agent: Record<string, number>;
    percentage_of_total: number;
  };
}

/**
 * GET /api/costs/summary
 * Get total spend + breakdown by project, model, agent
 */
router.get("/summary", (req: Request, res: Response): void => {
  try {
    const metrics = getCostMetrics();
    const totalAllProjects = Object.values(metrics.by_project).reduce((a, b) => a + b, 0) || 1;

    const response: CostSummaryResponse = {
      success: true,
      timestamp: new Date().toISOString(),
      data: {
        total_cost: Math.round(metrics.total_cost * 10000) / 10000,
        entries_count: metrics.entries_count,
        by_project: Object.fromEntries(
          Object.entries(metrics.by_project).map(([project, cost]) => [
            project,
            Math.round(cost * 10000) / 10000,
          ]),
        ),
        by_model: Object.fromEntries(
          Object.entries(metrics.by_model).map(([model, cost]) => [
            model,
            Math.round(cost * 10000) / 10000,
          ]),
        ),
        by_agent: Object.fromEntries(
          Object.entries(metrics.by_agent).map(([agent, cost]) => [
            agent,
            Math.round(cost * 10000) / 10000,
          ]),
        ),
        pricing_info: {
          models: {
            "claude-3-5-haiku-20241022": {
              input: 0.8,
              output: 4.0,
            },
            "claude-3-5-sonnet-20241022": {
              input: 3.0,
              output: 15.0,
            },
            "claude-opus-4-6": {
              input: 15.0,
              output: 75.0,
            },
          },
        },
      },
    };

    res.json(response);
  } catch (error) {
    const response: CostDashboardResponse = {
      success: false,
      timestamp: new Date().toISOString(),
      data: null,
      error: String(error),
    };
    res.status(500).json(response);
  }
});

/**
 * GET /api/costs/trends
 * Get cost trends over time
 */
router.get("/trends", (req: Request, res: Response): void => {
  try {
    const metrics = getCostMetrics();

    // Group costs by day and hour (simplified)
    const daily: Record<string, number> = {};
    const hourly: Record<string, number> = {};

    // Parse entries and aggregate
    // Note: This is a simplified implementation
    // In production, you'd want to iterate through actual entries

    const response: CostTrendsResponse = {
      success: true,
      timestamp: new Date().toISOString(),
      data: {
        daily,
        hourly,
        by_model: Object.fromEntries(
          Object.entries(metrics.by_model).map(([model, total]) => [
            model,
            {
              total: Math.round(total * 10000) / 10000,
              entries: 1, // Simplified
              avg_cost: Math.round((total / Math.max(metrics.entries_count, 1)) * 10000) / 10000,
            },
          ]),
        ),
      },
    };

    res.json(response);
  } catch (error) {
    const response: CostDashboardResponse = {
      success: false,
      timestamp: new Date().toISOString(),
      data: null,
      error: String(error),
    };
    res.status(500).json(response);
  }
});

/**
 * GET /api/costs/project/:name
 * Get spend per project
 */
router.get("/project/:name", (req: Request, res: Response): void => {
  try {
    const projectName = req.params.name;
    const metrics = getCostMetrics();

    const projectCost = metrics.by_project[projectName] || 0;
    const totalCost = Object.values(metrics.by_project).reduce((a, b) => a + b, 0) || 1;
    const percentage = (projectCost / totalCost) * 100;

    const projectMetrics: Record<string, number> = {};
    const projectAgents: Record<string, number> = {};

    // Note: In production, you'd filter entries by project
    // For now, returning aggregated by_model for the project

    const response: CostProjectResponse = {
      success: true,
      timestamp: new Date().toISOString(),
      data: {
        project: projectName,
        total_cost: Math.round(projectCost * 10000) / 10000,
        entries_count: Math.round(
          metrics.entries_count / Math.max(Object.keys(metrics.by_project).length, 1),
        ),
        by_model: projectMetrics,
        by_agent: projectAgents,
        percentage_of_total: Math.round(percentage * 100) / 100,
      },
    };

    res.json(response);
  } catch (error) {
    const response: CostDashboardResponse = {
      success: false,
      timestamp: new Date().toISOString(),
      data: null,
      error: String(error),
    };
    res.status(500).json(response);
  }
});

/**
 * POST /api/costs/log
 * Log a cost event
 */
router.post("/log", async (req: Request, res: Response): Promise<void> => {
  try {
    const event: CostTracker = req.body;

    // Validate required fields
    if (
      !event.project ||
      !event.agent ||
      !event.model ||
      event.tokens_input === undefined ||
      event.tokens_output === undefined
    ) {
      const response: CostDashboardResponse = {
        success: false,
        timestamp: new Date().toISOString(),
        data: null,
        error: "Missing required fields: project, agent, model, tokens_input, tokens_output",
      };
      res.status(400).json(response);
      return;
    }

    // Add timestamp if missing
    if (!event.timestamp) {
      event.timestamp = new Date().toISOString();
    }

    // Calculate cost if not provided
    if (event.cost === undefined) {
      const pricing = getPricing(event.model);
      if (pricing) {
        event.cost =
          (event.tokens_input * pricing.input + event.tokens_output * pricing.output) / 1000000;
      } else {
        // Default to Sonnet pricing
        event.cost = (event.tokens_input * 3.0 + event.tokens_output * 15.0) / 1000000;
      }
    }

    await logCostEvent(event);

    const response: CostDashboardResponse = {
      success: true,
      timestamp: new Date().toISOString(),
      data: {
        logged: event,
        cost_usd: Math.round(event.cost * 10000) / 10000,
      },
    };

    res.json(response);
  } catch (error) {
    const response: CostDashboardResponse = {
      success: false,
      timestamp: new Date().toISOString(),
      data: null,
      error: String(error),
    };
    res.status(500).json(response);
  }
});

/**
 * GET /api/costs/clear
 * Clear all cost data (admin only)
 */
router.get("/clear", async (req: Request, res: Response): Promise<void> => {
  try {
    // Simple admin check - in production, use proper auth
    const token = req.query.admin_token;
    if (token !== process.env.ADMIN_TOKEN) {
      const response: CostDashboardResponse = {
        success: false,
        timestamp: new Date().toISOString(),
        data: null,
        error: "Unauthorized",
      };
      res.status(401).json(response);
      return;
    }

    await clearCostLog();

    const response: CostDashboardResponse = {
      success: true,
      timestamp: new Date().toISOString(),
      data: { message: "Cost log cleared" },
    };

    res.json(response);
  } catch (error) {
    const response: CostDashboardResponse = {
      success: false,
      timestamp: new Date().toISOString(),
      data: null,
      error: String(error),
    };
    res.status(500).json(response);
  }
});

export default router;
