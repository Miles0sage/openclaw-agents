/**
 * Model Pool Configuration & Management
 * Manages available models, pricing, rate limits, and selection logic
 * Supports Feb 2026 Claude API rates for cost optimization
 */

export interface ModelConfig {
  name: string;
  model: "haiku" | "sonnet" | "opus";
  provider: "anthropic" | "openai" | "other";
  alias: string;
  pricing: {
    input: number; // per million tokens
    output: number; // per million tokens
  };
  rateLimit: {
    requestsPerMinute: number;
    tokensPerMinute: number;
  };
  contextWindow: number;
  maxOutputTokens: number;
  available: boolean;
  costSavingsPercentage: number; // Relative to baseline (Sonnet = 0%)
}

/**
 * Pricing constants (Feb 2026 Claude API rates)
 */
const CLAUDE_PRICING = {
  haiku: {
    input: 0.8, // $0.80 per million input tokens
    output: 4.0, // $4.00 per million output tokens
  },
  sonnet: {
    input: 3.0, // $3.00 per million input tokens
    output: 15.0, // $15.00 per million output tokens
  },
  opus: {
    input: 15.0, // $15.00 per million input tokens
    output: 75.0, // $75.00 per million output tokens
  },
};

/**
 * Base cost per token for Sonnet (used for comparison)
 */
const SONNET_BASE_COST = (3.0 + 15.0) / 2; // Average per million tokens

/**
 * Model Pool Manager
 */
export class ModelPool {
  private models: Map<string, ModelConfig> = new Map();

  constructor() {
    this.initializeModels();
  }

  /**
   * Initialize default model configurations
   */
  private initializeModels(): void {
    // Haiku - Fast & Cheap (70% of queries)
    this.models.set("haiku", {
      name: "Claude 3.5 Haiku",
      model: "haiku",
      provider: "anthropic",
      alias: "claude-3-5-haiku-20241022",
      pricing: CLAUDE_PRICING.haiku,
      rateLimit: {
        requestsPerMinute: 100,
        tokensPerMinute: 500000,
      },
      contextWindow: 200000,
      maxOutputTokens: 4096,
      available: true,
      costSavingsPercentage: -75, // 75% cheaper than Sonnet
    });

    // Sonnet - Balanced (20% of queries)
    this.models.set("sonnet", {
      name: "Claude 3.5 Sonnet",
      model: "sonnet",
      provider: "anthropic",
      alias: "claude-3-5-sonnet-20241022",
      pricing: CLAUDE_PRICING.sonnet,
      rateLimit: {
        requestsPerMinute: 50,
        tokensPerMinute: 200000,
      },
      contextWindow: 200000,
      maxOutputTokens: 4096,
      available: true,
      costSavingsPercentage: 0, // Baseline
    });

    // Opus - Powerful (10% of queries)
    this.models.set("opus", {
      name: "Claude Opus 4.6",
      model: "opus",
      provider: "anthropic",
      alias: "claude-opus-4-6",
      pricing: CLAUDE_PRICING.opus,
      rateLimit: {
        requestsPerMinute: 25,
        tokensPerMinute: 100000,
      },
      contextWindow: 200000,
      maxOutputTokens: 4096,
      available: true,
      costSavingsPercentage: 400, // 400% more expensive than Sonnet
    });
  }

  /**
   * Select model based on complexity score (0-100)
   * Returns the best model for the given complexity
   */
  public selectModel(complexity: number): ModelConfig {
    if (complexity <= 30) {
      // Low complexity: use Haiku
      return this.models.get("haiku")!;
    } else if (complexity < 70) {
      // Medium complexity: use Sonnet
      return this.models.get("sonnet")!;
    } else {
      // High complexity: use Opus
      return this.models.get("opus")!;
    }
  }

  /**
   * Get model configuration by name
   */
  public getModelConfig(model: string): ModelConfig | null {
    return this.models.get(model.toLowerCase()) || null;
  }

  /**
   * Get all available models
   */
  public getAvailableModels(): ModelConfig[] {
    return Array.from(this.models.values()).filter((m) => m.available);
  }

  /**
   * Get pricing for a model
   */
  public getPricing(model: string): { input: number; output: number } | null {
    const config = this.getModelConfig(model);
    return config ? config.pricing : null;
  }

  /**
   * Calculate cost for token usage
   */
  public calculateCost(model: string, inputTokens: number, outputTokens: number): number {
    const pricing = this.getPricing(model);
    if (!pricing) return 0;

    return (inputTokens * pricing.input + outputTokens * pricing.output) / 1000000;
  }

