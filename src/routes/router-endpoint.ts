/**
 * Router Endpoint for OpenClaw Gateway
 * REST API for intelligent model routing based on complexity analysis
 * Endpoint: POST /api/route
 *
 * Usage:
 * curl -X POST http://localhost:18789/api/route \
 *   -H "Content-Type: application/json" \
 *   -d '{"query": "How do I implement async/await in TypeScript?"}'
 */

import type { Request, Response } from "express";
import { Router } from "express";
import { logCostEvent, type CostTracker } from "../gateway/cost-tracker.js";
import { getModelPool } from "../gateway/model-pool.js";
import { classify } from "../routing/complexity-classifier.js";

const router = Router();

/**
 * Request body for routing endpoint
 */
export interface RoutingRequest {
  query: string;
  context?: string;
  sessionKey?: string;
}

/**
 * Response body from routing endpoint
 */
export interface RoutingResponse {
  success: boolean;
  timestamp: string;
  model: "haiku" | "sonnet" | "opus";
  complexity: number;
  confidence: number;
  reasoning: string;
  cost_estimate: number;
  estimated_tokens: number;
  metadata: {
    pricing: { input: number; output: number };
    cost_savings_vs_sonnet: number;
    cost_savings_percentage: number;
    rate_limit: { requestsPerMinute: number; tokensPerMinute: number };
  };
  error?: string;
}

/**
 * POST /api/route - Classify query and route to optimal model
 */
router.post("/api/route", async (req: Request, res: Response) => {
  try {
    const { query, context, sessionKey } = req.body as RoutingRequest;

    // Validate input
    if (!query || typeof query !== "string") {
      res.status(400).json({
        success: false,
        timestamp: new Date().toISOString(),
        model: "sonnet" as const,
        complexity: 0,
        confidence: 0,
        reasoning: "Invalid request: query is required and must be a string",
        cost_estimate: 0,
        estimated_tokens: 0,
        metadata: {
          pricing: { input: 0, output: 0 },
          cost_savings_vs_sonnet: 0,
          cost_savings_percentage: 0,
          rate_limit: { requestsPerMinute: 0, tokensPerMinute: 0 },
        },
        error: "Invalid query parameter",
      } as RoutingResponse);
      return;
    }

    // Combine query and context for classification
    const fullQuery = context ? `${query}\n\nContext: ${context}` : query;

    // Classify complexity
    const classification = classify(fullQuery);

    // Get model pool and recommendation
    const modelPool = getModelPool();
    const recommendation = modelPool.getRecommendation(
      classification.complexity,
      Math.floor(classification.estimatedTokens / 3), // Rough split: 1/3 input
      Math.ceil((classification.estimatedTokens * 2) / 3), // 2/3 output
    );

    const modelConfig = recommendation.model;
    const rateLimit = modelPool.getRateLimit(modelConfig.model);

    // Log routing decision
    if (sessionKey) {
      const costEvent: CostTracker = {
        project: "openclaw",
        agent: "router",
        model: modelConfig.alias,
        tokens_input: Math.floor(classification.estimatedTokens / 3),
        tokens_output: Math.ceil((classification.estimatedTokens * 2) / 3),
        cost: recommendation.estimatedCost,
        timestamp: new Date().toISOString(),
      };

      // Log asynchronously (don't block response)
      logCostEvent(costEvent).catch((err) => {
        console.error("Failed to log cost event:", err);
      });
    }

    // Build response
    const response: RoutingResponse = {
      success: true,
      timestamp: new Date().toISOString(),
      model: modelConfig.model,
      complexity: classification.complexity,
      confidence: classification.confidence,
      reasoning: classification.reasoning,
      cost_estimate: recommendation.estimatedCost,
      estimated_tokens: classification.estimatedTokens,
      metadata: {
        pricing: modelConfig.pricing,
        cost_savings_vs_sonnet: recommendation.savingsVsSonnet,
        cost_savings_percentage: recommendation.savingsPercentage,
        rate_limit: rateLimit || { requestsPerMinute: 0, tokensPerMinute: 0 },
      },
    };

    res.status(200).json(response);
  } catch (error) {
    console.error("Router endpoint error:", error);

    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      model: "sonnet" as const,
      complexity: 0,
      confidence: 0,
      reasoning: "Internal server error",
      cost_estimate: 0,
      estimated_tokens: 0,
      metadata: {
        pricing: { input: 0, output: 0 },
        cost_savings_vs_sonnet: 0,
        cost_savings_percentage: 0,
        rate_limit: { requestsPerMinute: 0, tokensPerMinute: 0 },
      },
      error: error instanceof Error ? error.message : "Unknown error",
    } as RoutingResponse);
  }
});

