/**
 * Performance Profiler
 * Track per-agent latency percentiles, token usage, channel stats, and error rates
 * Uses Redis for persistence (compatible with the RedisClient interface from agency-cost-tracker)
 */

export interface PerformanceMetric {
  agent: string;
  channel: "slack" | "discord" | "telegram" | "whatsapp" | "api";
  latencyMs: number;
  tokensGenerated: number;
  success: boolean;
  timestamp?: string; // ISO string, defaults to now
}

interface RedisClient {
  lpush(key: string, ...values: string[]): Promise<number>;
  lrange(key: string, start: number, stop: number): Promise<string[]>;
  incrbyfloat(key: string, increment: number): Promise<number>;
  get(key: string): Promise<string | null>;
  set(key: string, value: string, opts?: { ex?: number }): Promise<string>;
  expire(key: string, seconds: number): Promise<number>;
  del(...keys: string[]): Promise<number>;
}

interface StoredMetric extends PerformanceMetric {
  timestamp: string;
}

export interface ChannelStats {
  channel: string;
  totalRequests: number;
  successCount: number;
  failureCount: number;
  errorRate: number;
  avgLatencyMs: number;
  avgTokensGenerated: number;
}

export interface AgentStats {
  agent: string;
  totalRequests: number;
  successCount: number;
  failureCount: number;
  errorRate: number;
  p50LatencyMs: number;
  p95LatencyMs: number;
  p99LatencyMs: number;
  avgTokensGenerated: number;
}

export interface LatencyBucket {
  le: number; // upper bound in ms
  count: number;
}

const REDIS_KEY_PREFIX = "openclaw:perf:";
const METRICS_LIST_KEY = `${REDIS_KEY_PREFIX}metrics`;
const MAX_STORED_METRICS = 50000;
const DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60; // 7 days

export class PerformanceProfiler {
  private redis: RedisClient | null = null;

  /**
   * Initialize with a Redis client (same interface as agency-cost-tracker)
   */
  init(client: RedisClient): void {
    this.redis = client;
  }

  private getClient(): RedisClient {
    if (!this.redis) {
      throw new Error("PerformanceProfiler not initialized. Call init() with a RedisClient first.");
    }
    return this.redis;
  }

  /**
   * Record a single performance metric
   */
  async recordMetric(metric: PerformanceMetric): Promise<void> {
    const client = this.getClient();

    const stored: StoredMetric = {
      ...metric,
      timestamp: metric.timestamp || new Date().toISOString(),
    };

    try {
      const serialized = JSON.stringify(stored);
      await client.lpush(METRICS_LIST_KEY, serialized);
      await client.expire(METRICS_LIST_KEY, DEFAULT_TTL_SECONDS);

      // Bump per-agent and per-channel counters for fast lookups
      const agentKey = `${REDIS_KEY_PREFIX}agent:${metric.agent}:count`;
      const channelKey = `${REDIS_KEY_PREFIX}channel:${metric.channel}:count`;
      await client.incrbyfloat(agentKey, 1);
      await client.expire(agentKey, DEFAULT_TTL_SECONDS);
      await client.incrbyfloat(channelKey, 1);
      await client.expire(channelKey, DEFAULT_TTL_SECONDS);

      if (!metric.success) {
        const errKey = `${REDIS_KEY_PREFIX}agent:${metric.agent}:errors`;
        await client.incrbyfloat(errKey, 1);
        await client.expire(errKey, DEFAULT_TTL_SECONDS);
      }
    } catch (err) {
      console.error("PerformanceProfiler: failed to record metric:", err);
    }
  }

  /**
   * Get p95 latency in ms, optionally filtered by agent
   */
  async getP95Latency(agent?: string): Promise<number> {
    const metrics = await this.loadMetrics(agent);
    if (metrics.length === 0) return 0;
    return this.percentile(
      metrics.map((m) => m.latencyMs),
      95,
    );
  }

  /**
   * Get error rate as a percentage (0-100), optionally filtered by agent
   */
  async getErrorRate(agent?: string): Promise<number> {
    const metrics = await this.loadMetrics(agent);
    if (metrics.length === 0) return 0;

    const failures = metrics.filter((m) => !m.success).length;
    return Math.round((failures / metrics.length) * 10000) / 100;
  }

