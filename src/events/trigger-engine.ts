/**
 * Event Trigger System
 * Enables autonomous reactions to workflow events (quality_gate_passed → deploy, cost_alert → notify, etc.)
 * Implements event-driven automation patterns for the OpenClaw agent platform
 */

import { EventEmitter } from "node:events";
import { logDebug, logError, logInfo } from "../logger.js";

/**
 * Represents a single trigger that listens for an event and executes actions
 */
export interface EventTrigger {
  /** Event type to listen for (e.g., "quality_gate_passed", "test_failed", "cost_alert") */
  eventType: string;

  /** Optional condition that must be true for trigger to fire */
  condition?: (data: any) => boolean;

  /** Actions to execute when trigger fires (executed sequentially) */
  actions: Array<(data: any) => Promise<void>>;

  /** Human-readable description of what this trigger does */
  description: string;

  /** Execution priority (high triggers execute before normal/low) */
  priority?: "high" | "normal" | "low";

  /** Optional ID for tracking and management */
  id?: string;
}

/**
 * TriggerEngine: Event dispatcher for autonomous workflow reactions
 * Manages event subscriptions and executes triggers based on event emissions
 */
export class TriggerEngine extends EventEmitter {
  private triggers: Map<string, EventTrigger[]> = new Map();
  private executingCount = 0;
  private maxConcurrentExecutions = 10;

  constructor() {
    super();
    this.setMaxListeners(100); // Allow many event listeners
  }

  /**
   * Register a trigger for an event type
   * Multiple triggers can be registered for the same event
   */
  registerTrigger(trigger: EventTrigger): void {
    // Validate trigger
    if (!trigger.eventType || trigger.eventType.trim() === "") {
      throw new Error("EventTrigger must have a non-empty eventType");
    }
    if (!trigger.actions || trigger.actions.length === 0) {
      throw new Error("EventTrigger must have at least one action");
    }

    // Assign ID if not provided
    if (!trigger.id) {
      trigger.id = `trigger-${trigger.eventType}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    }

    // Add to triggers map
    const existing = this.triggers.get(trigger.eventType) || [];
    existing.push(trigger);

    // Sort by priority (high first)
    existing.sort((a, b) => {
      const priorityOrder = { high: 0, normal: 1, low: 2 };
      const aPriority = priorityOrder[a.priority || "normal"];
      const bPriority = priorityOrder[b.priority || "normal"];
      return aPriority - bPriority;
    });

    this.triggers.set(trigger.eventType, existing);

    logDebug(`Registered trigger: ${trigger.id} for event "${trigger.eventType}"`);
  }

  /**
   * Unregister a trigger by ID
   */
  unregisterTrigger(triggerId: string): boolean {
    for (const [eventType, triggers] of this.triggers.entries()) {
      const index = triggers.findIndex((t) => t.id === triggerId);
      if (index !== -1) {
        triggers.splice(index, 1);
        if (triggers.length === 0) {
          this.triggers.delete(eventType);
        }
        logDebug(`Unregistered trigger: ${triggerId}`);
        return true;
      }
    }
    return false;
  }

  /**
   * Fire an event and execute all matching triggers
   * Non-blocking: triggers execute asynchronously
   */
  async emitEvent(eventType: string, data: any): Promise<void> {
    const triggers = this.triggers.get(eventType) || [];

    if (triggers.length === 0) {
      logDebug(`Event "${eventType}" fired but no triggers registered`);
      return;
    }

    logInfo(`Event triggered: "${eventType}" with ${triggers.length} listener(s)`);

    // Execute triggers without blocking
    this.executeTriggers(triggers, eventType, data).catch((err) => {
      logError(`Error executing triggers for event "${eventType}": ${String(err)}`);
    });

    // Emit the event on the EventEmitter for external listeners
    this.emit(eventType, data);
  }

  /**
   * Execute all triggers for an event (internal method)
   */
  private async executeTriggers(
    triggers: EventTrigger[],
    eventType: string,
    data: any,
  ): Promise<void> {
    // Wait if too many concurrent executions
    while (this.executingCount >= this.maxConcurrentExecutions) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }

    this.executingCount++;

    try {
      for (const trigger of triggers) {
        try {
          // Check condition (skip if it returns false)
          if (trigger.condition && !trigger.condition(data)) {
            logDebug(`Trigger ${trigger.id} condition not met, skipping`);
            continue;
          }

          logInfo(`Executing trigger: ${trigger.id} (${trigger.description})`);

          // Execute all actions sequentially for this trigger
          for (const action of trigger.actions) {
            try {
              await action(data);
            } catch (err) {
              logError(`Action failed in trigger ${trigger.id}: ${String(err)}`);
              // Don't crash; continue to next action
            }
          }

          logInfo(`Trigger ${trigger.id} completed successfully`);
        } catch (err) {
          logError(`Trigger ${trigger.id} failed: ${String(err)}`);
          // Don't crash; continue to next trigger
        }
      }
    } finally {
      this.executingCount--;
    }
  }

  /**
   * List all registered triggers
   */
  getTriggers(eventType?: string): EventTrigger[] {
    if (eventType) {
      return this.triggers.get(eventType) || [];
    }
    return Array.from(this.triggers.values()).flat();
  }

  /**
   * Get trigger count by event type
   */
  getTriggerCount(eventType?: string): number {
    if (eventType) {
      return (this.triggers.get(eventType) || []).length;
    }
    return this.getTriggers().length;
  }

  /**
   * Clear all triggers
   */
  clearAll(): void {
    const count = this.getTriggers().length;
    this.triggers.clear();
    logInfo(`Cleared ${count} trigger(s)`);
  }

  /**
   * Clear triggers for a specific event type
   */
  clearEvent(eventType: string): number {
    const triggers = this.triggers.get(eventType) || [];
    const count = triggers.length;
    this.triggers.delete(eventType);
    logInfo(`Cleared ${count} trigger(s) for event "${eventType}"`);
    return count;
  }

  /**
   * Get engine statistics
   */
  getStats(): {
    totalTriggers: number;
    triggersByEvent: Record<string, number>;
    executingCount: number;
  } {
    const stats: Record<string, number> = {};
    for (const [eventType, triggers] of this.triggers.entries()) {
      stats[eventType] = triggers.length;
    }

    return {
      totalTriggers: this.getTriggers().length,
      triggersByEvent: stats,
      executingCount: this.executingCount,
    };
  }
}

/**
 * Create and return a singleton TriggerEngine instance
 */
let engineInstance: TriggerEngine | null = null;

export function getTriggerEngine(): TriggerEngine {
  if (!engineInstance) {
    engineInstance = new TriggerEngine();
  }
  return engineInstance;
}

/**
 * Reset the singleton (useful for testing)
 */
export function resetTriggerEngine(): void {
  if (engineInstance) {
    engineInstance.clearAll();
  }
  engineInstance = null;
}
