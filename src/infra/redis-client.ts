/**
 * Shared Redis client factory.
 *
 * Creates an Upstash-REST-compatible Redis client from environment variables:
 *   - UPSTASH_REDIS_REST_URL
 *   - UPSTASH_REDIS_REST_TOKEN
 *
 * The returned object satisfies the RedisClient interface used by both
 * agency-cost-tracker.ts and monitoring/performance.ts.
 *
 * Returns `null` when the required env vars are not set, so callers can
 * gracefully skip Redis-dependent features.
 */

export interface RedisClient {
  lpush(key: string, ...values: string[]): Promise<number>;
  lrange(key: string, start: number, stop: number): Promise<string[]>;
  incrbyfloat(key: string, increment: number): Promise<number>;
  get(key: string): Promise<string | null>;
  set(key: string, value: string, opts?: { ex?: number }): Promise<string>;
  expire(key: string, seconds: number): Promise<number>;
  del(...keys: string[]): Promise<number>;
}

/**
 * Minimal Upstash REST adapter.
 *
 * Each Redis command is translated into a POST to the Upstash REST endpoint:
 *   POST {baseUrl}
 *   Authorization: Bearer {token}
 *   Body: ["COMMAND", ...args]
 *
 * Upstash responds with: { result: <value> }
 */
function createUpstashRestClient(baseUrl: string, token: string): RedisClient {
  async function command<T = unknown>(...args: (string | number)[]): Promise<T> {
    const res = await fetch(baseUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(args),
    });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`Upstash Redis error ${res.status}: ${body}`);
    }
    const json = (await res.json()) as { result: T };
    return json.result;
  }

  return {
    async lpush(key: string, ...values: string[]): Promise<number> {
      return command<number>("LPUSH", key, ...values);
    },
    async lrange(key: string, start: number, stop: number): Promise<string[]> {
      return command<string[]>("LRANGE", key, String(start), String(stop));
    },
    async incrbyfloat(key: string, increment: number): Promise<number> {
      const result = await command<string>("INCRBYFLOAT", key, String(increment));
      return parseFloat(result);
    },
    async get(key: string): Promise<string | null> {
      return command<string | null>("GET", key);
    },
    async set(key: string, value: string, opts?: { ex?: number }): Promise<string> {
      if (opts?.ex) {
        return command<string>("SET", key, value, "EX", opts.ex);
      }
      return command<string>("SET", key, value);
    },
    async expire(key: string, seconds: number): Promise<number> {
      return command<number>("EXPIRE", key, String(seconds));
    },
    async del(...keys: string[]): Promise<number> {
      return command<number>("DEL", ...keys);
    },
  };
}

/**
 * Create a Redis client from environment variables.
 * Returns `null` if the required env vars are missing.
 */
export function createRedisClient(): RedisClient | null {
  const url = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;

  if (!url || !token) {
    return null;
  }

  return createUpstashRestClient(url, token);
}