  /**
   * Get cost breakdown for routing comparison
   */
  public getCostComparison(
    inputTokens: number,
    outputTokens: number,
  ): {
    haiku: number;
    sonnet: number;
    opus: number;
  } {
    return {
      haiku: this.calculateCost("haiku", inputTokens, outputTokens),
      sonnet: this.calculateCost("sonnet", inputTokens, outputTokens),
      opus: this.calculateCost("opus", inputTokens, outputTokens),
    };
  }

  /**
   * Get savings percentage vs Sonnet baseline
   */
  public getSavingsPercentage(model: string): number {
    const config = this.getModelConfig(model);
    return config ? config.costSavingsPercentage : 0;
  }

  /**
   * Get model recommendation with cost savings estimate
   */
  public getRecommendation(
    complexity: number,
    estimatedInputTokens: number,
    estimatedOutputTokens: number,
  ): {
    model: ModelConfig;
    estimatedCost: number;
    savingsVsSonnet: number;
    savingsPercentage: number;
  } {
    const selectedModel = this.selectModel(complexity);
    const cost = this.calculateCost(
      selectedModel.model,
      estimatedInputTokens,
      estimatedOutputTokens,
    );
    const sonnetCost = this.calculateCost("sonnet", estimatedInputTokens, estimatedOutputTokens);
    const savings = sonnetCost - cost;
    const savingsPercentage = sonnetCost > 0 ? (savings / sonnetCost) * 100 : 0;

    return {
      model: selectedModel,
      estimatedCost: cost,
      savingsVsSonnet: Math.max(0, savings),
      savingsPercentage: Math.round(savingsPercentage * 100) / 100,
    };
  }

  /**
   * Get routing distribution for optimal cost (70% Haiku, 20% Sonnet, 10% Opus)
   */
  public getOptimalDistribution(): {
    haiku: number;
    sonnet: number;
    opus: number;
  } {
    return {
      haiku: 0.7, // 70%
      sonnet: 0.2, // 20%
      opus: 0.1, // 10%
    };
  }

  /**
   * Calculate aggregate cost savings from routing
   * Assumes all queries would normally use Sonnet
   */
  public calculateRoutingSavings(
    totalInputTokens: number,
    totalOutputTokens: number,
  ): {
    totalWithoutRouting: number;
    totalWithRouting: number;
    savings: number;
    savingsPercentage: number;
  } {
    const dist = this.getOptimalDistribution();

    // Cost without routing (all Sonnet)
    const totalWithoutRouting = this.calculateCost("sonnet", totalInputTokens, totalOutputTokens);

    // Cost with routing
    const haikusCost = this.calculateCost(
      "haiku",
      Math.floor(totalInputTokens * dist.haiku),
      Math.floor(totalOutputTokens * dist.haiku),
    );
    const sonnetsCost = this.calculateCost(
      "sonnet",
      Math.floor(totalInputTokens * dist.sonnet),
      Math.floor(totalOutputTokens * dist.sonnet),
    );
    const opusCost = this.calculateCost(
      "opus",
      Math.floor(totalInputTokens * dist.opus),
      Math.floor(totalOutputTokens * dist.opus),
    );
    const totalWithRouting = haikusCost + sonnetsCost + opusCost;

    const savings = totalWithoutRouting - totalWithRouting;
    const savingsPercentage = totalWithoutRouting > 0 ? (savings / totalWithoutRouting) * 100 : 0;

    return {
      totalWithoutRouting,
      totalWithRouting,
      savings: Math.max(0, savings),
      savingsPercentage: Math.round(savingsPercentage * 100) / 100,
    };
  }

  /**
   * Get rate limit for model
   */
  public getRateLimit(
    model: string,
  ): { requestsPerMinute: number; tokensPerMinute: number } | null {
    const config = this.getModelConfig(model);
    return config ? config.rateLimit : null;
  }

  /**
   * Check if model is available
   */
  public isAvailable(model: string): boolean {
    const config = this.getModelConfig(model);
    return config ? config.available : false;
  }

  /**
   * Set model availability status
   */
  public setAvailability(model: string, available: boolean): void {
    const config = this.getModelConfig(model);
    if (config) {
      config.available = available;
    }
  }
}

/**
 * Singleton instance
 */
let instance: ModelPool | null = null;

/**
 * Get or create ModelPool instance
 */
export function getModelPool(): ModelPool {
  if (!instance) {
    instance = new ModelPool();
  }
  return instance;
}

/**
 * Reset singleton (for testing)
 */
export function resetModelPool(): void {
  instance = null;
}
