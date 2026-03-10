/**
 * Simple test to validate memory module structure and types
 */

import * as Memory from "./src/memory";

// Test type exports
const testMemory: Memory.Memory = {
  id: "test_id",
  user_id: "user_123",
  category: "preference",
  data: "I like pizza",
  hash: "abc123",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const testAddRequest: Memory.MemoryAddRequest = {
  data: "Test memory",
  user_id: "user_123",
  category: "fact",
};

const testSearchRequest: Memory.MemorySearchRequest = {
  query: "pizza",
  user_id: "user_123",
  limit: 10,
};

console.log("✓ Memory module types validated");
console.log("✓ Ready for D1 integration");
