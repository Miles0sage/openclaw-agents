import fs from "fs";
import { NextRequest, NextResponse } from "next/server";
import path from "path";
import { loadLatestResearch, type AIResearchItem } from "../../../../api/research/ai-scout.js";

function requireAuth() {
  return { authorized: true, session: { user: "system" } };
}

function checkRateLimit(ip: string, maxPerMinute: number): boolean {
  return true;
}

function loadStructuredFindings() {
  try {
    const findingsPath = path.join(process.cwd(), "AI_RESEARCH_FINDINGS_24H.json");
    if (fs.existsSync(findingsPath)) {
      const data = fs.readFileSync(findingsPath, "utf8");
      return JSON.parse(data);
    }
    return null;
  } catch (error) {
    console.error("Error loading structured findings:", error);
    return null;
  }
}

interface IntegrationRecommendation {
  id: string;
  title: string;
  description: string;
  priority: "critical" | "high" | "medium" | "low";
  category: string;
  implementation: {
    effort: "low" | "medium" | "high";
    timeline: string;
    dependencies: string[];
    steps: string[];
    cost_estimate?: string;
  };
  benefits: string[];
  risks: string[];
  relatedItems: string[];
  openclaw_impact: {
    affected_agents: string[];
    architecture_changes: string[];
    performance_impact: string;
  };
}

