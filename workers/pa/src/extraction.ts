/**
 * Fact Extraction Module — DeepSeek V3
 *
 * Extracts personal facts from user messages and stores them in memory.
 * Designed to be called fire-and-forget (via waitUntil) so it never
 * blocks the chat response.
 *
 * Cost: ~$0.0001 per extraction call.
 */

import { addMemory, searchMemories, updateMemory, initializeMemoryTables } from "./memory";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ExtractedFact {
  text: string;
  category: "preference" | "habit" | "fact" | "relationship" | "goal";
}

interface ExtractionResult {
  facts: ExtractedFact[];
  raw?: string;
}

// ---------------------------------------------------------------------------
// Extraction Prompt
// ---------------------------------------------------------------------------

const EXTRACTION_PROMPT = `You are a Personal Information Organizer. Your job is to extract important personal facts from the USER's message ONLY (ignore the assistant's message).

Extract facts that would be useful for a personal assistant to remember about this person.

Categories:
1. preference — Food likes/dislikes, activities, products, style preferences
2. habit — Recurring behaviors, routines, schedules
3. fact — Name, age, location, job, static personal details
4. relationship — People they mention, family, friends, colleagues
5. goal — Plans, aspirations, intentions, upcoming events

Rules:
- Only extract CLEAR, SPECIFIC facts (not vague statements)
- Do NOT extract greetings, questions, or commands to the assistant
- Do NOT extract facts about the assistant or AI
- Keep each fact as a short, standalone sentence
- If no facts are found, return an empty array

Return JSON ONLY (no markdown, no explanation):
{"facts": [{"text": "fact text here", "category": "category_name"}]}

Examples:
User: "I have soccer every Thursday at 9:20pm"
→ {"facts": [{"text": "Has soccer every Thursday at 9:20pm", "category": "habit"}]}

User: "My name is Miles and I'm building an AI company"
→ {"facts": [{"text": "Name is Miles", "category": "fact"}, {"text": "Building an AI company", "category": "goal"}]}

User: "What's the weather?"
→ {"facts": []}`;

// ---------------------------------------------------------------------------
// Core Functions
// ---------------------------------------------------------------------------

/**
 * Extract facts from a user message using DeepSeek V3.
 * Returns parsed facts or empty array on failure.
 */
export async function extractFacts(
  apiKey: string,
  userMessage: string,
): Promise<ExtractionResult> {
  // Skip extraction for very short messages or obvious commands
  if (userMessage.length < 10 || isCommandOnly(userMessage)) {
    return { facts: [] };
  }

  try {
    const response = await fetch("https://api.deepseek.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: "deepseek-chat",
        messages: [
          { role: "system", content: EXTRACTION_PROMPT },
          { role: "user", content: userMessage },
        ],
        temperature: 0.1,
        max_tokens: 512,
        response_format: { type: "json_object" },
      }),
    });

    if (!response.ok) {
      console.error(`Extraction API error: ${response.status}`);
      return { facts: [] };
    }

    const data = (await response.json()) as {
      choices?: Array<{ message?: { content?: string } }>;
    };

    const raw = data.choices?.[0]?.message?.content || "";
    const parsed = parseExtractionResponse(raw);
    return { facts: parsed, raw };
  } catch (err) {
    console.error("Fact extraction failed:", err);
    return { facts: [] };
  }
}

/**
 * Parse the LLM's JSON response, handling markdown code blocks.
 */
function parseExtractionResponse(raw: string): ExtractedFact[] {
  if (!raw.trim()) return [];

  // Strip markdown code blocks if present
  let cleaned = raw.trim();
  cleaned = cleaned.replace(/^```(?:json)?\s*\n?/i, "").replace(/\n?```\s*$/i, "");

  try {
    const parsed = JSON.parse(cleaned);
    if (!parsed.facts || !Array.isArray(parsed.facts)) return [];

    const validCategories = ["preference", "habit", "fact", "relationship", "goal"];
    return parsed.facts
      .filter(
        (f: { text?: string; category?: string }) =>
          f.text &&
          typeof f.text === "string" &&
          f.text.length > 3 &&
          validCategories.includes(f.category || "fact"),
      )
      .map((f: { text: string; category?: string }) => ({
        text: f.text.trim(),
        category: (f.category || "fact") as ExtractedFact["category"],
      }));
  } catch {
    console.error("Failed to parse extraction JSON:", cleaned.slice(0, 200));
    return [];
  }
}

/**
 * Check if a message is just a command (no personal info to extract).
 */
