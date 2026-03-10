/**
 * Course Maker Module — AI-powered document-to-course generator
 *
 * Flow: Document (PDF URL / text / web URL) → Concept extraction → Lessons → Quizzes → Progress tracking
 * Storage: D1 for courses, lessons, quizzes, progress
 * LLM: DeepSeek V3 for generation (cheap, fast)
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Course {
  id: string;
  user_id: string;
  title: string;
  description: string;
  source_type: "text" | "url" | "pdf_url";
  source_ref: string;
  total_lessons: number;
  total_quizzes: number;
  created_at: string;
  updated_at: string;
}

export interface Lesson {
  id: string;
  course_id: string;
  order_num: number;
  title: string;
  concepts: string; // JSON array of concept strings
  explanation: string; // The lesson content
  key_takeaways: string; // JSON array
  created_at: string;
}

export interface Quiz {
  id: string;
  lesson_id: string;
  course_id: string;
  order_num: number;
  question: string;
  options: string; // JSON array of 4 options
  correct_index: number;
  explanation: string;
  difficulty: "easy" | "medium" | "hard";
}

export interface UserProgress {
  id: string;
  user_id: string;
  course_id: string;
  lesson_id: string;
  completed: boolean;
  quiz_score: number | null; // 0-100
  quiz_answers: string | null; // JSON
  started_at: string;
  completed_at: string | null;
}

export interface Flashcard {
  id: string;
  course_id: string;
  lesson_id: string;
  front: string; // question/term
  back: string; // answer/definition
  difficulty: "easy" | "medium" | "hard";
  next_review: string | null; // ISO date
  interval_days: number;
  ease_factor: number;
  review_count: number;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Database Setup
// ---------------------------------------------------------------------------

export async function initializeCourseTables(db: D1Database): Promise<void> {
  await db.prepare(`
    CREATE TABLE IF NOT EXISTS courses (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL,
      title TEXT NOT NULL,
      description TEXT DEFAULT '',
      source_type TEXT DEFAULT 'text',
      source_ref TEXT DEFAULT '',
      total_lessons INTEGER DEFAULT 0,
      total_quizzes INTEGER DEFAULT 0,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
  `).run();

  await db.prepare(`
    CREATE TABLE IF NOT EXISTS lessons (
      id TEXT PRIMARY KEY,
      course_id TEXT NOT NULL,
      order_num INTEGER NOT NULL,
      title TEXT NOT NULL,
      concepts TEXT DEFAULT '[]',
      explanation TEXT NOT NULL,
      key_takeaways TEXT DEFAULT '[]',
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (course_id) REFERENCES courses(id)
    )
  `).run();

  await db.prepare(`
    CREATE TABLE IF NOT EXISTS quizzes (
      id TEXT PRIMARY KEY,
      lesson_id TEXT NOT NULL,
      course_id TEXT NOT NULL,
      order_num INTEGER NOT NULL,
      question TEXT NOT NULL,
      options TEXT NOT NULL,
      correct_index INTEGER NOT NULL,
      explanation TEXT DEFAULT '',
      difficulty TEXT DEFAULT 'medium',
      FOREIGN KEY (lesson_id) REFERENCES lessons(id),
      FOREIGN KEY (course_id) REFERENCES courses(id)
    )
  `).run();

  await db.prepare(`
    CREATE TABLE IF NOT EXISTS user_progress (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL,
      course_id TEXT NOT NULL,
      lesson_id TEXT NOT NULL,
      completed BOOLEAN DEFAULT FALSE,
      quiz_score REAL,
      quiz_answers TEXT,
      started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      completed_at DATETIME,
      FOREIGN KEY (course_id) REFERENCES courses(id),
      FOREIGN KEY (lesson_id) REFERENCES lessons(id)
    )
  `).run();

  await db.prepare(`
    CREATE TABLE IF NOT EXISTS flashcards (
      id TEXT PRIMARY KEY,
      course_id TEXT NOT NULL,
      lesson_id TEXT NOT NULL,
      front TEXT NOT NULL,
      back TEXT NOT NULL,
      difficulty TEXT DEFAULT 'medium',
      next_review TEXT,
      interval_days INTEGER DEFAULT 1,
      ease_factor REAL DEFAULT 2.5,
      review_count INTEGER DEFAULT 0,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (course_id) REFERENCES courses(id),
      FOREIGN KEY (lesson_id) REFERENCES lessons(id)
    )
  `).run();

  await db.prepare(`CREATE INDEX IF NOT EXISTS idx_courses_user ON courses(user_id)`).run();
  await db.prepare(`CREATE INDEX IF NOT EXISTS idx_lessons_course ON lessons(course_id)`).run();
  await db.prepare(`CREATE INDEX IF NOT EXISTS idx_quizzes_lesson ON quizzes(lesson_id)`).run();
  await db.prepare(`CREATE INDEX IF NOT EXISTS idx_progress_user ON user_progress(user_id, course_id)`).run();
  await db.prepare(`CREATE INDEX IF NOT EXISTS idx_flashcards_course ON flashcards(course_id)`).run();
  await db.prepare(`CREATE INDEX IF NOT EXISTS idx_flashcards_lesson ON flashcards(lesson_id)`).run();
  await db.prepare(`CREATE INDEX IF NOT EXISTS idx_flashcards_review ON flashcards(next_review)`).run();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function genId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).substr(2, 8)}`;
}

async function callLLM(
  apiKey: string,
  systemPrompt: string,
  userPrompt: string,
  maxTokens: number = 4096,
  jsonMode: boolean = true,
): Promise<string> {
  const resp = await fetch("https://api.deepseek.com/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: "deepseek-chat",
      messages: [
        { role: "system", content: systemPrompt },
        { role: "user", content: userPrompt },
      ],
      temperature: 0.3,
      max_tokens: maxTokens,
      ...(jsonMode ? { response_format: { type: "json_object" } } : {}),
    }),
  });

  if (!resp.ok) {
    throw new Error(`DeepSeek API error: ${resp.status}`);
  }

  const data = (await resp.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };

  return data.choices?.[0]?.message?.content || "";
}

function parseJSON<T>(raw: string): T | null {
  let cleaned = raw.trim();
  cleaned = cleaned.replace(/^```(?:json)?\s*\n?/i, "").replace(/\n?```\s*$/i, "");
  try {
    return JSON.parse(cleaned) as T;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Content Fetching
// ---------------------------------------------------------------------------

async function fetchContent(sourceType: string, sourceRef: string): Promise<string> {
  if (sourceType === "text") {
    return sourceRef;
  }

  if (sourceType === "url" || sourceType === "pdf_url") {
    const resp = await fetch(sourceRef, {
      headers: { "User-Agent": "OpenClaw-CourseBot/1.0" },
      signal: AbortSignal.timeout(15000),
    });
    if (!resp.ok) throw new Error(`Failed to fetch URL: ${resp.status}`);

    const contentType = resp.headers.get("content-type") || "";

    if (contentType.includes("application/pdf")) {
      // For PDFs, we'll extract what we can from the raw text
      // Cloudflare Workers can't run pdfjs, so we'll pass the URL to the LLM
      // and let it work with what we can extract
      const text = await resp.text();
      // Extract readable text from PDF (basic approach)
      const readable = text
        .replace(/[^\x20-\x7E\n\r\t]/g, " ")
        .replace(/\s{3,}/g, "\n")
        .trim();
      return readable.slice(0, 30000) || `[PDF at ${sourceRef} — content could not be extracted directly. The LLM should work with the URL.]`;
    }

    // HTML — strip tags for text content
    const html = await resp.text();
    const textContent = html
      .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "")
      .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "")
      .replace(/<nav[^>]*>[\s\S]*?<\/nav>/gi, "")
      .replace(/<footer[^>]*>[\s\S]*?<\/footer>/gi, "")
      .replace(/<header[^>]*>[\s\S]*?<\/header>/gi, "")
      .replace(/<[^>]+>/g, " ")
      .replace(/&nbsp;/g, " ")
      .replace(/&amp;/g, "&")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&#\d+;/g, "")
      .replace(/\s{2,}/g, " ")
      .trim();

    return textContent.slice(0, 30000);
  }

  throw new Error(`Unknown source type: ${sourceType}`);
}

// ---------------------------------------------------------------------------
// Course Generation Pipeline
// ---------------------------------------------------------------------------

/**
 * Step 1: Extract concepts and generate course outline
 */