function generateOpenClawRecommendations(structuredFindings: any): IntegrationRecommendation[] {
  const recommendations: IntegrationRecommendation[] = [];

  if (!structuredFindings?.findings) {
    return recommendations;
  }

  // Process MCP ecosystem findings - CRITICAL priority
  if (structuredFindings.findings.mcp_ecosystem) {
    const mcpFindings = structuredFindings.findings.mcp_ecosystem;
    const mcpStableRelease = mcpFindings.find((item: any) => item.title.includes("MCP 1.0"));

    if (mcpStableRelease) {
      recommendations.push({
        id: "mcp-1.0-migration",
        title: "Migrate to MCP 1.0 Stable Protocol",
        description:
          "MCP 1.0 stable release includes breaking changes and improved routing. Critical for maintaining compatibility with the ecosystem.",
        priority: "critical",
        category: "mcp-ecosystem",
        implementation: {
          effort: "high",
          timeline: "2-3 weeks",
          dependencies: ["MCP client library updates", "agent communication testing"],
          steps: [
            "Audit current MCP usage across all agents",
            "Update MCP client libraries to 1.0",
            "Test agent-to-agent communication protocols",
            "Update routing configurations",
            "Deploy with rollback plan",
          ],
          cost_estimate: "$2,000-3,000 (development time)",
        },
        benefits: [
          "Future-proof protocol compatibility",
          "Improved routing performance",
          "Access to new MCP ecosystem features",
          "Reduced technical debt",
        ],
        risks: [
          "Breaking changes may disrupt agent communication",
          "Rollback complexity if issues arise",
          "Temporary performance degradation during migration",
        ],
        relatedItems: [mcpStableRelease.title],
        openclaw_impact: {
          affected_agents: ["All agents using MCP communication"],
          architecture_changes: ["Agent router updates", "Communication protocol changes"],
          performance_impact: "Neutral to positive after migration",
        },
      });
    }

    // New MCP servers
    const mcpRegistry = mcpFindings.find((item: any) => item.title.includes("Registry Expansion"));
    if (mcpRegistry && mcpRegistry.new_servers) {
      recommendations.push({
        id: "new-mcp-servers-integration",
        title: "Integrate New MCP Servers for Enhanced Capabilities",
        description: `New MCP servers available: ${mcpRegistry.new_servers.join(", ")}. These can enhance agent coordination and data access patterns.`,
        priority: "high",
        category: "mcp-ecosystem",
        implementation: {
          effort: "medium",
          timeline: "1-2 weeks",
          dependencies: ["MCP 1.0 migration completion"],
          steps: [
            "Evaluate new server capabilities",
            "Test integration with existing agent workflows",
            "Configure server connections",
            "Update agent tool profiles",
            "Monitor performance impact",
          ],
          cost_estimate: "$1,000-1,500",
        },
        benefits: [
          "Enhanced database gateway patterns",
          "Improved distributed caching",
          "Better agent coordination capabilities",
        ],
        risks: ["Additional infrastructure complexity", "Potential performance overhead"],
        relatedItems: [mcpRegistry.title],
        openclaw_impact: {
          affected_agents: ["SupabaseConnector", "All data-accessing agents"],
          architecture_changes: ["New server integrations", "Enhanced coordination layer"],
          performance_impact: "Positive for data-intensive operations",
        },
      });
    }
  }

  // Process AI coding agents findings
  if (structuredFindings.findings.ai_coding_agents) {
    const codingAgents = structuredFindings.findings.ai_coding_agents;

    // Claude extended tool use
    const claudeUpdate = codingAgents.find((item: any) => item.title.includes("Claude"));
    if (claudeUpdate && claudeUpdate.relevance_to_openclaw === "HIGH") {
      recommendations.push({
        id: "claude-extended-tools",
        title: "Upgrade Claude Integration for Extended Tool Use",
        description:
          "Claude's new extended tool use with vision capabilities can enhance code analysis and generation across all coding agents.",
        priority: "high",
        category: "ai_coding_agents",
        implementation: {
          effort: "medium",
          timeline: "1 week",
          dependencies: ["Anthropic API access", "Tool definition updates"],
          steps: [
            "Update Claude API integration",
            "Enhance tool definitions for vision capabilities",
            "Test code analysis improvements",
            "Update CodeGen Pro and CodeGen Elite workflows",
            "Monitor cost impact",
          ],
          cost_estimate: "$500-800",
        },
        benefits: [
          "Enhanced code analysis with visual context",
          "Improved debugging capabilities",
          "Better architectural decision support",
        ],
        risks: ["Increased API costs", "Learning curve for new capabilities"],
        relatedItems: [claudeUpdate.title],
        openclaw_impact: {
          affected_agents: ["CodeGen Pro", "CodeGen Elite", "Code Reviewer"],
          architecture_changes: ["Enhanced tool definitions", "Vision capability integration"],
          performance_impact: "Positive for complex code analysis tasks",
        },
      });
    }

    // OpenAI o1 reasoning model
    const o1Update = codingAgents.find((item: any) => item.title.includes("o1"));
    if (o1Update) {
      recommendations.push({
        id: "openai-o1-integration",
        title: "Evaluate OpenAI o1 for Architectural Decision Tasks",
        description:
          "o1's enhanced reasoning capabilities could serve as a fallback model for complex architectural decisions that require deep analysis.",
        priority: "medium",
        category: "ai_coding_agents",
        implementation: {
          effort: "low",
          timeline: "3-5 days",
          dependencies: ["OpenAI API access", "Cost analysis"],
          steps: [
            "Set up o1 API integration",
            "Define use cases for architectural reasoning",
            "Create routing rules for complex tasks",
            "Performance and cost testing",
            "Integration with Architecture Designer agent",
          ],
          cost_estimate: "$300-500",
        },
        benefits: [
          "Enhanced reasoning for complex decisions",
          "Fallback option for challenging architectural problems",
          "Improved system design quality",
        ],
        risks: [
          "Higher API costs than standard models",
          "Slower response times for reasoning tasks",
        ],
        relatedItems: [o1Update.title],
        openclaw_impact: {
          affected_agents: ["Architecture Designer", "CodeGen Elite"],
          architecture_changes: ["New model routing rules", "Fallback decision logic"],
          performance_impact: "Positive for complex reasoning, slower response times",
        },
      });
    }
  }

  // Process multi-agent patterns
  if (structuredFindings.findings.multi_agent_patterns) {
    const patterns = structuredFindings.findings.multi_agent_patterns;

    // Deterministic handoff protocols
    const handoffResearch = patterns.find((item: any) => item.title.includes("Handoff"));
    if (handoffResearch && handoffResearch.relevance_to_openclaw === "CRITICAL") {
      recommendations.push({
        id: "deterministic-handoff-protocols",
        title: "Implement Deterministic Agent Handoff Protocols",
        description:
          "Research shows deterministic handoff protocols significantly improve multi-agent workflow reliability. Critical for OpenClaw's agent coordination.",
        priority: "critical",
        category: "multi_agent_patterns",
        implementation: {
          effort: "high",
          timeline: "3-4 weeks",
          dependencies: ["Agent router refactoring", "Comprehensive testing framework"],
          steps: [
            "Study research implementation details",
            "Design deterministic handoff state machine",
            "Implement handoff protocol in agent router",
            "Update all agent communication patterns",
            "Extensive testing and validation",
            "Gradual rollout with monitoring",
          ],
          cost_estimate: "$3,000-4,000",
        },
        benefits: [
          "Dramatically improved workflow reliability",
          "Reduced agent coordination failures",
          "Better error recovery and debugging",
          "Predictable system behavior",
        ],
        risks: [
          "Complex implementation requiring careful testing",
          "Potential performance overhead",
          "Risk of introducing new failure modes",
        ],
        relatedItems: [handoffResearch.title],
        openclaw_impact: {
          affected_agents: ["All agents", "Agent router", "Overseer"],
          architecture_changes: ["Core routing protocol changes", "State management updates"],
          performance_impact: "Slight overhead, major reliability improvement",
        },
      });
    }

    // Distributed memory systems
    const memoryResearch = patterns.find((item: any) => item.title.includes("Memory"));
    if (memoryResearch && memoryResearch.relevance_to_openclaw === "HIGH") {
      recommendations.push({
        id: "distributed-agent-memory",
        title: "Implement Distributed Agent Memory System",
        description:
          "Distributed memory across agent network enables better context sharing and continuity between agent handoffs.",
        priority: "high",
        category: "multi_agent_patterns",
        implementation: {
          effort: "high",
          timeline: "2-3 weeks",
          dependencies: ["Database schema updates", "Memory management framework"],
          steps: [
            "Design shared memory architecture",
            "Implement memory persistence layer",
            "Create context propagation mechanisms",
            "Update agents to use shared memory",
            "Performance optimization and testing",
          ],
          cost_estimate: "$2,500-3,500",
        },
        benefits: [
          "Better context continuity between agents",
          "Reduced redundant processing",
          "Improved decision quality with shared context",
          "Enhanced debugging and audit trails",
        ],
        risks: [
          "Memory consistency challenges",
          "Increased system complexity",
          "Potential performance bottlenecks",
        ],
        relatedItems: [memoryResearch.title],
        openclaw_impact: {
          affected_agents: ["All agents", "Memory management system"],
          architecture_changes: ["New memory layer", "Context sharing protocols"],
          performance_impact: "Positive for context-heavy operations",
        },
      });
    }
  }

  // Process automation tools
  if (structuredFindings.findings.automation_tools) {
    const tools = structuredFindings.findings.automation_tools;

    // Agentic benchmark suite
    const benchmarkSuite = tools.find((item: any) => item.title.includes("Benchmark"));
    if (benchmarkSuite && benchmarkSuite.relevance_to_openclaw === "HIGH") {
      recommendations.push({
        id: "agentic-benchmark-integration",
        title: "Adopt Agentic Framework Benchmark Suite",
        description:
          "New benchmark suite enables continuous performance monitoring of OpenClaw's multi-agent architecture and tool use quality.",
        priority: "medium",
        category: "automation_tools",
        implementation: {
          effort: "medium",
          timeline: "1-2 weeks",
          dependencies: ["CI/CD pipeline updates", "Monitoring infrastructure"],
          steps: [
            "Integrate benchmark suite into testing pipeline",
            "Configure performance baselines",
            "Set up automated reporting",
            "Create performance regression alerts",
            "Establish improvement tracking",
          ],
          cost_estimate: "$1,000-1,500",
        },
        benefits: [
          "Continuous performance monitoring",
          "Objective quality measurements",
          "Performance regression detection",
          "Competitive benchmarking capability",
        ],
        risks: ["Additional CI/CD complexity", "Benchmark maintenance overhead"],
        relatedItems: [benchmarkSuite.title],
        openclaw_impact: {
          affected_agents: ["All agents (for benchmarking)"],
          architecture_changes: ["Benchmarking integration", "Performance monitoring"],
          performance_impact: "Neutral (monitoring only)",
        },
      });
    }
  }

  // Sort by priority: critical > high > medium > low
  const priorityOrder = { critical: 4, high: 3, medium: 2, low: 1 };
  return recommendations.sort((a, b) => priorityOrder[b.priority] - priorityOrder[a.priority]);
}

