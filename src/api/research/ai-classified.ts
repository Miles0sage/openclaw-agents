import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ClassifiedResearchItem {
  id: string;
  title: string;
  date: string;
  description: string;
  source: string;
  technical_impact_score: number;
  integration_urgency_score: number;
  rationale: {
    impact: string;
    urgency: string;
  };
  integration_recommendation: string;
  tags: string[];
  new_servers?: string[];
}

export interface ClassifiedResearchBucket {
  [key: string]: ClassifiedResearchItem[];
}

export interface PriorityItem {
  id: string;
  combined_score: number;
  action: string;
}

export interface ClassifiedResearchData {
  metadata: {
    classification_date: string;
    source_document: string;
    classification_criteria: {
      buckets: string[];
      scoring_system: {
        technical_impact: string;
        integration_urgency: string;
      };
    };
  };
  classified_findings: ClassifiedResearchBucket;
  deduplication_notes: {
    duplicates_found: number;
    cross_category_items: Array<{
      item: string;
      primary_category: string;
      secondary_relevance: string;
      note: string;
    }>;
  };
  priority_matrix: {
    critical_urgent: PriorityItem[];
    high_impact_urgent: PriorityItem[];
    high_impact_medium_urgency: PriorityItem[];
    medium_priority: PriorityItem[];
  };
  summary_statistics: {
    total_items_classified: number;
    items_per_bucket: Record<string, number>;
    average_scores: {
      technical_impact: number;
      integration_urgency: number;
      combined: number;
    };
    high_priority_items: number;
    critical_items: number;
  };
}

export interface ClassificationFilters {
  bucket?: string;
  min_impact_score?: number;
  min_urgency_score?: number;
  min_combined_score?: number;
  tags?: string[];
  priority_level?:
    | "critical_urgent"
    | "high_impact_urgent"
    | "high_impact_medium_urgency"
    | "medium_priority";
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DATA_DIR = ".";
const CLASSIFIED_FILENAME = "AI_RESEARCH_CLASSIFIED_20260304.json";

// ---------------------------------------------------------------------------
// Core Functions
// ---------------------------------------------------------------------------

export function loadClassifiedResearch(): ClassifiedResearchData | null {
  try {
    const filepath = join(DATA_DIR, CLASSIFIED_FILENAME);

    if (existsSync(filepath)) {
      const data = readFileSync(filepath, "utf-8");
      return JSON.parse(data) as ClassifiedResearchData;
    }

    return null;
  } catch (error) {
    console.warn("Failed to load classified research:", error);
    return null;
  }
}

export function filterClassifiedItems(
  data: ClassifiedResearchData,
  filters: ClassificationFilters,
): ClassifiedResearchData {
  const filteredData = { ...data };

  // Filter classified findings by bucket
  if (filters.bucket) {
    const bucketData = data.classified_findings[filters.bucket];
    if (bucketData) {
      filteredData.classified_findings = { [filters.bucket]: bucketData };
    } else {
      filteredData.classified_findings = {};
    }
  }

  // Apply score filters to all buckets
  if (
    filters.min_impact_score ||
    filters.min_urgency_score ||
    filters.min_combined_score ||
    filters.tags
  ) {
    const filteredBuckets: ClassifiedResearchBucket = {};

    for (const [bucketName, items] of Object.entries(filteredData.classified_findings)) {
      const filteredItems = items.filter((item) => {
        // Impact score filter
        if (filters.min_impact_score && item.technical_impact_score < filters.min_impact_score) {
          return false;
        }

        // Urgency score filter
        if (
          filters.min_urgency_score &&
          item.integration_urgency_score < filters.min_urgency_score
        ) {
          return false;
        }

        // Combined score filter
        if (filters.min_combined_score) {
          const combined = item.technical_impact_score + item.integration_urgency_score;
          if (combined < filters.min_combined_score) {
            return false;
          }
        }

        // Tags filter
        if (filters.tags && filters.tags.length > 0) {
          const hasMatchingTag = filters.tags.some((tag) =>
            item.tags.some((itemTag) => itemTag.toLowerCase().includes(tag.toLowerCase())),
          );
          if (!hasMatchingTag) {
            return false;
          }
        }

        return true;
      });

      if (filteredItems.length > 0) {
        filteredBuckets[bucketName] = filteredItems;
      }
    }

    filteredData.classified_findings = filteredBuckets;
  }

  // Filter priority matrix by level
  if (filters.priority_level) {
    const priorityData = data.priority_matrix[filters.priority_level];
    filteredData.priority_matrix = {
      critical_urgent: [],
      high_impact_urgent: [],
      high_impact_medium_urgency: [],
      medium_priority: [],
      [filters.priority_level]: priorityData,
    };
  }

  return filteredData;
}

export function getTopPriorityItems(
  data: ClassifiedResearchData,
  limit: number = 5,
): PriorityItem[] {
  const allPriorityItems: PriorityItem[] = [
    ...data.priority_matrix.critical_urgent,
    ...data.priority_matrix.high_impact_urgent,
    ...data.priority_matrix.high_impact_medium_urgency,
    ...data.priority_matrix.medium_priority,
  ];

  return allPriorityItems.sort((a, b) => b.combined_score - a.combined_score).slice(0, limit);
}

export function getItemsByBucket(
  data: ClassifiedResearchData,
  bucket: string,
): ClassifiedResearchItem[] {
  return data.classified_findings[bucket] || [];
}

export function getItemById(
  data: ClassifiedResearchData,
  id: string,
): ClassifiedResearchItem | null {
  for (const items of Object.values(data.classified_findings)) {
    const item = items.find((item) => item.id === id);
    if (item) return item;
  }
  return null;
}

export function getBucketSummary(data: ClassifiedResearchData): Record<
  string,
  {
    count: number;
    avg_impact: number;
    avg_urgency: number;
    avg_combined: number;
    top_item: string;
  }
> {
  const summary: Record<string, any> = {};

  for (const [bucketName, items] of Object.entries(data.classified_findings)) {
    if (items.length === 0) continue;

    const avgImpact =
      items.reduce((sum, item) => sum + item.technical_impact_score, 0) / items.length;
    const avgUrgency =
      items.reduce((sum, item) => sum + item.integration_urgency_score, 0) / items.length;
    const avgCombined = avgImpact + avgUrgency;

    const topItem = items.reduce((top, item) => {
      const itemCombined = item.technical_impact_score + item.integration_urgency_score;
      const topCombined = top.technical_impact_score + top.integration_urgency_score;
      return itemCombined > topCombined ? item : top;
    });

    summary[bucketName] = {
      count: items.length,
      avg_impact: Math.round(avgImpact * 10) / 10,
      avg_urgency: Math.round(avgUrgency * 10) / 10,
      avg_combined: Math.round(avgCombined * 10) / 10,
      top_item: topItem.title,
    };
  }

  return summary;
}

// ---------------------------------------------------------------------------
// Auth & Rate Limiting (Mock implementations)
// ---------------------------------------------------------------------------

export function requireAuth() {
  return { authorized: true, session: { user: "system" } };
}

export function checkRateLimit(ip: string, maxPerMinute: number): boolean {
  // Simple in-memory rate limiting for now
  return true;
}