function isCommandOnly(msg: string): boolean {
  const lower = msg.toLowerCase().trim();
  const commandPatterns = [
    /^\/\w+/, // slash commands
    /^(hi|hello|hey|yo|sup|thanks|thank you|ok|okay|yes|no|yep|nope|bye|gm|gn)[\s!.?]*$/i,
    /^what('s| is) the (weather|time|date|price)/i,
    /^(show|get|check|list|tell me) /i,
    /^how (much|many|long|far)/i,
  ];
  return commandPatterns.some((p) => p.test(lower));
}

// ---------------------------------------------------------------------------
// Memory Integration
// ---------------------------------------------------------------------------

/**
 * Extract facts from a message and store them in the D1 memory database.
 * This is the main entry point — call via waitUntil() for fire-and-forget.
 *
 * Flow:
 * 1. Extract facts from user message via DeepSeek
 * 2. For each fact, check if similar memory exists
 * 3. If no match → ADD new memory
 * 4. If match exists → skip (dedup via hash handles exact matches)
 */
export async function extractAndStore(
  db: D1Database,
  apiKey: string,
  userId: string,
  userMessage: string,
): Promise<{ stored: number; skipped: number; facts: string[] }> {
  // Ensure tables exist before writing
  await initializeMemoryTables(db);

  const result = await extractFacts(apiKey, userMessage);

  if (result.facts.length === 0) {
    return { stored: 0, skipped: 0, facts: [] };
  }

  let stored = 0;
  let skipped = 0;
  const factTexts: string[] = [];

  for (const fact of result.facts) {
    try {
      // Check for existing similar memories (simple keyword search)
      const keywords = fact.text
        .split(/\s+/)
        .filter((w) => w.length > 3)
        .slice(0, 3)
        .join(" ");

      let isDuplicate = false;

      if (keywords.length > 0) {
        const existing = await searchMemories(db, {
          query: keywords,
          user_id: userId,
          category: fact.category,
          limit: 3,
        });

        // Check if any existing memory is semantically similar enough
        for (const mem of existing) {
          if (isSimilarEnough(fact.text, mem.data)) {
            isDuplicate = true;
            break;
          }
        }
      }

      if (isDuplicate) {
        skipped++;
        continue;
      }

      // Store the new fact
      const addResult = await addMemory(db, {
        data: fact.text,
        user_id: userId,
        category: fact.category,
      });

      if (addResult.created) {
        stored++;
        factTexts.push(fact.text);
      } else {
        skipped++; // hash dedup caught it
      }
    } catch (err) {
      console.error(`Failed to store fact "${fact.text}":`, err);
      skipped++;
    }
  }

  if (stored > 0) {
    console.log(`Memory: stored ${stored} facts for user ${userId}:`, factTexts);
  }

  return { stored, skipped, facts: factTexts };
}

/**
 * Simple similarity check using word overlap.
 * Returns true if the two strings share 60%+ of their significant words.
 */
function isSimilarEnough(a: string, b: string): boolean {
  const wordsA = new Set(
    a
      .toLowerCase()
      .split(/\s+/)
      .filter((w) => w.length > 3),
  );
  const wordsB = new Set(
    b
      .toLowerCase()
      .split(/\s+/)
      .filter((w) => w.length > 3),
  );

  if (wordsA.size === 0 || wordsB.size === 0) return false;

  let overlap = 0;
  for (const w of wordsA) {
    if (wordsB.has(w)) overlap++;
  }

  const similarity = overlap / Math.min(wordsA.size, wordsB.size);
  return similarity >= 0.6;
}

// ---------------------------------------------------------------------------
// Context Injection
// ---------------------------------------------------------------------------

/**
 * Retrieve relevant memories for a user message and format them as
 * context to inject into the system prompt.
 *
 * Returns empty string if no relevant memories found.
 */
export async function getMemoryContext(
  db: D1Database,
  userId: string,
  userMessage: string,
  limit: number = 5,
): Promise<string> {
  // Ensure tables exist before reading
  await initializeMemoryTables(db);

  // Extract keywords from the user message for search
  const keywords = userMessage
    .split(/\s+/)
    .filter((w) => w.length > 3)
    .slice(0, 5);

  if (keywords.length === 0) return "";

  try {
    // Search for each keyword and collect unique results
    const allMemories = new Map<string, { data: string; category: string }>();

    // Search with the full message keywords
    const results = await searchMemories(db, {
      query: keywords.join(" "),
      user_id: userId,
      limit,
    });

    for (const mem of results) {
      allMemories.set(mem.id, { data: mem.data, category: mem.category });
    }

    // If not enough results, try individual keywords
    if (allMemories.size < limit) {
      for (const kw of keywords.slice(0, 3)) {
        if (allMemories.size >= limit) break;
        const kwResults = await searchMemories(db, {
          query: kw,
          user_id: userId,
          limit: 2,
        });
        for (const mem of kwResults) {
          if (!allMemories.has(mem.id)) {
            allMemories.set(mem.id, { data: mem.data, category: mem.category });
          }
        }
      }
    }

    if (allMemories.size === 0) return "";

    // Format as context block
    const lines = Array.from(allMemories.values())
      .slice(0, limit)
      .map((m) => `- [${m.category}] ${m.data}`);

    return `\n\nTHINGS I REMEMBER ABOUT MILES:\n${lines.join("\n")}\nUse these memories naturally in your response when relevant. Don't explicitly say "I remember" unless it adds value.`;
  } catch (err) {
    console.error("Memory context retrieval failed:", err);
    return "";
  }
}
