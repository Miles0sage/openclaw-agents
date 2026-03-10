/**
 * Hook Executor Utility
 *
 * Executes PostToolUse hooks after file edits and captures results.
 * Supports quality gates: auto-testing, linting, validation.
 *
 * Exit codes:
 * - 0: Success
 * - 1: Warning (tools ran but issues found)
 * - 2: Failure (block operation, requires fix)
 */

import { spawn } from "child_process";
import * as fs from "fs";
import * as path from "path";
import { Readable } from "stream";

/**
 * Result from hook execution
 */
export interface HookResult {
  success: boolean;
  exitCode: number;
  stdout: string;
  stderr: string;
  blockedOperation: boolean;
  duration: number;
  timestamp: string;
}

/**
 * Hook execution request
 */
export interface HookRequest {
  hookName: string;
  projectPath: string;
  changedFiles: string[];
  hookConfig: {
    test_command?: string;
    coverage_command?: string;
    lint_command?: string;
    prettier_command?: string;
    validation_script?: string;
    block_exit_code?: number;
    timeout?: number;
  };
}

/**
 * Hook Executor - Runs quality gate hooks with timeout and error handling
 */
export class HookExecutor {
  private logDir: string;

  constructor(logDir: string = "/tmp/hook-logs") {
    this.logDir = logDir;
    this.ensureLogDir();
  }

  /**
   * Ensure log directory exists
   */
  private ensureLogDir(): void {
    if (!fs.existsSync(this.logDir)) {
      fs.mkdirSync(this.logDir, { recursive: true });
    }
  }

  /**
   * Execute a hook command with timeout and capture output
   */
  async executeCommand(
    command: string,
    args: string[],
    cwd: string,
    timeout: number = 30000, // 30 seconds default
  ): Promise<{ stdout: string; stderr: string; exitCode: number }> {
    return new Promise((resolve, reject) => {
      let stdout = "";
      let stderr = "";
      let timedOut = false;

      // Spawn child process
      const child = spawn(command, args, {
        cwd,
        stdio: ["pipe", "pipe", "pipe"],
        timeout,
      });

      // Capture stdout
      if (child.stdout) {
        child.stdout.on("data", (data: Buffer) => {
          stdout += data.toString();
        });
      }

      // Capture stderr
      if (child.stderr) {
        child.stderr.on("data", (data: Buffer) => {
          stderr += data.toString();
        });
      }

      // Handle completion
      child.on("close", (code: number) => {
        if (timedOut) {
          reject(new Error(`Command timed out after ${timeout}ms: ${command} ${args.join(" ")}`));
        } else {
          resolve({ stdout, stderr, exitCode: code || 0 });
        }
      });

      // Handle timeout
      child.on("error", (err: Error) => {
        reject(err);
      });

      // Set timeout to kill process
      const timeoutHandle = setTimeout(() => {
        timedOut = true;
        child.kill("SIGKILL");
      }, timeout);

      // Clear timeout on completion
      child.on("exit", () => {
        clearTimeout(timeoutHandle);
      });
    });
  }