async function extractConcepts(
  apiKey: string,
  content: string,
  title?: string,
): Promise<{
  title: string;
  description: string;
  lessons: Array<{
    title: string;
    concepts: string[];
    order: number;
  }>;
}> {
  const prompt = `Analyze this content and create a structured course outline.

${title ? `Suggested title: "${title}"` : ""}

CONTENT:
${content.slice(0, 15000)}

Return JSON:
{
  "title": "Course title",
  "description": "1-2 sentence course description",
  "lessons": [
    {
      "title": "Lesson title",
      "concepts": ["concept1", "concept2", "concept3"],
      "order": 1
    }
  ]
}

Rules:
- Create 3-8 lessons depending on content complexity
- Each lesson should have 2-5 key concepts
- Order lessons from foundational to advanced (prerequisites first)
- Lesson titles should be clear and specific
- Keep course description concise`;

  const raw = await callLLM(apiKey, "You are an expert curriculum designer. Create well-structured course outlines from any content.", prompt);
  const parsed = parseJSON<{
    title: string;
    description: string;
    lessons: Array<{ title: string; concepts: string[]; order: number }>;
  }>(raw);

  if (!parsed || !parsed.lessons?.length) {
    throw new Error("Failed to extract course structure");
  }

  return parsed;
}

/**
 * Step 2: Generate lesson content for each lesson
 */
