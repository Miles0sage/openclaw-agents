// Type definitions
export interface LLMCallData {
  user_id: string;
  model: string;
  tool_used: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  success: boolean;
  error_message?: string;
}

export interface LLMCallRecord extends LLMCallData {
  id: string;
  total_tokens: number;
  cost_usd: number;
  created_at: string;
}

export interface CostSummary {
  total_cost_usd: number;
  call_count: number;
  avg_latency_ms: number;
  top_tools: Array<{ tool: string; count: number; cost_usd: number }>;
  breakdown_by_model: Array<{ model: string; calls: number; cost_usd: number }>;
  period: string;
}

// Generate a unique ID (simple UUID-like)
function generateId(): string {
  const timestamp = Date.now().toString(36);
  const randomStr = Math.random().toString(36).substring(2, 9);
  return `${timestamp}-${randomStr}`;
}

// Get cost per token for a model
function getCostPerToken(model: string): { input: number; output: number } {
  // Cost in USD per million tokens
  const modelCosts: Record<string, { input: number; output: number }> = {
    'deepseek-chat': { input: 0.27, output: 1.1 },
    'deepseek-v3': { input: 0.27, output: 1.1 },
    'gemini-2.5-flash-lite': { input: 0.075, output: 0.3 },
  };

  const costs = modelCosts[model] || { input: 0.5, output: 2.0 };
  // Convert per-million to per-token
  return {
    input: costs.input / 1_000_000,
    output: costs.output / 1_000_000,
  };
}

// Calculate cost in USD
function calculateCost(
  model: string,
  inputTokens: number,
  outputTokens: number
): number {
  const costs = getCostPerToken(model);
  const totalCost = inputTokens * costs.input + outputTokens * costs.output;
  return parseFloat(totalCost.toFixed(6));
}

// Initialize analytics tables
export async function initializeAnalyticsTables(db: D1Database): Promise<void> {
  // Create llm_calls table
  await db.prepare(`
    CREATE TABLE IF NOT EXISTS llm_calls (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL,
      model TEXT NOT NULL,
      tool_used TEXT NOT NULL,
      input_tokens INTEGER NOT NULL,
      output_tokens INTEGER NOT NULL,
      total_tokens INTEGER NOT NULL,
      cost_usd REAL NOT NULL,
      latency_ms INTEGER NOT NULL,
      success BOOLEAN NOT NULL,
      error_message TEXT,
      created_at TEXT NOT NULL
    )
  `).run();

  // Create indexes for common queries
  await db
    .prepare(`CREATE INDEX IF NOT EXISTS idx_llm_calls_user_id ON llm_calls(user_id)`)
    .run();

  await db
    .prepare(
      `CREATE INDEX IF NOT EXISTS idx_llm_calls_created_at ON llm_calls(created_at)`
    )
    .run();

  await db
    .prepare(`CREATE INDEX IF NOT EXISTS idx_llm_calls_model ON llm_calls(model)`)
    .run();

  await db
    .prepare(`CREATE INDEX IF NOT EXISTS idx_llm_calls_tool ON llm_calls(tool_used)`)
    .run();
}

// Log an LLM API call
export async function logLLMCall(
  db: D1Database,
  data: LLMCallData
): Promise<LLMCallRecord> {
  const id = generateId();
  const totalTokens = data.input_tokens + data.output_tokens;
  const costUsd = calculateCost(data.model, data.input_tokens, data.output_tokens);
  const createdAt = new Date().toISOString();

  const record: LLMCallRecord = {
    id,
    ...data,
    total_tokens: totalTokens,
    cost_usd: costUsd,
    created_at: createdAt,
  };

  await db
    .prepare(
      `
    INSERT INTO llm_calls (
      id, user_id, model, tool_used, input_tokens, output_tokens,
      total_tokens, cost_usd, latency_ms, success, error_message, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `
    )
    .bind(
      record.id,
      record.user_id,
      record.model,
      record.tool_used,
      record.input_tokens,
      record.output_tokens,
      record.total_tokens,
      record.cost_usd,
      record.latency_ms,
      record.success ? 1 : 0,
      record.error_message || null,
      record.created_at
    )
    .run();

  return record;
}

