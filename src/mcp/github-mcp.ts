/**
 * GitHub MCP Client
 * Enables agents to interact with GitHub API for code commits, PRs, comments, branches
 * Uses GitHub REST API v3 with token-based authentication
 */

export interface GitHubIssue {
  number: number;
  title: string;
  body: string;
  state: "open" | "closed";
  user: {
    login: string;
  };
  created_at: string;
  updated_at: string;
}

export interface GitHubPR {
  number: number;
  title: string;
  body: string;
  state: "open" | "closed" | "merged";
  head: {
    ref: string;
    sha: string;
  };
  base: {
    ref: string;
  };
  html_url: string;
  created_at: string;
  updated_at: string;
}

export interface GitHubCommit {
  sha: string;
  message: string;
  author: {
    name: string;
    email: string;
    date: string;
  };
}

export interface GitHubBranch {
  name: string;
  commit: {
    sha: string;
    url: string;
  };
  protected: boolean;
}

export interface CommitResponse {
  commit: {
    message: string;
    author: {
      name: string;
      email: string;
      date: string;
    };
  };
  sha: string;
  html_url: string;
}

export interface FileContent {
  name: string;
  path: string;
  sha: string;
  size: number;
  type: "file" | "dir";
  content?: string;
  encoding?: string;
}

export class GitHubClient {
  private token: string;
  private baseUrl = "https://api.github.com";

  constructor(token?: string) {
    this.token = token || process.env.GITHUB_TOKEN || "";
    if (!this.token) {
      throw new Error("GITHUB_TOKEN environment variable not set");
    }
  }

  private async request<T>(method: string, endpoint: string, body?: unknown): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const headers: HeadersInit = {
      Accept: "application/vnd.github.v3+json",
      Authorization: `token ${this.token}`,
      "User-Agent": "OpenClaw-MCP",
      "Content-Type": "application/json",
    };

    const options: RequestInit = {
      method,
      headers,
    };

    if (body) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`GitHub API error ${response.status}: ${error}`);
    }

    const contentType = response.headers.get("content-type");
    if (contentType?.includes("application/json")) {
      return (await response.json()) as T;
    }

    return {} as T;
  }

  /**
   * Read issue details
   */
  async readIssue(owner: string, repo: string, issueNumber: number): Promise<GitHubIssue> {
    return this.request<GitHubIssue>("GET", `/repos/${owner}/${repo}/issues/${issueNumber}`);
  }

  /**
   * Create a new branch
   */
  async createBranch(
    owner: string,
    repo: string,
    baseBranch: string,
    newBranch: string,
  ): Promise<void> {
    // First get the SHA of the base branch
    const refResponse = await this.request<{ object: { sha: string } }>(
      "GET",
      `/repos/${owner}/${repo}/git/refs/heads/${baseBranch}`,
    );

    const baseSha = refResponse.object.sha;

    // Create new branch from base branch SHA
    await this.request("POST", `/repos/${owner}/${repo}/git/refs`, {
      ref: `refs/heads/${newBranch}`,
      sha: baseSha,
    });
  }

  /**
   * Commit a file to a branch
   * Returns the commit SHA
   */
  async commitFile(
    owner: string,
    repo: string,
    branch: string,
    filePath: string,
    content: string,
    message: string,
  ): Promise<string> {
    // Encode content to base64
    const encodedContent = Buffer.from(content).toString("base64");

    // Check if file exists
    let fileSha: string | undefined;
    try {
      const existingFile = await this.request<{ sha: string }>(
        "GET",
        `/repos/${owner}/${repo}/contents/${filePath}?ref=${branch}`,
      );
      fileSha = existingFile.sha;
    } catch {
      // File doesn't exist, that's fine
    }

    const response = await this.request<{ commit: { sha: string } }>(
      "PUT",
      `/repos/${owner}/${repo}/contents/${filePath}`,
      {
        message,
        content: encodedContent,
        branch,
        ...(fileSha && { sha: fileSha }),
      },
    );

    return response.commit.sha;
  }

  /**
   * Create a pull request
   */
  async createPullRequest(
    owner: string,
    repo: string,
    headBranch: string,
    baseBranch: string,
    title: string,
    body: string,
  ): Promise<GitHubPR> {
    return this.request<GitHubPR>("POST", `/repos/${owner}/${repo}/pulls`, {
      title,
      body,
      head: headBranch,
      base: baseBranch,
    });
  }

  /**
   * Merge a pull request
   */
  async mergePullRequest(owner: string, repo: string, prNumber: number): Promise<void> {
    await this.request("PUT", `/repos/${owner}/${repo}/pulls/${prNumber}/merge`, {
      commit_title: "Merge pull request",
      merge_method: "squash",
    });
  }

  /**
   * Add a comment to an issue or PR
   */
  async addComment(
    owner: string,
    repo: string,
    issueNumber: number,
    comment: string,
  ): Promise<void> {
    await this.request("POST", `/repos/${owner}/${repo}/issues/${issueNumber}/comments`, {
      body: comment,
    });
  }

  /**
   * List branches
   */
  async listBranches(owner: string, repo: string): Promise<GitHubBranch[]> {
    return this.request<GitHubBranch[]>("GET", `/repos/${owner}/${repo}/branches`);
  }

  /**
   * Get file content
   */
  async getFileContent(
    owner: string,
    repo: string,
    filePath: string,
    ref?: string,
  ): Promise<FileContent> {
    const query = ref ? `?ref=${ref}` : "";
    return this.request<FileContent>("GET", `/repos/${owner}/${repo}/contents/${filePath}${query}`);
  }

  /**
   * Decode file content (if returned from API as base64)
   */
  decodeFileContent(content: string): string {
    return Buffer.from(content, "base64").toString("utf-8");
  }

  /**
   * Get commit details
   */
  async getCommit(owner: string, repo: string, sha: string): Promise<CommitResponse> {
    return this.request<CommitResponse>("GET", `/repos/${owner}/${repo}/commits/${sha}`);
  }

  /**
   * Create a release
   */
  async createRelease(
    owner: string,
    repo: string,
    tagName: string,
    name: string,
    body: string,
    isDraft?: boolean,
    isPrerelease?: boolean,
  ): Promise<{ id: number; url: string; html_url: string }> {
    return this.request("POST", `/repos/${owner}/${repo}/releases`, {
      tag_name: tagName,
      name,
      body,
      draft: isDraft || false,
      prerelease: isPrerelease || false,
    });
  }

  /**
   * Delete a branch
   */
  async deleteBranch(owner: string, repo: string, branchName: string): Promise<void> {
    await this.request("DELETE", `/repos/${owner}/${repo}/git/refs/heads/${branchName}`);
  }

  /**
   * Compare two commits/branches
   */
  async compareCommits(
    owner: string,
    repo: string,
    base: string,
    head: string,
  ): Promise<{
    commits: CommitResponse[];
    files: Array<{ filename: string; additions: number; deletions: number }>;
  }> {
    return this.request("GET", `/repos/${owner}/${repo}/compare/${base}...${head}`);
  }
}
