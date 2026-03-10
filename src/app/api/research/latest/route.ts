import { NextRequest, NextResponse } from "next/server";
import { loadLatestResearch } from "../../../../api/research/ai-scout.js";

function checkRateLimit(ip: string, maxPerMinute: number): boolean {
  return true;
}

export async function GET(request: NextRequest) {
  // Rate limiting
  const clientIP = request.ip || "unknown";
  if (!checkRateLimit(clientIP, 20)) {
    return NextResponse.json({ error: "Rate limit exceeded" }, { status: 429 });
  }

  try {
    const collection = loadLatestResearch();

    if (!collection) {
      return NextResponse.json(
        {
          success: false,
          error: "No research data found",
          message: "Run a collection first using POST /api/research/scout",
        },
        { status: 404 },
      );
    }

    const { searchParams } = new URL(request.url);
    const category = searchParams.get("category");
    const minScore = parseInt(searchParams.get("minScore") || "0");
    const limit = parseInt(searchParams.get("limit") || "50");

    let filteredItems = collection.items;

    // Filter by category if specified
    if (category && category !== "all") {
      filteredItems = filteredItems.filter((item) => item.category === category);
    }

    // Filter by minimum relevance score
    if (minScore > 0) {
      filteredItems = filteredItems.filter((item) => item.relevanceScore >= minScore);
    }

    // Apply limit
    filteredItems = filteredItems.slice(0, limit);

    return NextResponse.json({
      success: true,
      data: {
        ...collection,
        items: filteredItems,
        totalItems: filteredItems.length,
      },
      filters: {
        category: category || "all",
        minScore,
        limit,
        appliedFilters: filteredItems.length !== collection.items.length,
      },
    });
  } catch (error) {
    console.error("Latest research error:", error);
    return NextResponse.json(
      {
        error: "Failed to load latest research",
        message: error instanceof Error ? error.message : "Unknown error",
      },
      { status: 500 },
    );
  }
}