  /**
   * Execute PostToolUse hook - Runs quality gates after file edit
   */
  async executePostToolUseHook(request: HookRequest): Promise<HookResult> {
    const startTime = Date.now();
    const timestamp = new Date().toISOString();

    try {
      const config = request.hookConfig;
      const timeout = config.timeout || 60000; // 60 second default
      const blockExitCode = config.block_exit_code || 2;

      let finalExitCode = 0;
      let allStdout = "";
      let allStderr = "";

      // 1. Run tests (if configured)
      if (config.test_command) {
        const [testCmd, ...testArgs] = config.test_command.split(" ");
        try {
          const result = await this.executeCommand(testCmd, testArgs, request.projectPath, timeout);
          allStdout += `\n=== TEST OUTPUT ===\n${result.stdout}`;
          allStderr += result.stderr;
          finalExitCode = Math.max(finalExitCode, result.exitCode);

          if (result.exitCode !== 0) {
            console.error(`❌ Tests failed: ${request.projectPath}`);
          } else {
            console.log(`✅ Tests passed: ${request.projectPath}`);
          }
        } catch (err) {
          const errMsg = err instanceof Error ? err.message : String(err);
          allStderr += `\nTest error: ${errMsg}`;
          finalExitCode = blockExitCode;
        }
      }

      // 2. Run coverage check (if configured)
      if (config.coverage_command) {
        const [covCmd, ...covArgs] = config.coverage_command.split(" ");
        try {
          const result = await this.executeCommand(covCmd, covArgs, request.projectPath, timeout);
          allStdout += `\n=== COVERAGE OUTPUT ===\n${result.stdout}`;
          allStderr += result.stderr;
          finalExitCode = Math.max(finalExitCode, result.exitCode);

          if (result.exitCode !== 0) {
            console.error(`❌ Coverage check failed: ${request.projectPath}`);
          } else {
            console.log(`✅ Coverage check passed: ${request.projectPath}`);
          }
        } catch (err) {
          const errMsg = err instanceof Error ? err.message : String(err);
          allStderr += `\nCoverage error: ${errMsg}`;
        }
      }

      // 3. Run linting (if configured)
      if (config.lint_command) {
        const [lintCmd, ...lintArgs] = config.lint_command.split(" ");
        try {
          const result = await this.executeCommand(lintCmd, lintArgs, request.projectPath, timeout);
          allStdout += `\n=== LINT OUTPUT ===\n${result.stdout}`;
          allStderr += result.stderr;
          finalExitCode = Math.max(finalExitCode, result.exitCode);

          if (result.exitCode !== 0) {
            console.warn(`⚠️  Linting issues: ${request.projectPath}`);
          } else {
            console.log(`✅ Linting passed: ${request.projectPath}`);
          }
        } catch (err) {
          const errMsg = err instanceof Error ? err.message : String(err);
          allStderr += `\nLint error: ${errMsg}`;
        }
      }

      // 4. Run prettier check (if configured)
      if (config.prettier_command) {
        const [prettierCmd, ...prettierArgs] = config.prettier_command.split(" ");
        try {
          const result = await this.executeCommand(
            prettierCmd,
            prettierArgs,
            request.projectPath,
            timeout,
          );
          allStdout += `\n=== PRETTIER OUTPUT ===\n${result.stdout}`;
          allStderr += result.stderr;

          if (result.exitCode !== 0) {
            console.warn(`⚠️  Formatting issues: ${request.projectPath}`);
            // Don't block on prettier (exit code 1 for check failures)
          } else {
            console.log(`✅ Code formatting check passed: ${request.projectPath}`);
          }
        } catch (err) {
          const errMsg = err instanceof Error ? err.message : String(err);
          allStderr += `\nPrettier error: ${errMsg}`;
        }
      }

      // 5. Run validation script (if configured)
      if (config.validation_script) {
        const [valCmd, ...valArgs] = config.validation_script.split(" ");
        try {
          const result = await this.executeCommand(valCmd, valArgs, request.projectPath, timeout);
          allStdout += `\n=== VALIDATION OUTPUT ===\n${result.stdout}`;
          allStderr += result.stderr;
          finalExitCode = Math.max(finalExitCode, result.exitCode);

          if (result.exitCode !== 0) {
            console.error(`❌ Validation failed: ${request.projectPath}`);
          } else {
            console.log(`✅ Validation passed: ${request.projectPath}`);
          }
        } catch (err) {
          const errMsg = err instanceof Error ? err.message : String(err);
          allStderr += `\nValidation error: ${errMsg}`;
          finalExitCode = blockExitCode;
        }
      }

      const duration = Date.now() - startTime;
      const result: HookResult = {
        success: finalExitCode === 0,
        exitCode: finalExitCode,
        stdout: allStdout,
        stderr: allStderr,
        blockedOperation: finalExitCode === blockExitCode,
        duration,
        timestamp,
      };

      // Save result to log
      this.saveHookLog(request.hookName, result);

      return result;
    } catch (err) {
      const duration = Date.now() - startTime;
      const errMsg = err instanceof Error ? err.message : String(err);
      const result: HookResult = {
        success: false,
        exitCode: 2,
        stdout: "",
        stderr: errMsg,
        blockedOperation: true,
        duration,
        timestamp,
      };

      this.saveHookLog(request.hookName, result);
      return result;
    }
  }