  /**
   * Get aggregated stats per channel
   */
  async getChannelStats(): Promise<ChannelStats[]> {
    const metrics = await this.loadMetrics();
    if (metrics.length === 0) return [];

    const grouped = this.groupBy(metrics, (m) => m.channel);
    const stats: ChannelStats[] = [];

    for (const [channel, items] of Object.entries(grouped)) {
      const successCount = items.filter((m) => m.success).length;
      const failureCount = items.length - successCount;
      const avgLatency = items.reduce((s, m) => s + m.latencyMs, 0) / items.length;
      const avgTokens = items.reduce((s, m) => s + m.tokensGenerated, 0) / items.length;

      stats.push({
        channel,
        totalRequests: items.length,
        successCount,
        failureCount,
        errorRate: Math.round((failureCount / items.length) * 10000) / 100,
        avgLatencyMs: Math.round(avgLatency * 100) / 100,
        avgTokensGenerated: Math.round(avgTokens * 100) / 100,
      });
    }

    return stats.sort((a, b) => b.totalRequests - a.totalRequests);
  }

  /**
   * Get aggregated stats per agent including latency percentiles
   */
  async getAgentStats(): Promise<AgentStats[]> {
    const metrics = await this.loadMetrics();
    if (metrics.length === 0) return [];

    const grouped = this.groupBy(metrics, (m) => m.agent);
    const stats: AgentStats[] = [];

    for (const [agent, items] of Object.entries(grouped)) {
      const latencies = items.map((m) => m.latencyMs);
      const successCount = items.filter((m) => m.success).length;
      const failureCount = items.length - successCount;
      const avgTokens = items.reduce((s, m) => s + m.tokensGenerated, 0) / items.length;

      stats.push({
        agent,
        totalRequests: items.length,
        successCount,
        failureCount,
        errorRate: Math.round((failureCount / items.length) * 10000) / 100,
        p50LatencyMs: this.percentile(latencies, 50),
        p95LatencyMs: this.percentile(latencies, 95),
        p99LatencyMs: this.percentile(latencies, 99),
        avgTokensGenerated: Math.round(avgTokens * 100) / 100,
      });
    }

    return stats.sort((a, b) => b.totalRequests - a.totalRequests);
  }

  /**
   * Get a latency histogram for a specific agent with custom bucket boundaries
   * Each bucket counts requests with latency <= the bucket upper bound.
   * Buckets are cumulative (like Prometheus histograms).
   */
  async getLatencyHistogram(agent: string, buckets: number[]): Promise<LatencyBucket[]> {
    const metrics = await this.loadMetrics(agent);
    const latencies = metrics.map((m) => m.latencyMs);
    const sorted = [...buckets].sort((a, b) => a - b);

    return sorted.map((le) => ({
      le,
      count: latencies.filter((l) => l <= le).length,
    }));
  }

  /**
   * Load raw metrics from Redis, optionally filtered by agent
   */
  private async loadMetrics(agent?: string): Promise<StoredMetric[]> {
    const client = this.getClient();

    try {
      const raw = await client.lrange(METRICS_LIST_KEY, 0, MAX_STORED_METRICS - 1);
      let metrics: StoredMetric[] = [];

      for (const entry of raw) {
        try {
          metrics.push(JSON.parse(entry) as StoredMetric);
        } catch {
          // skip malformed entries
        }
      }

      if (agent) {
        metrics = metrics.filter((m) => m.agent === agent);
      }

      return metrics;
    } catch (err) {
      console.error("PerformanceProfiler: failed to load metrics:", err);
      return [];
    }
  }

  /**
   * Compute the p-th percentile from an array of numbers
   */
  private percentile(values: number[], p: number): number {
    if (values.length === 0) return 0;

    const sorted = [...values].sort((a, b) => a - b);
    const index = (p / 100) * (sorted.length - 1);
    const lower = Math.floor(index);
    const upper = Math.ceil(index);

    if (lower === upper) {
      return Math.round(sorted[lower] * 100) / 100;
    }

    // Linear interpolation between the two nearest ranks
    const weight = index - lower;
    const result = sorted[lower] * (1 - weight) + sorted[upper] * weight;
    return Math.round(result * 100) / 100;
  }

  /**
   * Group an array by a key function
   */
  private groupBy<T>(items: T[], keyFn: (item: T) => string): Record<string, T[]> {
    const groups: Record<string, T[]> = {};
    for (const item of items) {
      const key = keyFn(item);
      if (!groups[key]) {
        groups[key] = [];
      }
      groups[key].push(item);
    }
    return groups;
  }
}

export const performanceProfiler = new PerformanceProfiler();
