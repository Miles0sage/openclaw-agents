/**
 * N8N MCP Client
 * Enables agents to trigger N8N workflows
 * Supports workflow execution with payloads and status tracking
 */

export interface WorkflowPayload {
  action?: string;
  repo?: string;
  branch?: string;
  cost?: number;
  filePath?: string;
  content?: string;
  message?: string;
  [key: string]: unknown;
}

export interface WorkflowRun {
  executionId: string;
  status: "pending" | "running" | "success" | "failed";
  startTime: string;
  endTime?: string;
  output?: unknown;
}

export class N8NClient {
  private webhookUrl: string;
  private retryAttempts = 3;
  private retryDelayMs = 1000;

  constructor(webhookUrl?: string) {
    this.webhookUrl = webhookUrl || process.env.N8N_WEBHOOK_URL || "";
    if (!this.webhookUrl) {
      throw new Error("N8N_WEBHOOK_URL environment variable not set");
    }
  }

  /**
   * Trigger a workflow with exponential backoff retry
   */
  async triggerWorkflow(workflowId: string, payload: WorkflowPayload): Promise<WorkflowRun> {
    let lastError: Error | null = null;

    for (let attempt = 0; attempt < this.retryAttempts; attempt++) {
      try {
        return await this.executeWorkflow(workflowId, payload);
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error));

        if (attempt < this.retryAttempts - 1) {
          const delay = this.retryDelayMs * Math.pow(2, attempt);
          await new Promise((resolve) => setTimeout(resolve, delay));
        }
      }
    }

    throw lastError || new Error("Failed to trigger workflow after retries");
  }

  /**
   * Execute workflow (single attempt)
   */
  private async executeWorkflow(
    workflowId: string,
    payload: WorkflowPayload,
  ): Promise<WorkflowRun> {
    const executionId = `exec-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

    const url = `${this.webhookUrl}?workflowId=${encodeURIComponent(workflowId)}`;

    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...payload,
        executionId,
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`N8N workflow trigger failed ${response.status}: ${error}`);
    }

    const result = (await response.json()) as unknown;

    return {
      executionId,
      status: "pending",
      startTime: new Date().toISOString(),
      output: result,
    };
  }

  /**
   * Get workflow execution status
   * Note: Requires N8N execution tracking endpoint
   */
  async getWorkflowStatus(executionId: string): Promise<WorkflowRun["status"]> {
    try {
      // Try to fetch status from a dedicated endpoint if available
      const url = `${this.webhookUrl.replace(/\/webhook.*/, "")}/executions/${executionId}`;

      const response = await fetch(url, {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        return "pending";
      }

      const data = (await response.json()) as { status?: string };
      const status = data.status || "pending";

      if (status === "success" || status === "completed") {
        return "success";
      }
      if (status === "error" || status === "failed") {
        return "failed";
      }
      if (status === "running") {
        return "running";
      }

      return "pending";
    } catch {
      // If endpoint not available, return pending
      return "pending";
    }
  }

  /**
   * Trigger a deploy workflow
   */
  async triggerDeploy(payload: {
    repo: string;
    branch: string;
    commitSha: string;
  }): Promise<WorkflowRun> {
    return this.triggerWorkflow("deploy", {
      action: "deploy",
      ...payload,
    });
  }

  /**
   * Trigger a test workflow
   */
  async triggerTest(payload: { repo: string; branch: string }): Promise<WorkflowRun> {
    return this.triggerWorkflow("test", {
      action: "test",
      ...payload,
    });
  }

  /**
   * Trigger a Slack notification workflow
   */
  async triggerSlackNotification(payload: {
    channel: string;
    message: string;
    context?: string;
  }): Promise<WorkflowRun> {
    return this.triggerWorkflow("notify-slack", {
      action: "notify",
      ...payload,
    });
  }

  /**
   * Trigger a cost analysis workflow
   */
  async triggerCostAnalysis(payload: {
    repo: string;
    estimatedCost: number;
    threshold?: number;
  }): Promise<WorkflowRun> {
    return this.triggerWorkflow("cost-analysis", {
      action: "analyze-cost",
      ...payload,
    });
  }
}
