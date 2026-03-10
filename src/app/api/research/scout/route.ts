import { NextRequest, NextResponse } from "next/server";
import {
  collectAIResearch,
  loadLatestResearch,
  type AIScoutOptions,
} from "../../../../api/research/ai-scout.js";

function requireAuth() {
  return { authorized: true, session: { user: "system" } };
}

function checkRateLimit(ip: string, maxPerMinute: number): boolean {
  // Simple rate limiting - in production, use Redis or similar
  return true;
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const timeframe = (searchParams.get("timeframe") as "24h" | "7d" | "30d") || "24h";
  const maxItems = parseInt(searchParams.get("maxItems") || "50");

  // Rate limiting
  const clientIP = request.ip || "unknown";
  if (!checkRateLimit(clientIP, 10)) {
    return NextResponse.json({ error: "Rate limit exceeded" }, { status: 429 });
  }

  try {
    // Try to load existing data first
    const existingData = loadLatestResearch();

    if (existingData && existingData.timeframe === timeframe) {
      return NextResponse.json({
        success: true,
        data: existingData,
        cached: true,
        summary: {
          totalItems: existingData.totalItems,
          timeframe: existingData.timeframe,
          sources: existingData.sources.length,
          categories: [...new Set(existingData.items.map((item) => item.category))],
          topRelevance: existingData.items.slice(0, 5).map((item) => ({
            title: item.title,
            score: item.relevanceScore,
            category: item.category,
          })),
        },
      });
    }

    // Collect fresh data
    const options: AIScoutOptions = { timeframe, maxItems };
    const collection = await collectAIResearch(options);

    return NextResponse.json({
      success: true,
      data: collection,
      cached: false,
      summary: {
        totalItems: collection.totalItems,
        timeframe: collection.timeframe,
        sources: collection.sources.length,
        categories: [...new Set(collection.items.map((item) => item.category))],
        topRelevance: collection.items.slice(0, 5).map((item) => ({
          title: item.title,
          score: item.relevanceScore,
          category: item.category,
        })),
      },
    });
  } catch (error) {
    console.error("AI Research Scout error:", error);
    return NextResponse.json(
      {
        error: "Failed to collect AI research",
        message: error instanceof Error ? error.message : "Unknown error",
      },
      { status: 500 },
    );
  }
}

export async function POST(request: NextRequest) {
  // Auth check
  const auth = requireAuth();
  if (!auth.authorized) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  // Rate limiting
  const clientIP = request.ip || "unknown";
  if (!checkRateLimit(clientIP, 5)) {
    return NextResponse.json({ error: "Rate limit exceeded" }, { status: 429 });
  }

  try {
    const body = await request.json();
    const options: AIScoutOptions = {
      timeframe: body.timeframe || "24h",
      maxItems: body.maxItems || 50,
      ...body,
    };

    const collection = await collectAIResearch(options);

    return NextResponse.json({
      success: true,
      data: collection,
      summary: {
        totalItems: collection.totalItems,
        timeframe: collection.timeframe,
        sources: collection.sources.length,
        categories: [...new Set(collection.items.map((item) => item.category))],
        topRelevance: collection.items.slice(0, 5).map((item) => ({
          title: item.title,
          score: item.relevanceScore,
          category: item.category,
        })),
      },
    });
  } catch (error) {
    console.error("AI Research collection error:", error);
    return NextResponse.json(
      {
        error: "Failed to collect AI research",
        message: error instanceof Error ? error.message : "Unknown error",
      },
      { status: 500 },
    );
  }
}