async function generateLesson(
  apiKey: string,
  content: string,
  lessonTitle: string,
  concepts: string[],
  courseTitle: string,
): Promise<{
  explanation: string;
  key_takeaways: string[];
}> {
  const prompt = `Create a lesson for the course "${courseTitle}".

Lesson: "${lessonTitle}"
Key concepts to cover: ${concepts.join(", ")}

SOURCE MATERIAL:
${content.slice(0, 10000)}

Return JSON:
{
  "explanation": "Full lesson text (500-1000 words). Use clear language, examples, and analogies. Break into sections with headers. Make it engaging and easy to understand.",
  "key_takeaways": ["takeaway 1", "takeaway 2", "takeaway 3"]
}

Rules:
- Write at a level that a motivated beginner can follow
- Include practical examples where possible
- Use analogies to explain complex ideas
- Each takeaway should be one sentence
- 3-5 key takeaways per lesson`;

  const raw = await callLLM(apiKey, "You are an expert teacher. Write clear, engaging lessons that build intuitive understanding.", prompt);
  const parsed = parseJSON<{ explanation: string; key_takeaways: string[] }>(raw);

  if (!parsed?.explanation) {
    throw new Error(`Failed to generate lesson: ${lessonTitle}`);
  }

  return parsed;
}

/**
 * Step 3: Generate flashcards for a lesson
 */
async function generateFlashcards(
  apiKey: string,
  lessonExplanation: string,
  lessonTitle: string,
  concepts: string[],
): Promise<Array<{
  front: string;
  back: string;
  difficulty: "easy" | "medium" | "hard";
}>> {
  const prompt = `Create flashcards for the lesson "${lessonTitle}".

LESSON CONTENT:
${lessonExplanation.slice(0, 6000)}

KEY CONCEPTS: ${concepts.join(", ")}

Return JSON:
{
  "flashcards": [
    {
      "front": "Question or term to be memorized",
      "back": "Answer or definition",
      "difficulty": "easy"
    }
  ]
}

Rules:
- Generate 5-8 flashcards per lesson
- Front should be concise (question or term)
- Back should be clear and complete (answer or definition)
- Mix of easy (2-3), medium (2-3), and hard (1-2) cards
- Test memorization and recall
- Each card should be self-contained and unambiguous`;

  const raw = await callLLM(apiKey, "You are a curriculum designer creating spaced-repetition flashcards. Make cards that test understanding and retention.", prompt);
  const parsed = parseJSON<{
    flashcards: Array<{
      front: string;
      back: string;
      difficulty: "easy" | "medium" | "hard";
    }>;
  }>(raw);

  if (!parsed?.flashcards?.length) {
    throw new Error(`Failed to generate flashcards for: ${lessonTitle}`);
  }

  return parsed.flashcards;
}

