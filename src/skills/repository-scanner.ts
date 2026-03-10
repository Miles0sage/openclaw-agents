/**
 * Repository Scanner Skill for OpenClaw
 * Enables agents to autonomously clone, read, and analyze GitHub repositories
 *
 * Usage: Agent calls this skill with repo URL → generates project summary
 */

import { exec } from "child_process";
import * as fs from "fs";
import * as path from "path";
import { promisify } from "util";

const execAsync = promisify(exec);
const readFileAsync = promisify(fs.readFile);

interface RepositoryAnalysis {
  name: string;
  url: string;
  status: "analyzed" | "error";
  summary: {
    description: string;
    techStack: string[];
    currentPhase: string;
    lastCommit: string;
    recentChanges: string[];
    nextSteps: string[];
  };
  error?: string;
}

/**
 * Clone repository to temp directory
 */
async function cloneRepository(repoUrl: string): Promise<string> {
  const repoName = repoUrl.split("/").pop()?.replace(".git", "") || "repo";
  const tempDir = `/tmp/openclaw-scan-${Date.now()}`;

  try {
    await execAsync(`git clone --depth 1 ${repoUrl} ${tempDir}`);
    return tempDir;
  } catch (error) {
    throw new Error(`Failed to clone ${repoUrl}: ${error}`);
  }
}

/**
 * Read package.json to detect tech stack
 */
async function detectTechStack(repoPath: string): Promise<string[]> {
  const packageJsonPath = path.join(repoPath, "package.json");

  if (!fs.existsSync(packageJsonPath)) {
    return ["Unknown - no package.json found"];
  }

  try {
    const content = await readFileAsync(packageJsonPath, "utf-8");
    const pkg = JSON.parse(content);

    const techStack = new Set<string>();

    // Detect from dependencies
    Object.keys(pkg.dependencies || {}).forEach((dep) => {
      if (dep.includes("react")) techStack.add("React");
      if (dep.includes("next")) techStack.add("Next.js");
      if (dep.includes("vue")) techStack.add("Vue");
      if (dep.includes("angular")) techStack.add("Angular");
      if (dep.includes("express")) techStack.add("Express");
      if (dep.includes("fastapi")) techStack.add("FastAPI");
      if (dep.includes("supabase")) techStack.add("Supabase");
      if (dep.includes("stripe")) techStack.add("Stripe");
      if (dep.includes("tailwind")) techStack.add("Tailwind CSS");
      if (dep.includes("typescript")) techStack.add("TypeScript");
    });

    return Array.from(techStack).length > 0 ? Array.from(techStack) : ["Node.js/JavaScript"];
  } catch (error) {
    return ["Tech stack detection failed"];
  }
}

/**
 * Get recent git commits
 */
async function getRecentCommits(repoPath: string): Promise<string[]> {
  try {
    const { stdout } = await execAsync(`cd ${repoPath} && git log --oneline -10`);
    return stdout.split("\n").filter((line) => line.trim());
  } catch (error) {
    return ["Failed to retrieve commits"];
  }
}

/**
 * Read README.md for project description
 */
async function getProjectDescription(repoPath: string): Promise<string> {
  const readmePath = path.join(repoPath, "README.md");

  if (!fs.existsSync(readmePath)) {
    return "No README found - analyzing from commits and code structure";
  }

  try {
    const content = await readFileAsync(readmePath, "utf-8");
    // Extract first paragraph
    const lines = content.split("\n");
    const firstParagraph = lines.slice(0, 10).join(" ");
    return firstParagraph.substring(0, 200);
  } catch (error) {
    return "Failed to read README";
  }
}

/**
 * Main skill: Analyze repository
 */
export async function analyzeRepository(
  repoUrl: string,
  options?: { generateSummary?: boolean },
): Promise<RepositoryAnalysis> {
  const repoName = repoUrl.split("/").pop()?.replace(".git", "") || "unknown";

  try {
    console.log(`[RepositoryScanner] Analyzing ${repoName}...`);

    // Clone repo
    const repoPath = await cloneRepository(repoUrl);
    console.log(`[RepositoryScanner] Cloned to ${repoPath}`);

    // Gather information in parallel
    const [description, techStack, commits] = await Promise.all([
      getProjectDescription(repoPath),
      detectTechStack(repoPath),
      getRecentCommits(repoPath),
    ]);

    // Cleanup
    await execAsync(`rm -rf ${repoPath}`);

    // Determine phase from commits
    const allCommits = commits.join(" ").toLowerCase();
    let phase = "Unknown";
    if (allCommits.includes("live") || allCommits.includes("deployed")) phase = "Production";
    else if (allCommits.includes("phase")) phase = "In Development";
    else if (allCommits.includes("refactor")) phase = "Maintenance";

    return {
      name: repoName,
      url: repoUrl,
      status: "analyzed",
      summary: {
        description,
        techStack,
        currentPhase: phase,
        lastCommit: commits[0] || "No commits found",
        recentChanges: commits.slice(0, 5),
        nextSteps: [
          "Deploy latest changes",
          "Run full test suite",
          "Update documentation",
          "Security audit",
        ],
      },
    };
  } catch (error) {
    return {
      name: repoName,
      url: repoUrl,
      status: "error",
      summary: {
        description: "Analysis failed",
        techStack: [],
        currentPhase: "Unknown",
        lastCommit: "N/A",
        recentChanges: [],
        nextSteps: [],
      },
      error: String(error),
    };
  }
}

/**
 * Batch analyze multiple repositories
 */
export async function analyzeRepositories(repoUrls: string[]): Promise<RepositoryAnalysis[]> {
  console.log(`[RepositoryScanner] Starting batch analysis of ${repoUrls.length} repos...`);

  const results = await Promise.all(
    repoUrls.map((url) =>
      analyzeRepository(url).catch((err) => ({
        name: url,
        url: url,
        status: "error" as const,
        summary: {
          description: "Batch analysis failed",
          techStack: [],
          currentPhase: "Unknown",
          lastCommit: "N/A",
          recentChanges: [],
          nextSteps: [],
        },
        error: String(err),
      })),
    ),
  );

  return results;
}

/**
 * Generate markdown summary from analysis
 */
export function generateMarkdownSummary(analysis: RepositoryAnalysis): string {
  if (analysis.status === "error") {
    return `# ${analysis.name}\n\n**Error:** ${analysis.error}\n`;
  }

  return `
# ${analysis.name}

## Overview
${analysis.summary.description}

## Tech Stack
- ${analysis.summary.techStack.join("\n- ")}

## Current Phase
${analysis.summary.currentPhase}

## Latest Activity
\`\`\`
${analysis.summary.lastCommit}
\`\`\`

## Recent Changes
${analysis.summary.recentChanges.map((c) => `- ${c}`).join("\n")}

## Recommended Next Steps
${analysis.summary.nextSteps.map((s) => `- [ ] ${s}`).join("\n")}

---
*Analysis generated by OpenClaw Repository Scanner*
`.trim();
}

export default {
  analyzeRepository,
  analyzeRepositories,
  generateMarkdownSummary,
};
