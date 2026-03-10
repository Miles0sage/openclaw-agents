/**
 * Monitoring Routes
 * REST API endpoints for dashboard, alerts, and metrics
 */

import type { Request, Response } from "express";
import { Router } from "express";
import { alertManager } from "../monitoring/alerts.js";
import { dashboard } from "../monitoring/dashboard.js";
import { eventLogger } from "../monitoring/event-logger.js";
import { metricsCollector } from "../monitoring/metrics.js";

const router = Router();

/**
 * GET /api/dashboard-state
 * Get complete dashboard state
 */
router.get("/state", async (req: Request, res: Response): Promise<void> => {
  try {
    const state = await dashboard.getDashboardState();
    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      data: state,
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: String(error),
    });
  }
});

/**
 * GET /api/agents
 * Get all agent statuses
 */
router.get("/agents", async (req: Request, res: Response): Promise<void> => {
  try {
    const agents = await dashboard.getAgentStatus();
    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      data: agents,
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: String(error),
    });
  }
});

/**
 * POST /api/agents/:agentId/status
 * Update agent status
 */
router.post("/agents/:agentId/status", async (req: Request, res: Response): Promise<void> => {
  try {
    const { agentId } = req.params;
    await dashboard.updateAgentStatus(agentId, req.body);

    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      data: { message: `Agent ${agentId} status updated` },
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: String(error),
    });
  }
});

/**
 * GET /api/costs
 * Get cost summary
 */
router.get("/costs", async (req: Request, res: Response): Promise<void> => {
  try {
    const costs = await dashboard.getCostSummary();
    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      data: costs,
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: String(error),
    });
  }
});

/**
 * POST /api/costs/update
 * Update cost tracking
 */
router.post("/costs/update", async (req: Request, res: Response): Promise<void> => {
  try {
    await dashboard.updateCosts(req.body);

    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      data: { message: "Costs updated" },
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: String(error),
    });
  }
});

/**
 * GET /api/alerts
 * Get active and historical alerts
 */
router.get("/alerts", async (req: Request, res: Response): Promise<void> => {
  try {
    const acknowledged = req.query.acknowledged ? req.query.acknowledged === "true" : undefined;
    const alerts = await dashboard.getAlerts(acknowledged);

    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      data: alerts,
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: String(error),
    });
  }
});

/**
 * POST /api/alerts/create
 * Create a new alert
 */
router.post("/alerts/create", async (req: Request, res: Response): Promise<void> => {
  try {
    const { type, message, context } = req.body;

    if (!type || !message) {
      res.status(400).json({
        success: false,
        timestamp: new Date().toISOString(),
        error: "Missing required fields: type, message",
      });
      return;
    }

    const alert = await alertManager.createAlert(type, message, context);

    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      data: alert,
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: String(error),
    });
  }
});

/**
 * POST /api/alerts/:alertId/acknowledge
 * Acknowledge an alert
 */
router.post("/alerts/:alertId/acknowledge", async (req: Request, res: Response): Promise<void> => {
  try {
    const { alertId } = req.params;
    await alertManager.acknowledgeAlert(alertId);

    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      data: { message: `Alert ${alertId} acknowledged` },
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: String(error),
    });
  }
});

/**
 * GET /api/metrics
 * Get aggregated metrics
 */
router.get("/metrics", async (req: Request, res: Response): Promise<void> => {
  try {
    const metrics = await dashboard.getMetrics();

    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      data: metrics,
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: String(error),
    });
  }
});

/**
 * POST /api/metrics/record
 * Record a task metric
 */
router.post("/metrics/record", async (req: Request, res: Response): Promise<void> => {
  try {
    await metricsCollector.recordTask(req.body);

    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      data: { message: "Metric recorded" },
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: String(error),
    });
  }
});

/**
 * GET /api/metrics/project/:projectId
 * Get metrics for a specific project
 */
router.get("/metrics/project/:projectId", async (req: Request, res: Response): Promise<void> => {
  try {
    const { projectId } = req.params;
    const stats = await metricsCollector.getMetricsByProject(projectId);

    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      data: stats,
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: String(error),
    });
  }
});

/**
 * GET /api/events
 * Get recent events
 */
router.get("/events", async (req: Request, res: Response): Promise<void> => {
  try {
    const type = req.query.type ? String(req.query.type) : undefined;
    const level = req.query.level ? String(req.query.level) : undefined;

    const events = await eventLogger.getEvents({ type, level });

    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      data: events.slice(-100), // Return last 100 events
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: String(error),
    });
  }
});

/**
 * POST /api/events/log
 * Log an event
 */
router.post("/events/log", async (req: Request, res: Response): Promise<void> => {
  try {
    const { type, data, agentId, taskId, projectId, level } = req.body;

    if (!type || !data) {
      res.status(400).json({
        success: false,
        timestamp: new Date().toISOString(),
        error: "Missing required fields: type, data",
      });
      return;
    }

    await eventLogger.logEvent(type, data, { agentId, taskId, projectId, level });

    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      data: { message: "Event logged" },
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: String(error),
    });
  }
});

export default router;
