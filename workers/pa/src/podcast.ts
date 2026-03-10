// Podcast generation: URL → summarize → script → audio
// Runs on Cloudflare Workers, no external packages

export interface PodcastRequest {
  url?: string;
  text?: string;
  title?: string;
  style?: "summary" | "deep_dive" | "quick_brief";
}

export interface PodcastResult {
  title: string;
  script: string;
  audio_base64?: string;
  duration_estimate: string;
  word_count: number;
}

/**
 * Fetch URL and extract main text content
 * Simple regex-based, no heavy libs. Limit to ~5000 chars.
 */
export async function fetchAndExtract(url: string): Promise<string> {
  try {
    const response = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const html = await response.text();

    // Strip script and style tags
    let text = html
      .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "")
      .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, "");

    // Remove HTML tags
    text = text.replace(/<[^>]+>/g, " ");

    // Decode HTML entities
    text = text
      .replace(/&nbsp;/g, " ")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&amp;/g, "&")
      .replace(/&#39;/g, "'");

    // Clean up whitespace
    text = text
      .replace(/\s+/g, " ")
      .trim();

    // Limit to 5000 chars
    return text.substring(0, 5000);
  } catch (error) {
    throw new Error(`Failed to fetch URL: ${error instanceof Error ? error.message : String(error)}`);
  }
}

/**
 * Generate podcast script from text using DeepSeek
 */
export async function generatePodcastScript(
  text: string,
  title: string,
  style: string,
  deepseekApiKey: string
): Promise<string> {
  const styleGuides: Record<string, string> = {
    summary: "~500 words for summary",
    deep_dive: "~1000 words for deep dive",
    quick_brief: "~200 words for quick brief",
  };

  const wordLimit = styleGuides[style] || styleGuides.summary;

  const systemPrompt = `You are a professional podcast scriptwriter. Transform content into engaging, conversational podcast scripts.
Guidelines:
- Use a friendly, engaging tone
- Start with a brief, catchy intro
- Cover key points in logical order
- End with a clear takeaway
- Keep it concise (${wordLimit})
- Write for audio — short sentences, natural pauses
- Add [PAUSE] markers where speakers should pause`;

  const userPrompt = `Title: "${title}"

Content:
${text}

Transform this into a conversational podcast script. Make it sound natural and engaging, as if two hosts are discussing this topic.`;

  try {
    const response = await fetch("https://api.deepseek.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${deepseekApiKey}`,
      },
      body: JSON.stringify({
        model: "deepseek-chat",
        messages: [
          {
            role: "system",
            content: systemPrompt,
          },
          {
            role: "user",
            content: userPrompt,
          },
        ],
        temperature: 0.7,
        max_tokens: 2000,
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`DeepSeek API error: ${response.status} - ${error}`);
    }

    const data = (await response.json()) as {
      choices: Array<{ message: { content: string } }>;
    };

    if (!data.choices || !data.choices[0]) {
      throw new Error("No response from DeepSeek");
    }

    return data.choices[0].message.content.trim();
  } catch (error) {
    throw new Error(
      `Failed to generate podcast script: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

/**
 * Convert text to speech using Google Cloud TTS REST API
 * Returns base64 audio or null on failure
 */
export async function textToSpeech(
  text: string,
  geminiApiKey: string
): Promise<string | null> {
  try {
    // Use the Google Cloud TTS endpoint directly
    // Note: Gemini API key may or may not work — handle gracefully
    const response = await fetch(
      `https://texttospeech.googleapis.com/v1/text:synthesize?key=${geminiApiKey}`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          input: {
            text: text,
          },
          voice: {
            languageCode: "en-US",
            name: "en-US-Neural2-D",
          },
          audioConfig: {
            audioEncoding: "OGG_OPUS",
          },
        }),
      }
    );

    if (!response.ok) {
      // Silently fail — TTS is optional
      console.warn(`TTS failed: ${response.status}`);
      return null;
    }

    const data = (await response.json()) as { audioContent?: string };

    if (!data.audioContent) {
      return null;
    }

    return data.audioContent;
  } catch (error) {
    // Gracefully handle TTS failure
    console.warn(
      `TTS error: ${error instanceof Error ? error.message : String(error)}`
    );
    return null;
  }
}

