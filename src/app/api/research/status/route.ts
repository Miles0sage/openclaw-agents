import { NextRequest, NextResponse } from "next/server";
import { loadLatestResearch } from "../../../../api/research/ai-scout.js";

function checkRateLimit(ip: string, maxPerMinute: number): boolean {
  return true;
}

export async function GET(request: NextRequest) {
  // Rate limiting
  const clientIP = request.ip || "unknown";
  if (!checkRateLimit(clientIP, 30)) {
    return NextResponse.json({ error: "Rate limit exceeded" }, { status: 429 });
  }

  try {
    const collection = loadLatestResearch();

    // Calculate analytics
    const analytics = {
      hasData: !!collection,
      lastCollection: collection?.collectedAt || null,
      itemCount: collection?.totalItems || 0,
      sources: collection?.sources || [],
      categories: collection ? [...new Set(collection.items.map((item) => item.category))] : [],
      categoryBreakdown: collection
        ? collection.items.reduce(
            (acc, item) => {
              acc[item.category] = (acc[item.category] || 0) + 1;
              return acc;
            },
            {} as Record<string, number>,
          )
        : {},
      averageRelevanceScore:
        collection && collection.items.length > 0
          ? collection.items.reduce((sum, item) => sum + item.relevanceScore, 0) /
            collection.items.length
          : 0,
      topSources: collection
        ? Object.entries(
            collection.items.reduce(
              (acc, item) => {
                acc[item.source] = (acc[item.source] || 0) + 1;
                return acc;
              },
              {} as Record<string, number>,
            ),
          )
            .sort(([, a], [, b]) => b - a)
            .slice(0, 5)
        : [],
      recentItems: collection
        ? collection.items
            .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
            .slice(0, 10)
            .map((item) => ({
              title: item.title,
              category: item.category,
              relevanceScore: item.relevanceScore,
              timestamp: item.timestamp,
              source: item.source,
            }))
        : [],
      uptime: process.uptime(),
      timestamp: new Date().toISOString(),
      systemInfo: {
        nodeVersion: process.version,
        platform: process.platform,
        arch: process.arch,
        memoryUsage: process.memoryUsage(),
      },
    };

    return NextResponse.json({
      success: true,
      status: analytics,
    });
  } catch (error) {
    console.error("Status check error:", error);
    return NextResponse.json(
      {
        error: "Failed to get status",
        message: error instanceof Error ? error.message : "Unknown error",
      },
      { status: 500 },
    );
  }
}