  /**
   * Save hook execution result to log file
   */
  private saveHookLog(hookName: string, result: HookResult): void {
    try {
      const logFile = path.join(this.logDir, `${hookName}-${Date.now()}.json`);
      fs.writeFileSync(logFile, JSON.stringify(result, null, 2));
    } catch (err) {
      console.error(`Failed to save hook log: ${err}`);
    }
  }

  /**
   * Get hook execution history (last N executions)
   */
  getHookHistory(hookName: string, limit: number = 10): HookResult[] {
    try {
      const files = fs.readdirSync(this.logDir);
      const hookLogs = files
        .filter((f) => f.startsWith(hookName))
        .sort()
        .reverse()
        .slice(0, limit);

      return hookLogs.map((file) => {
        const content = fs.readFileSync(path.join(this.logDir, file), "utf-8");
        return JSON.parse(content) as HookResult;
      });
    } catch (err) {
      console.error(`Failed to read hook history: ${err}`);
      return [];
    }
  }

  /**
   * Filter changed files by pattern
   */
  static filterFilesByPattern(files: string[], patterns: string[]): string[] {
    if (!patterns || patterns.length === 0) {
      return files;
    }

    const isMatch = (file: string, pattern: string): boolean => {
      // Convert glob pattern to regex
      const regex = new RegExp(`^${pattern.replace(/\*/g, ".*").replace(/\?/g, ".")}$`);
      return regex.test(file);
    };

    return files.filter((file) => patterns.some((pattern) => isMatch(file, pattern)));
  }

  /**
   * Format hook result for display
   */
  static formatResult(result: HookResult, verbose: boolean = false): string {
    const status = result.success ? "✅ PASS" : "❌ FAIL";
    const blocked = result.blockedOperation ? " [BLOCKED]" : "";

    let output = `${status}${blocked} (${result.duration}ms)\n`;

    if (verbose) {
      if (result.stdout) {
        output += `\nSTDOUT:\n${result.stdout}\n`;
      }
      if (result.stderr) {
        output += `\nSTDERR:\n${result.stderr}\n`;
      }
    } else {
      // Show last 500 chars of output
      const combinedOutput = result.stdout + result.stderr;
      if (combinedOutput.length > 500) {
        output += `...\n${combinedOutput.slice(-500)}`;
      } else if (combinedOutput) {
        output += combinedOutput;
      }
    }

    return output;
  }
}

/**
 * Helper function for integration with agent context
 * Injects hook result into agent state if failure
 */
export function injectHookResultToContext(
  hookResult: HookResult,
  context: Record<string, unknown>,
): Record<string, unknown> {
  if (!hookResult.success) {
    return {
      ...context,
      hookFailure: {
        blocked: hookResult.blockedOperation,
        exitCode: hookResult.exitCode,
        error: hookResult.stderr,
        output: hookResult.stdout,
        duration: hookResult.duration,
        action: "Fix issues and run tests again before committing",
      },
    };
  }

  return context;
}

/**
 * Example usage
 */
export async function exampleUsage(): Promise<void> {
  const executor = new HookExecutor();

  const request: HookRequest = {
    hookName: "pythest-post-edit",
    projectPath: "/root/Mathcad-Scripts",
    changedFiles: ["prestressed/beam_design.py", "tests/test_beam_design.py"],
    hookConfig: {
      test_command: "python -m pytest -v --tb=short",
      coverage_command: "python -m pytest --cov=prestressed --cov-report=term-missing",
      block_exit_code: 2,
      timeout: 60000,
    },
  };

  const result = await executor.executePostToolUseHook(request);
  console.log("Hook Result:", HookExecutor.formatResult(result, false));
  console.log("Exit Code:", result.exitCode);
  console.log("Operation Blocked:", result.blockedOperation);
}

// Export for use as CLI tool
if (require.main === module) {
  exampleUsage().catch(console.error);
}