/**
 * Step 4: Generate quiz questions for a lesson
 */
async function generateQuiz(
  apiKey: string,
  lessonExplanation: string,
  lessonTitle: string,
  concepts: string[],
): Promise<Array<{
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
  difficulty: "easy" | "medium" | "hard";
}>> {
  const prompt = `Create quiz questions for the lesson "${lessonTitle}".

LESSON CONTENT:
${lessonExplanation.slice(0, 6000)}

KEY CONCEPTS: ${concepts.join(", ")}

Return JSON:
{
  "questions": [
    {
      "question": "Question text?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_index": 0,
      "explanation": "Why this answer is correct",
      "difficulty": "easy"
    }
  ]
}

Rules:
- Generate 3-5 questions per lesson
- Mix of easy (1), medium (2-3), and hard (1) questions
- Each question must have exactly 4 options
- correct_index is 0-based (0 = first option)
- Explanation should teach why the correct answer is right
- Test understanding, not memorization
- Wrong options should be plausible (not obviously wrong)`;

  const raw = await callLLM(apiKey, "You are a test designer. Create questions that test genuine understanding, not memorization.", prompt);
  const parsed = parseJSON<{
    questions: Array<{
      question: string;
      options: string[];
      correct_index: number;
      explanation: string;
      difficulty: "easy" | "medium" | "hard";
    }>;
  }>(raw);

  if (!parsed?.questions?.length) {
    throw new Error(`Failed to generate quiz for: ${lessonTitle}`);
  }

  return parsed.questions;
}

// ---------------------------------------------------------------------------
// Main Course Creation
// ---------------------------------------------------------------------------

/**
 * Create a complete course from content.
 * This is the main entry point.
 */