/**
 * Main entry point: create podcast from URL or text
 */
export async function createPodcast(
  request: PodcastRequest,
  deepseekApiKey: string,
  geminiApiKey?: string
): Promise<PodcastResult> {
  const style = request.style || "summary";

  // Fetch content
  let content: string;
  if (request.url) {
    content = await fetchAndExtract(request.url);
  } else if (request.text) {
    content = request.text.substring(0, 5000);
  } else {
    throw new Error("Either url or text must be provided");
  }

  // Extract title
  const title = request.title || request.url || "Podcast";

  // Generate script
  const script = await generatePodcastScript(
    content,
    title,
    style,
    deepseekApiKey
  );

  // Count words
  const wordCount = script.split(/\s+/).length;

  // Estimate duration
  const duration_estimate = `~${Math.ceil(wordCount / 150)} min`;

  // Try to generate audio (optional)
  let audio_base64: string | undefined;
  if (geminiApiKey) {
    audio_base64 = (await textToSpeech(script, geminiApiKey)) || undefined;
  }

  return {
    title,
    script,
    audio_base64,
    duration_estimate,
    word_count: wordCount,
  };
}

/**
 * Send audio as voice message to Telegram
 * Uses sendVoice API with multipart/form-data
 */
export async function sendTelegramVoice(
  botToken: string,
  chatId: string,
  audioBase64: string,
  caption: string
): Promise<boolean> {
  try {
    // Convert base64 to ArrayBuffer
    const binaryString = atob(audioBase64);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }

    // Build multipart form data
    const boundary = "----FormBoundary" + Date.now();
    let body = `--${boundary}\r\n`;
    body += `Content-Disposition: form-data; name="chat_id"\r\n\r\n`;
    body += `${chatId}\r\n`;
    body += `--${boundary}\r\n`;
    body += `Content-Disposition: form-data; name="voice"; filename="podcast.ogg"\r\n`;
    body += `Content-Type: audio/ogg\r\n\r\n`;

    // Convert body string to bytes, concatenate with binary audio, then rest of body
    const bodyPart1 = new TextEncoder().encode(body);
    const bodyPart2 = new TextEncoder().encode(
      `\r\n--${boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n${caption}\r\n--${boundary}--\r\n`
    );

    // Combine all parts
    const combined = new Uint8Array(
      bodyPart1.length + bytes.length + bodyPart2.length
    );
    combined.set(bodyPart1);
    combined.set(bytes, bodyPart1.length);
    combined.set(bodyPart2, bodyPart1.length + bytes.length);

    const response = await fetch(
      `https://api.telegram.org/bot${botToken}/sendVoice`,
      {
        method: "POST",
        headers: {
          "Content-Type": `multipart/form-data; boundary=${boundary}`,
        },
        body: combined,
      }
    );

    if (!response.ok) {
      console.warn(`Telegram sendVoice failed: ${response.status}`);
      return false;
    }

    return true;
  } catch (error) {
    console.warn(
      `Failed to send Telegram voice: ${error instanceof Error ? error.message : String(error)}`
    );
    return false;
  }
}

/**
 * Send podcast result to Telegram
 * If audio exists, send as voice message. Otherwise, send script as text.
 */
export async function sendTelegramAudioResult(
  botToken: string,
  chatId: string,
  result: PodcastResult
): Promise<void> {
  const caption = `📻 **${result.title}**\n\n⏱️ Duration: ${result.duration_estimate}\n📝 Words: ${result.word_count}`;

  if (result.audio_base64) {
    // Send as voice message
    const success = await sendTelegramVoice(
      botToken,
      chatId,
      result.audio_base64,
      caption
    );

    if (!success) {
      // Fallback: send script as text
      await sendTelegramText(botToken, chatId, caption, result.script);
    }
  } else {
    // Send script as text
    await sendTelegramText(botToken, chatId, caption, result.script);
  }
}

/**
 * Helper: send text message to Telegram
 */
async function sendTelegramText(
  botToken: string,
  chatId: string,
  caption: string,
  script: string
): Promise<void> {
  const text = `${caption}\n\n${script}`;

  try {
    await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        chat_id: chatId,
        text: text,
        parse_mode: "Markdown",
      }),
    });
  } catch (error) {
    console.warn(
      `Failed to send Telegram message: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}