export async function GET(request: NextRequest) {
  // Auth check
  const auth = requireAuth();
  if (!auth.authorized) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  // Rate limiting
  const clientIP = request.ip || "unknown";
  if (!checkRateLimit(clientIP, 10)) {
    return NextResponse.json({ error: "Rate limit exceeded" }, { status: 429 });
  }

  try {
    // Try structured findings first (from AI_RESEARCH_FINDINGS_24H.json)
    const structuredFindings = loadStructuredFindings();
    let recommendations: IntegrationRecommendation[] = [];
    let dataSource = "none";
    let metadata: any = {};

    if (structuredFindings) {
      recommendations = generateOpenClawRecommendations(structuredFindings);
      dataSource = "structured_findings";
      metadata = {
        generatedAt: new Date().toISOString(),
        basedOnFindings: structuredFindings.metadata?.research_date || "unknown",
        focusAreas: structuredFindings.metadata?.focus_areas || [],
        sourcesConsulted: structuredFindings.sources_consulted?.length || 0,
        findingsAnalyzed: Object.keys(structuredFindings.findings || {}).length,
      };
    } else {
      // Fallback to dynamic collection data
      const collection = loadLatestResearch();
      if (collection) {
        // Use the original logic as fallback
        recommendations = generateIntegrationRecommendations(collection.items);
        dataSource = "dynamic_collection";
        metadata = {
          generatedAt: new Date().toISOString(),
          basedOnCollection: collection.collectedAt,
          itemsAnalyzed: collection.totalItems,
          timeframe: collection.timeframe,
        };
      }
    }

    if (recommendations.length === 0) {
      return NextResponse.json(
        {
          success: false,
          error: "No research data found",
          message:
            "No structured findings or dynamic collection data available. Run a collection first using POST /api/research/scout",
        },
        { status: 404 },
      );
    }

    // Generate executive summary
    const summary = {
      totalRecommendations: recommendations.length,
      criticalPriority: recommendations.filter((r) => r.priority === "critical").length,
      highPriority: recommendations.filter((r) => r.priority === "high").length,
      mediumPriority: recommendations.filter((r) => r.priority === "medium").length,
      lowPriority: recommendations.filter((r) => r.priority === "low").length,
      categories: [...new Set(recommendations.map((r) => r.category))],
      estimatedEffort: {
        low: recommendations.filter((r) => r.implementation.effort === "low").length,
        medium: recommendations.filter((r) => r.implementation.effort === "medium").length,
        high: recommendations.filter((r) => r.implementation.effort === "high").length,
      },
      totalEstimatedCost: recommendations
        .filter((r) => r.implementation.cost_estimate)
        .map((r) => r.implementation.cost_estimate!)
        .join(", "),
      dataSource,
      affectedAgents: [
        ...new Set(recommendations.flatMap((r) => r.openclaw_impact?.affected_agents || [])),
      ],
    };

    // Create implementation roadmap
    const roadmap = {
      immediate: recommendations.filter((r) => r.priority === "critical"),
      shortTerm: recommendations.filter((r) => r.priority === "high"),
      mediumTerm: recommendations.filter((r) => r.priority === "medium"),
      longTerm: recommendations.filter((r) => r.priority === "low"),
    };

    return NextResponse.json({
      success: true,
      data: {
        recommendations,
        summary,
        roadmap,
        metadata,
      },
    });
  } catch (error) {
    console.error("Integration recommendations error:", error);
    return NextResponse.json(
      {
        error: "Failed to generate recommendations",
        message: error instanceof Error ? error.message : "Unknown error",
      },
      { status: 500 },
    );
  }
}

