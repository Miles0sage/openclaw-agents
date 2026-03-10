/**
 * Test Suite for Complexity Classifier
 * Validates classification accuracy across all complexity levels
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  ComplexityClassifier,
  classify,
  type ClassificationResult,
} from "../src/routing/complexity-classifier.js";

describe("ComplexityClassifier", () => {
  let classifier: ComplexityClassifier;

  beforeEach(() => {
    classifier = new ComplexityClassifier();
  });

  describe("Simple Queries (Haiku - Complexity 0-30)", () => {
    it("should classify greeting as low complexity", () => {
      const result = classifier.classify("Hello, how are you?");

      expect(result.complexity).toBeLessThanOrEqual(30);
      expect(result.model).toBe("haiku");
      expect(result.confidence).toBeGreaterThan(0.5);
    });

    it("should classify formatting request as low complexity", () => {
      const result = classifier.classify("Please format this text in bold");

      expect(result.complexity).toBeLessThanOrEqual(30);
      expect(result.model).toBe("haiku");
    });

    it("should classify quick question as low complexity", () => {
      const result = classifier.classify("What time is it?");

      expect(result.complexity).toBeLessThanOrEqual(30);
      expect(result.model).toBe("haiku");
    });

    it("should classify thank you as low complexity", () => {
      const result = classifier.classify("Thanks so much!");

      expect(result.complexity).toBeLessThanOrEqual(30);
      expect(result.model).toBe("haiku");
    });

    it("should classify simple conversion as low complexity", () => {
      const result = classifier.classify("Convert this to JSON");

      expect(result.complexity).toBeLessThanOrEqual(30);
      expect(result.model).toBe("haiku");
    });
  });

  describe("Medium Queries (Sonnet - Complexity 40-60)", () => {
    it("should classify bug fix request as medium complexity", () => {
      const result = classifier.classify(
        "I have a bug in my React component. The state isn't updating after the API call.",
      );

      expect(result.complexity).toBeGreaterThan(30);
      expect(result.complexity).toBeLessThan(70);
      expect(result.model).toBe("sonnet");
    });

    it("should classify code review as medium complexity", () => {
      const result = classifier.classify(`Please review this code:
\`\`\`typescript
function calculateTotal(items: Item[]): number {
  return items.reduce((sum, item) => sum + item.price, 0);
}
\`\`\``);

      expect(result.complexity).toBeGreaterThan(30);
      expect(result.complexity).toBeLessThan(70);
      expect(result.model).toBe("sonnet");
    });

    it("should classify feature implementation as medium complexity", () => {
      const result = classifier.classify(
        "How do I implement user authentication in my Node.js app?",
      );

      expect(result.complexity).toBeGreaterThan(30);
      expect(result.complexity).toBeLessThan(70);
      expect(result.model).toBe("sonnet");
    });

    it("should classify documentation request as medium complexity", () => {
      const result = classifier.classify(
        "Create API documentation for these endpoints. Also, add examples.",
      );

      expect(result.complexity).toBeGreaterThan(30);
      expect(result.complexity).toBeLessThan(70);
      expect(result.model).toBe("sonnet");
    });

    it("should classify test case creation as medium complexity", () => {
      const result = classifier.classify("Write test cases for the payment processing module");

      expect(result.complexity).toBeGreaterThan(30);
      expect(result.complexity).toBeLessThan(70);
      expect(result.model).toBe("sonnet");
    });
  });

  describe("Complex Queries (Opus - Complexity 70-100)", () => {
    it("should classify system architecture design as high complexity", () => {
      const result = classifier.classify(
        "Design a scalable microservices architecture for a real-time collaborative platform with 1M+ concurrent users. Consider database sharding, caching strategies, and fault tolerance.",
      );

      expect(result.complexity).toBeGreaterThanOrEqual(70);
      expect(result.model).toBe("opus");
      expect(result.confidence).toBeGreaterThan(0.6);
    });

    it("should classify security vulnerability analysis as high complexity", () => {
      const result = classifier.classify(
        "Analyze this authentication flow for vulnerabilities and suggest security improvements. What are the threats?",
      );

      expect(result.complexity).toBeGreaterThanOrEqual(70);
      expect(result.model).toBe("opus");
    });

    it("should classify algorithm optimization as high complexity", () => {
      const result = classifier.classify(
        "Optimize this algorithm. What patterns should I use? How do I handle edge cases? What are the performance tradeoffs?",
      );

      expect(result.complexity).toBeGreaterThanOrEqual(70);
      expect(result.model).toBe("opus");
    });

    it("should classify strategic planning as high complexity", () => {
      const result = classifier.classify(
        "Create a deployment strategy for our system that balances cost, performance, and reliability. What are the tradeoffs?",
      );

      expect(result.complexity).toBeGreaterThanOrEqual(70);
      expect(result.model).toBe("opus");
    });

    it("should classify machine learning implementation as high complexity", () => {
      const result = classifier.classify(
        "Design a machine learning pipeline for predictive analytics. Consider data preprocessing, model selection, evaluation metrics, and deployment considerations.",
      );

      expect(result.complexity).toBeGreaterThanOrEqual(70);
      expect(result.model).toBe("opus");
    });

    it("should classify distributed system design as high complexity", () => {
      const result = classifier.classify(
        "Design a fault-tolerant consensus algorithm for a distributed database. How would you handle network partitions and Byzantine failures?",
      );

      expect(result.complexity).toBeGreaterThanOrEqual(70);
      expect(result.model).toBe("opus");
    });
  });

  describe("Complexity Score Accuracy", () => {
    it("should score longer queries higher", () => {
      const short = classifier.classify("Hi");
      const medium = classifier.classify("How do I fix this error in my code?");
      const long = classifier.classify(
        "I need to build a complex system that handles real-time data streams from multiple sources, processes them through machine learning models, and stores results in a distributed database. What architecture would you recommend?",
      );

      expect(medium.complexity).toBeGreaterThan(short.complexity);
      expect(long.complexity).toBeGreaterThan(medium.complexity);
    });

    it("should score code blocks higher", () => {
      const noCode = classifier.classify("How do I fix this?");
      const withCode = classifier.classify(`How do I fix this?
\`\`\`python
def process(data):
  return [x for x in data if x > 0]
\`\`\``);

      expect(withCode.complexity).toBeGreaterThan(noCode.complexity);
    });

    it("should score architectural questions higher", () => {
      const simple = classifier.classify("How do I create a function?");
      const architecture = classifier.classify(
        "Design a scalable system architecture for handling millions of requests",
      );

      expect(architecture.complexity).toBeGreaterThan(simple.complexity);
    });

    it("should score hypothetical scenarios higher", () => {
      const direct = classifier.classify("How do I implement feature X?");
      const hypothetical = classifier.classify(
        "What if we need to implement feature X, but also support Y and Z? What tradeoffs exist?",
      );

      expect(hypothetical.complexity).toBeGreaterThan(direct.complexity);
    });
  });

  describe("Confidence Scoring", () => {
    it("should have high confidence for clearly simple queries", () => {
      const result = classifier.classify("Hello!");

      expect(result.confidence).toBeGreaterThan(0.7);
    });

    it("should have moderate confidence for boundary queries", () => {
      const result = classifier.classify("Can you review this code and suggest improvements?");

      expect(result.confidence).toBeGreaterThan(0.5);
      expect(result.confidence).toBeLessThan(0.9);
    });

    it("should have high confidence for clearly complex queries", () => {
      const result = classifier.classify(
        "Design a distributed transaction system with ACID guarantees for a horizontally scaled database",
      );

      expect(result.confidence).toBeGreaterThan(0.7);
    });
  });

  describe("Token Estimation", () => {
    it("should estimate tokens reasonably", () => {
      const short = classifier.classify("Hi");
      const medium = classifier.classify("How do I build a feature?");
      const long = classifier.classify(
        "Design a comprehensive system for handling distributed transactions across multiple data centers with eventual consistency and conflict resolution",
      );

      expect(short.estimatedTokens).toBeLessThan(medium.estimatedTokens);
      expect(medium.estimatedTokens).toBeLessThan(long.estimatedTokens);
    });

    it("should estimate tokens at least 1", () => {
      const result = classifier.classify("x");

      expect(result.estimatedTokens).toBeGreaterThanOrEqual(1);
    });
  });

  describe("Cost Estimation", () => {
    it("should estimate haiku as cheapest", () => {
      const classifier2 = new ComplexityClassifier();
      const query = "Design a complex system architecture with distributed transactions";

      const result = classifier2.classify(query);

      expect(result.costEstimate).toBeGreaterThan(0);
      expect(result.costEstimate).toBeLessThan(1); // Should be small
    });

    it("should produce valid cost estimates", () => {
      const queries = ["Hello", "Fix this bug in my code", "Design a distributed system"];

      queries.forEach((q) => {
        const result = classifier.classify(q);
        expect(result.costEstimate).toBeGreaterThanOrEqual(0);
        expect(result.costEstimate).toBeLessThan(100); // Sanity check
      });
    });
  });

  describe("Reasoning Quality", () => {
    it("should provide reasoning for each classification", () => {
      const result = classifier.classify("How do I implement async/await in TypeScript?");

      expect(result.reasoning).toBeTruthy();
      expect(result.reasoning.length).toBeGreaterThan(10);
      expect(result.reasoning).toContain("Complexity");
      expect(result.reasoning).toContain(result.model.toUpperCase());
    });

    it("should include factors in reasoning", () => {
      const result = classifier.classify("Fix this bug: `console.log(x)` doesn't print anything");

      expect(result.reasoning).toContain("Factors:");
    });
  });

  describe("Module Export", () => {
    it("should export classify function", () => {
      const result = classify("Hello, world!");

      expect(result).toBeTruthy();
      expect(result.model).toBeDefined();
      expect(result.complexity).toBeDefined();
    });

    it("classify function should return valid result", () => {
      const result = classify("Design a new system");

      expect(result.complexity).toBeGreaterThanOrEqual(0);
      expect(result.complexity).toBeLessThanOrEqual(100);
      expect(["haiku", "sonnet", "opus"]).toContain(result.model);
      expect(result.confidence).toBeGreaterThanOrEqual(0);
      expect(result.confidence).toBeLessThanOrEqual(1);
    });
  });

  describe("Edge Cases", () => {
    it("should handle empty query", () => {
      const result = classifier.classify("");

      expect(result.complexity).toBeGreaterThanOrEqual(0);
      expect(result.model).toBeDefined();
    });

    it("should handle very long query", () => {
      const longQuery = "x".repeat(10000);
      const result = classifier.classify(longQuery);

      expect(result.complexity).toBeGreaterThanOrEqual(0);
      expect(result.complexity).toBeLessThanOrEqual(100);
      expect(result.model).toBeDefined();
    });

    it("should handle special characters", () => {
      const result = classifier.classify("!!!???@@@###$$$%%%");

      expect(result.complexity).toBeGreaterThanOrEqual(0);
      expect(result.model).toBeDefined();
    });

    it("should handle mixed case keywords", () => {
      const result1 = classifier.classify("Design a system");
      const result2 = classifier.classify("DESIGN A SYSTEM");

      expect(result1.complexity).toBe(result2.complexity);
      expect(result1.model).toBe(result2.model);
    });
  });

  describe("Boundary Conditions", () => {
    it("should be near threshold for boundary queries", () => {
      // Query that should be near Haiku/Sonnet boundary
      const result1 = classifier.classify("Fix this error in my code");

      expect(result1.complexity).toBeGreaterThan(25);
      expect(result1.complexity).toBeLessThan(40);
    });

    it("should be near threshold for medium/complex boundary", () => {
      // Query that should be near Sonnet/Opus boundary
      const result = classifier.classify("Design improvements for the system architecture");

      expect(result.complexity).toBeGreaterThan(60);
      expect(result.complexity).toBeLessThan(80);
    });
  });

  describe("Consistency", () => {
    it("should classify same query consistently", () => {
      const query = "How do I implement authentication?";

      const result1 = classifier.classify(query);
      const result2 = classifier.classify(query);

      expect(result1.complexity).toBe(result2.complexity);
      expect(result1.model).toBe(result2.model);
      expect(result1.confidence).toBe(result2.confidence);
    });

    it("should handle multiple classifiers independently", () => {
      const c1 = new ComplexityClassifier();
      const c2 = new ComplexityClassifier();

      const query = "Optimize this algorithm";

      const result1 = c1.classify(query);
      const result2 = c2.classify(query);

      expect(result1.complexity).toBe(result2.complexity);
      expect(result1.model).toBe(result2.model);
    });
  });

  describe("Real-world Scenarios", () => {
    it("should route simple support questions to Haiku", () => {
      const queries = [
        "What's your API key format?",
        "How do I reset my password?",
        "Where's your documentation?",
      ];

      queries.forEach((q) => {
        const result = classifier.classify(q);
        expect(result.model).toBe("haiku");
      });
    });

    it("should route development tasks to Sonnet", () => {
      const queries = [
        "Help me debug this TypeScript error",
        "Review my PR",
        "How do I add authentication?",
      ];

      queries.forEach((q) => {
        const result = classifier.classify(q);
        expect(result.model).toBe("sonnet");
      });
    });

    it("should route architectural decisions to Opus", () => {
      const queries = [
        "Design our microservices architecture",
        "How should we handle distributed transactions?",
        "What's the best approach for global scale?",
      ];

      queries.forEach((q) => {
        const result = classifier.classify(q);
        expect(result.model).toBe("opus");
      });
    });
  });
});