/**
 * POST /api/route/test - Test routing with multiple queries
 */
router.post("/api/route/test", async (req: Request, res: Response) => {
  try {
    const { queries } = req.body as { queries?: string[] };

    if (!queries || !Array.isArray(queries) || queries.length === 0) {
      res.status(400).json({
        success: false,
        error: "queries array is required and must not be empty",
      });
      return;
    }

    const results = queries.map((query) => {
      const classification = classify(query);
      const modelPool = getModelPool();
      const recommendation = modelPool.getRecommendation(
        classification.complexity,
        Math.floor(classification.estimatedTokens / 3),
        Math.ceil((classification.estimatedTokens * 2) / 3),
      );

      return {
        query: query.substring(0, 100) + (query.length > 100 ? "..." : ""),
        model: recommendation.model.model,
        complexity: classification.complexity,
        confidence: classification.confidence,
        cost_estimate: recommendation.estimatedCost,
        savings_percentage: recommendation.savingsPercentage,
      };
    });

    // Calculate aggregate stats
    const stats = {
      total_queries: results.length,
      by_model: {
        haiku: results.filter((r) => r.model === "haiku").length,
        sonnet: results.filter((r) => r.model === "sonnet").length,
        opus: results.filter((r) => r.model === "opus").length,
      },
      avg_complexity: results.reduce((sum, r) => sum + r.complexity, 0) / results.length,
      avg_confidence: results.reduce((sum, r) => sum + r.confidence, 0) / results.length,
      total_estimated_cost: results.reduce((sum, r) => sum + r.cost_estimate, 0),
      avg_savings_percentage:
        results.reduce((sum, r) => sum + r.savings_percentage, 0) / results.length,
    };

    res.status(200).json({
      success: true,
      timestamp: new Date().toISOString(),
      results,
      stats,
    });
  } catch (error) {
    console.error("Router test endpoint error:", error);

    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: error instanceof Error ? error.message : "Unknown error",
    });
  }
});

/**
 * GET /api/route/models - Get available models and pricing
 */
router.get("/api/route/models", (req: Request, res: Response) => {
  try {
    const modelPool = getModelPool();
    const models = modelPool.getAvailableModels();

    const modelInfo = models.map((m) => ({
      name: m.name,
      model: m.model,
      alias: m.alias,
      pricing: m.pricing,
      contextWindow: m.contextWindow,
      maxOutputTokens: m.maxOutputTokens,
      costSavingsPercentage: m.costSavingsPercentage,
      available: m.available,
      rateLimit: m.rateLimit,
    }));

    const distribution = modelPool.getOptimalDistribution();

    res.status(200).json({
      success: true,
      timestamp: new Date().toISOString(),
      models: modelInfo,
      optimalDistribution: {
        haiku: `${(distribution.haiku * 100).toFixed(0)}%`,
        sonnet: `${(distribution.sonnet * 100).toFixed(0)}%`,
        opus: `${(distribution.opus * 100).toFixed(0)}%`,
      },
      expectedCostSavings: "60-70% reduction vs always using Sonnet",
    });
  } catch (error) {
    console.error("Models endpoint error:", error);

    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      error: error instanceof Error ? error.message : "Unknown error",
    });
  }
});

/**
 * GET /api/route/health - Health check
 */
router.get("/api/route/health", (req: Request, res: Response) => {
  try {
    const modelPool = getModelPool();
    const models = modelPool.getAvailableModels();

    res.status(200).json({
      success: true,
      timestamp: new Date().toISOString(),
      status: "healthy",
      models_available: models.length,
      models: models.map((m) => m.model),
    });
  } catch (error) {
    console.error("Health check error:", error);

    res.status(500).json({
      success: false,
      timestamp: new Date().toISOString(),
      status: "unhealthy",
      error: error instanceof Error ? error.message : "Unknown error",
    });
  }
});

export default router;