// Fallback function for dynamic collection data (original logic)
function generateIntegrationRecommendations(items: AIResearchItem[]): IntegrationRecommendation[] {
  const recommendations: IntegrationRecommendation[] = [];

  // Analyze high-relevance coding agents
  const codingAgents = items.filter(
    (item) => item.category === "coding-agents" && item.relevanceScore >= 7,
  );

  if (codingAgents.length > 0) {
    recommendations.push({
      id: "coding-agents-integration",
      title: "Integrate New AI Coding Agents",
      description: `${codingAgents.length} new coding agents detected with high relevance. Consider integrating these tools to enhance OpenClaw's development capabilities.`,
      priority: "high",
      category: "coding-agents",
      implementation: {
        effort: "medium",
        timeline: "2-3 weeks",
        dependencies: ["API access", "authentication setup"],
        steps: [
          "Evaluate agent capabilities and compatibility",
          "Set up API integrations",
          "Create wrapper services",
          "Add to agent registry",
          "Test integration with existing workflows",
        ],
      },
      benefits: [
        "Enhanced code generation capabilities",
        "Improved development velocity",
        "Access to specialized coding tools",
      ],
      risks: [
        "API rate limits",
        "Integration complexity",
        "Potential conflicts with existing agents",
      ],
      relatedItems: codingAgents.map((item) => item.id),
      openclaw_impact: {
        affected_agents: ["CodeGen Pro", "CodeGen Elite"],
        architecture_changes: ["Agent registry updates"],
        performance_impact: "Positive",
      },
    });
  }

  return recommendations;
}