export async function createCourse(
  db: D1Database,
  apiKey: string,
  userId: string,
  sourceType: "text" | "url" | "pdf_url",
  sourceRef: string,
  suggestedTitle?: string,
): Promise<{
  course: Course;
  lessons: Lesson[];
  quizCount: number;
}> {
  await initializeCourseTables(db);

  // 1. Fetch content
  const content = await fetchContent(sourceType, sourceRef);
  if (content.length < 100) {
    throw new Error("Content too short to create a course (need at least 100 chars)");
  }

  // 2. Extract concepts and structure
  const outline = await extractConcepts(apiKey, content, suggestedTitle);

  // 3. Create course record
  const courseId = genId();
  const now = new Date().toISOString();
  const course: Course = {
    id: courseId,
    user_id: userId,
    title: outline.title,
    description: outline.description,
    source_type: sourceType,
    source_ref: sourceType === "text" ? sourceRef.slice(0, 500) : sourceRef,
    total_lessons: outline.lessons.length,
    total_quizzes: 0,
    created_at: now,
    updated_at: now,
  };

  await db.prepare(`
    INSERT INTO courses (id, user_id, title, description, source_type, source_ref, total_lessons, total_quizzes, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).bind(courseId, userId, course.title, course.description, course.source_type, course.source_ref, course.total_lessons, 0, now, now).run();

  // 4. Generate lessons and quizzes (sequentially to manage API calls)
  const lessons: Lesson[] = [];
  let totalQuizzes = 0;

  for (const lessonOutline of outline.lessons) {
    // Generate lesson content
    const lessonContent = await generateLesson(
      apiKey,
      content,
      lessonOutline.title,
      lessonOutline.concepts,
      outline.title,
    );

    const lessonId = genId();
    const lesson: Lesson = {
      id: lessonId,
      course_id: courseId,
      order_num: lessonOutline.order,
      title: lessonOutline.title,
      concepts: JSON.stringify(lessonOutline.concepts),
      explanation: lessonContent.explanation,
      key_takeaways: JSON.stringify(lessonContent.key_takeaways),
      created_at: now,
    };

    await db.prepare(`
      INSERT INTO lessons (id, course_id, order_num, title, concepts, explanation, key_takeaways, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(lessonId, courseId, lesson.order_num, lesson.title, lesson.concepts, lesson.explanation, lesson.key_takeaways, now).run();

    lessons.push(lesson);

    // Generate flashcards for this lesson
    const flashcardData = await generateFlashcards(
      apiKey,
      lessonContent.explanation,
      lessonOutline.title,
      lessonOutline.concepts,
    );

    for (const fc of flashcardData) {
      const flashcardId = genId();
      await db.prepare(`
        INSERT INTO flashcards (id, course_id, lesson_id, front, back, difficulty, interval_days, ease_factor, review_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind(flashcardId, courseId, lessonId, fc.front, fc.back, fc.difficulty, 1, 2.5, 0, now).run();
    }

    // Generate quiz for this lesson
    const quizQuestions = await generateQuiz(
      apiKey,
      lessonContent.explanation,
      lessonOutline.title,
      lessonOutline.concepts,
    );

    for (let qi = 0; qi < quizQuestions.length; qi++) {
      const q = quizQuestions[qi];
      const quizId = genId();
      await db.prepare(`
        INSERT INTO quizzes (id, lesson_id, course_id, order_num, question, options, correct_index, explanation, difficulty)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind(quizId, lessonId, courseId, qi + 1, q.question, JSON.stringify(q.options), q.correct_index, q.explanation, q.difficulty).run();
      totalQuizzes++;
    }
  }

  // Update course with quiz count
  await db.prepare(`UPDATE courses SET total_quizzes = ?, updated_at = ? WHERE id = ?`)
    .bind(totalQuizzes, now, courseId).run();
  course.total_quizzes = totalQuizzes;

  return { course, lessons, quizCount: totalQuizzes };
}

// ---------------------------------------------------------------------------
// Course Interaction (Learn Mode, Quiz Mode, Progress)
// ---------------------------------------------------------------------------

/**
 * List all courses for a user
 */
export async function listCourses(db: D1Database, userId: string): Promise<Course[]> {
  await initializeCourseTables(db);
  const result = await db.prepare(`SELECT * FROM courses WHERE user_id = ? ORDER BY created_at DESC`)
    .bind(userId).all<Course>();
  return result.results || [];
}

/**
 * Get a lesson with its quiz questions
 */
export async function getLesson(
  db: D1Database,
  lessonId: string,
): Promise<{ lesson: Lesson; quizzes: Quiz[] } | null> {
  const lesson = await db.prepare(`SELECT * FROM lessons WHERE id = ?`)
    .bind(lessonId).first<Lesson>();
  if (!lesson) return null;

  const quizzes = await db.prepare(`SELECT * FROM quizzes WHERE lesson_id = ? ORDER BY order_num`)
    .bind(lessonId).all<Quiz>();

  return { lesson, quizzes: quizzes.results || [] };
}

/**
 * Get all lessons for a course
 */
export async function getCourseLessons(
  db: D1Database,
  courseId: string,
): Promise<Lesson[]> {
  const result = await db.prepare(`SELECT * FROM lessons WHERE course_id = ? ORDER BY order_num`)
    .bind(courseId).all<Lesson>();
  return result.results || [];
}

/**
 * Get next lesson (first incomplete lesson for user)
 */
export async function getNextLesson(
  db: D1Database,
  userId: string,
  courseId: string,
): Promise<{ lesson: Lesson; quizzes: Quiz[]; lessonNumber: number; totalLessons: number } | null> {
  const allLessons = await getCourseLessons(db, courseId);
  if (allLessons.length === 0) return null;

  // Find completed lessons
  const progress = await db.prepare(
    `SELECT lesson_id FROM user_progress WHERE user_id = ? AND course_id = ? AND completed = TRUE`
  ).bind(userId, courseId).all<{ lesson_id: string }>();

  const completedIds = new Set((progress.results || []).map(p => p.lesson_id));
  const nextLesson = allLessons.find(l => !completedIds.has(l.id));

  if (!nextLesson) {
    // All done — return last lesson
    const last = allLessons[allLessons.length - 1];
    const data = await getLesson(db, last.id);
    return data ? { ...data, lessonNumber: allLessons.length, totalLessons: allLessons.length } : null;
  }

  const data = await getLesson(db, nextLesson.id);
  const lessonNumber = allLessons.indexOf(nextLesson) + 1;
  return data ? { ...data, lessonNumber, totalLessons: allLessons.length } : null;
}

/**
 * Submit quiz answers and track progress
 */
export async function submitQuiz(
  db: D1Database,
  userId: string,
  courseId: string,
  lessonId: string,
  answers: number[], // User's answer indices
): Promise<{
  score: number;
  total: number;
  percentage: number;
  passed: boolean;
  results: Array<{
    question: string;
    userAnswer: string;
    correctAnswer: string;
    correct: boolean;
    explanation: string;
  }>;
  nextLessonId: string | null;
}> {
  await initializeCourseTables(db);

  const quizzes = await db.prepare(`SELECT * FROM quizzes WHERE lesson_id = ? ORDER BY order_num`)
    .bind(lessonId).all<Quiz>();
  const questions = quizzes.results || [];

  let correct = 0;
  const results = questions.map((q, i) => {
    const options = JSON.parse(q.options) as string[];
    const userIdx = answers[i] ?? -1;
    const isCorrect = userIdx === q.correct_index;
    if (isCorrect) correct++;

    return {
      question: q.question,
      userAnswer: options[userIdx] || "(no answer)",
      correctAnswer: options[q.correct_index],
      correct: isCorrect,
      explanation: q.explanation,
    };
  });

  const percentage = questions.length > 0 ? Math.round((correct / questions.length) * 100) : 0;
  const passed = percentage >= 60;

  // Save progress
  const progressId = genId();
  const now = new Date().toISOString();
  await db.prepare(`
    INSERT INTO user_progress (id, user_id, course_id, lesson_id, completed, quiz_score, quiz_answers, started_at, completed_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET completed = ?, quiz_score = ?, quiz_answers = ?, completed_at = ?
  `).bind(
    progressId, userId, courseId, lessonId, passed, percentage, JSON.stringify(answers), now, passed ? now : null,
    passed, percentage, JSON.stringify(answers), passed ? now : null,
  ).run();

  // Find next lesson
  let nextLessonId: string | null = null;
  if (passed) {
    const allLessons = await getCourseLessons(db, courseId);
    const currentIdx = allLessons.findIndex(l => l.id === lessonId);
    if (currentIdx >= 0 && currentIdx < allLessons.length - 1) {
      nextLessonId = allLessons[currentIdx + 1].id;
    }
  }

  return {
    score: correct,
    total: questions.length,
    percentage,
    passed,
    results,
    nextLessonId,
  };
}

/**
 * Get course progress summary
 */
export async function getCourseProgress(
  db: D1Database,
  userId: string,
  courseId: string,
): Promise<{
  course: Course | null;
  completedLessons: number;
  totalLessons: number;
  averageScore: number;
  percentage: number;
  lessonDetails: Array<{
    lessonId: string;
    title: string;
    completed: boolean;
    score: number | null;
  }>;
}> {
  await initializeCourseTables(db);

  const course = await db.prepare(`SELECT * FROM courses WHERE id = ?`)
    .bind(courseId).first<Course>();
  if (!course) return { course: null, completedLessons: 0, totalLessons: 0, averageScore: 0, percentage: 0, lessonDetails: [] };

  const lessons = await getCourseLessons(db, courseId);
  const progress = await db.prepare(
    `SELECT * FROM user_progress WHERE user_id = ? AND course_id = ?`
  ).bind(userId, courseId).all<UserProgress>();

  const progressMap = new Map<string, UserProgress>();
  for (const p of (progress.results || [])) {
    progressMap.set(p.lesson_id, p);
  }

  let completedCount = 0;
  let totalScore = 0;
  let scoredCount = 0;

  const lessonDetails = lessons.map(l => {
    const p = progressMap.get(l.id);
    const completed = p?.completed || false;
    if (completed) completedCount++;
    if (p?.quiz_score != null) {
      totalScore += p.quiz_score;
      scoredCount++;
    }
    return {
      lessonId: l.id,
      title: l.title,
      completed,
      score: p?.quiz_score ?? null,
    };
  });

  return {
    course,
    completedLessons: completedCount,
    totalLessons: lessons.length,
    averageScore: scoredCount > 0 ? Math.round(totalScore / scoredCount) : 0,
    percentage: lessons.length > 0 ? Math.round((completedCount / lessons.length) * 100) : 0,
    lessonDetails,
  };
}

/**
 * Delete a course and all related data
 */
export async function deleteCourse(db: D1Database, courseId: string): Promise<void> {
  await db.prepare(`DELETE FROM user_progress WHERE course_id = ?`).bind(courseId).run();
  await db.prepare(`DELETE FROM quizzes WHERE course_id = ?`).bind(courseId).run();
  await db.prepare(`DELETE FROM flashcards WHERE course_id = ?`).bind(courseId).run();
  await db.prepare(`DELETE FROM lessons WHERE course_id = ?`).bind(courseId).run();
  await db.prepare(`DELETE FROM courses WHERE id = ?`).bind(courseId).run();
}

// ---------------------------------------------------------------------------
// Flashcard Spaced Repetition
// ---------------------------------------------------------------------------

/**
 * Get flashcards due for review.
 * Returns cards where next_review <= now OR next_review IS NULL.
 * Ordered by next_review ASC (soonest first).
 */
export async function getFlashcardsForReview(
  db: D1Database,
  courseId: string,
  limit: number = 10,
): Promise<Flashcard[]> {
  const now = new Date().toISOString();
  const result = await db.prepare(`
    SELECT * FROM flashcards
    WHERE course_id = ? AND (next_review IS NULL OR next_review <= ?)
    ORDER BY next_review ASC
    LIMIT ?
  `).bind(courseId, now, limit).all<Flashcard>();

  return result.results || [];
}

/**
 * Review a flashcard using the SM-2 spaced repetition algorithm.
 *
 * quality: 0-5
 *   0 = complete blackout, wrong with no attempt
 *   1 = blackout, correct response after hesitation
 *   2 = correct response after a bit of struggle
 *   3 = correct response with serious difficulty
 *   4 = correct response after some hesitation
 *   5 = perfect response
 *
 * SM-2 algorithm:
 * - If quality >= 3: interval_days = old_interval * ease_factor
 * - ease_factor = max(1.3, ease + 0.1 - (5-quality)*(0.08+(5-quality)*0.02))
 * - If quality < 3: interval_days = 1, ease_factor unchanged
 * - next_review = now + interval_days
 */
export async function reviewFlashcard(
  db: D1Database,
  flashcardId: string,
  quality: number,
): Promise<void> {
  // Clamp quality to 0-5
  const q = Math.max(0, Math.min(5, quality));

  // Fetch current card
  const card = await db.prepare(`SELECT * FROM flashcards WHERE id = ?`)
    .bind(flashcardId).first<Flashcard>();

  if (!card) {
    throw new Error(`Flashcard not found: ${flashcardId}`);
  }

  let newInterval = card.interval_days;
  let newEaseFactor = card.ease_factor;

  if (q >= 3) {
    // Correct response: increase interval
    newInterval = Math.max(1, Math.round(card.interval_days * card.ease_factor));
    newEaseFactor = Math.max(1.3, card.ease_factor + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02));
  } else {
    // Incorrect response: reset interval, keep ease
    newInterval = 1;
    newEaseFactor = card.ease_factor;
  }

  // Calculate next review date
  const nextReviewDate = new Date();
  nextReviewDate.setDate(nextReviewDate.getDate() + newInterval);
  const nextReviewISO = nextReviewDate.toISOString();

  // Update card
  await db.prepare(`
    UPDATE flashcards
    SET interval_days = ?, ease_factor = ?, next_review = ?, review_count = review_count + 1
    WHERE id = ?
  `).bind(newInterval, newEaseFactor, nextReviewISO, flashcardId).run();
}

/**
 * Get flashcard statistics for a course.
 */
export async function getFlashcardStats(
  db: D1Database,
  courseId: string,
): Promise<{
  total: number;
  mastered: number; // interval >= 21 days
  learning: number; // reviewed but interval < 21
  new: number; // never reviewed (review_count = 0)
}> {
  const allCards = await db.prepare(`SELECT * FROM flashcards WHERE course_id = ?`)
    .bind(courseId).all<Flashcard>();

  const cards = allCards.results || [];
  const total = cards.length;

  let mastered = 0;
  let learning = 0;
  let newCards = 0;

  for (const card of cards) {
    if (card.review_count === 0) {
      newCards++;
    } else if (card.interval_days >= 21) {
      mastered++;
    } else {
      learning++;
    }
  }

  return { total, mastered, learning, new: newCards };
}