// Get cost summary for a user
export async function getCostSummary(
  db: D1Database,
  userId: string,
  period: 'today' | 'week' | 'month' | 'all' = 'today'
): Promise<CostSummary> {
  const now = new Date();
  let startDate: Date;

  switch (period) {
    case 'today':
      startDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      break;
    case 'week':
      startDate = new Date(now);
      startDate.setDate(startDate.getDate() - 7);
      break;
    case 'month':
      startDate = new Date(now);
      startDate.setMonth(startDate.getMonth() - 1);
      break;
    case 'all':
      startDate = new Date('2000-01-01');
      break;
  }

  const startDateStr = startDate.toISOString();

  // Get aggregate cost and call count
  const summaryResult = await db
    .prepare(
      `
    SELECT
      COALESCE(SUM(cost_usd), 0) as total_cost,
      COUNT(*) as call_count,
      ROUND(AVG(latency_ms), 0) as avg_latency
    FROM llm_calls
    WHERE user_id = ? AND created_at >= ?
  `
    )
    .bind(userId, startDateStr)
    .first<{
      total_cost: number;
      call_count: number;
      avg_latency: number;
    }>();

  // Get top tools
  const topToolsResult = await db
    .prepare(
      `
    SELECT
      tool_used,
      COUNT(*) as count,
      ROUND(SUM(cost_usd), 6) as cost_usd
    FROM llm_calls
    WHERE user_id = ? AND created_at >= ?
    GROUP BY tool_used
    ORDER BY count DESC
    LIMIT 10
  `
    )
    .bind(userId, startDateStr)
    .all<{ tool_used: string; count: number; cost_usd: number }>();

  // Get breakdown by model
  const modelBreakdownResult = await db
    .prepare(
      `
    SELECT
      model,
      COUNT(*) as calls,
      ROUND(SUM(cost_usd), 6) as cost_usd
    FROM llm_calls
    WHERE user_id = ? AND created_at >= ?
    GROUP BY model
    ORDER BY cost_usd DESC
  `
    )
    .bind(userId, startDateStr)
    .all<{ model: string; calls: number; cost_usd: number }>();

  return {
    total_cost_usd: parseFloat((summaryResult?.total_cost || 0).toFixed(6)),
    call_count: summaryResult?.call_count || 0,
    avg_latency_ms: summaryResult?.avg_latency || 0,
    top_tools:
      topToolsResult?.results?.map((row) => ({
        tool: row.tool_used,
        count: row.count,
        cost_usd: row.cost_usd,
      })) || [],
    breakdown_by_model:
      modelBreakdownResult?.results?.map((row) => ({
        model: row.model,
        calls: row.calls,
        cost_usd: row.cost_usd,
      })) || [],
    period,
  };
}

// Get recent calls for a user
export async function getRecentCalls(
  db: D1Database,
  userId: string,
  limit: number = 20
): Promise<LLMCallRecord[]> {
  const result = await db
    .prepare(
      `
    SELECT
      id, user_id, model, tool_used, input_tokens, output_tokens,
      total_tokens, cost_usd, latency_ms, success, error_message, created_at
    FROM llm_calls
    WHERE user_id = ?
    ORDER BY created_at DESC
    LIMIT ?
  `
    )
    .bind(userId, limit)
    .all<LLMCallRecord>();

  return (
    result?.results?.map((row) => ({
      ...row,
      success: row.success ? true : false,
    })) || []
  );
}

// Get cost stats for debugging/monitoring
export async function getCostStats(db: D1Database): Promise<{
  total_calls: number;
  total_cost_usd: number;
  avg_cost_per_call: number;
  last_24h_cost: number;
}> {
  const now = new Date();
  const oneDayAgo = new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString();

  const globalStats = await db
    .prepare(
      `
    SELECT
      COUNT(*) as total_calls,
      ROUND(SUM(cost_usd), 6) as total_cost,
      ROUND(AVG(cost_usd), 6) as avg_cost
    FROM llm_calls
  `
    )
    .first<{
      total_calls: number;
      total_cost: number;
      avg_cost: number;
    }>();

  const last24hStats = await db
    .prepare(
      `
    SELECT ROUND(SUM(cost_usd), 6) as cost
    FROM llm_calls
    WHERE created_at >= ?
  `
    )
    .bind(oneDayAgo)
    .first<{ cost: number }>();

  return {
    total_calls: globalStats?.total_calls || 0,
    total_cost_usd: parseFloat((globalStats?.total_cost || 0).toFixed(6)),
    avg_cost_per_call: parseFloat((globalStats?.avg_cost || 0).toFixed(6)),
    last_24h_cost: parseFloat((last24hStats?.cost || 0).toFixed(6)),
  };
}
