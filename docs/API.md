# OpenClaw REST & WebSocket API

**Base URL:** `https://<your-domain>`

**Authentication:** All endpoints require an `Authorization: Bearer <GATEWAY_AUTH_TOKEN>` header.

---

## Table of Contents

1. [Job Management](#job-management)
2. [Live Monitoring](#live-monitoring)
3. [Events](#events)
4. [Runner Control](#runner-control)
5. [Kill Switch](#kill-switch)
6. [WebSocket](#websocket)
7. [Error Responses](#error-responses)

---

## Job Management

### Create a Job

**Endpoint:** `POST /api/job/create`

Creates a new job and returns a job ID for tracking.

**Request:**

```json
{
  "project": "openclaw",
  "task": "Fix authentication bug in login flow",
  "priority": "P1"
}
```

**Parameters:**

- `project` (string, required): Project name (e.g., `openclaw`, `barber-crm`, `delhi-palace`)
- `task` (string, required): Description of the task to execute
- `priority` (string, required): One of `P0` (critical), `P1` (high), `P2` (medium), `P3` (low)

**Response:** `200 OK`

```json
{
  "job_id": "j_abc123def456",
  "project": "openclaw",
  "task": "Fix authentication bug in login flow",
  "status": "pending",
  "created_at": "2026-03-04T18:30:00Z"
}
```

**Error Responses:**

- `400 Bad Request`: Missing or invalid parameters
- `401 Unauthorized`: Invalid or missing auth token
- `500 Internal Server Error`: Server error

---

### Get Job Status

**Endpoint:** `GET /api/job/{job_id}`

Retrieves the current status and details of a specific job.

**Parameters:**

- `job_id` (path): The job ID (e.g., `j_abc123def456`)

**Response:** `200 OK`

```json
{
  "job_id": "j_abc123def456",
  "project": "openclaw",
  "task": "Fix authentication bug in login flow",
  "priority": "P1",
  "status": "analyzing",
  "created_at": "2026-03-04T18:30:00Z",
  "updated_at": "2026-03-04T18:31:15Z"
}
```

**Error Responses:**

- `404 Not Found`: Job ID does not exist
- `401 Unauthorized`: Invalid or missing auth token

---

### List All Jobs

**Endpoint:** `GET /api/jobs`

Returns a paginated list of all jobs.

**Query Parameters:**

- `status` (optional): Filter by status (`pending`, `analyzing`, `pr_ready`, `approved`, `done`)
- `project` (optional): Filter by project name
- `limit` (optional): Number of jobs per page (default: 50, max: 200)
- `offset` (optional): Pagination offset (default: 0)

**Response:** `200 OK`

```json
{
  "jobs": [
    {
      "job_id": "j_abc123def456",
      "project": "openclaw",
      "task": "Fix authentication bug",
      "priority": "P1",
      "status": "analyzing",
      "created_at": "2026-03-04T18:30:00Z"
    }
  ],
  "total": 15,
  "limit": 50,
  "offset": 0
}
```

---

### Approve a Job

**Endpoint:** `POST /api/job/{job_id}/approve`

Approves a job that is in `pr_ready` status, allowing it to proceed to execution.

**Parameters:**

- `job_id` (path): The job ID

**Request:**

```json
{
  "approved_by": "miles@example.com"
}
```

**Response:** `200 OK`

```json
{
  "job_id": "j_abc123def456",
  "status": "approved",
  "approved_by": "miles@example.com",
  "approved_at": "2026-03-04T18:35:00Z"
}
```

**Error Responses:**

- `400 Bad Request`: Job is not in `pr_ready` status
- `404 Not Found`: Job not found
- `401 Unauthorized`: Invalid or missing auth token

---

## Live Monitoring

### Get Live Job State

**Endpoint:** `GET /api/jobs/{job_id}/live`

Returns the current real-time state of a job, including phase, progress, and active tools.

**Parameters:**

- `job_id` (path): The job ID

**Response:** `200 OK`

```json
{
  "job_id": "j_abc123def456",
  "state": {
    "phase": "executing",
    "progress": 65,
    "active_tools": ["shell_execute", "file_read", "grep_search"],
    "cost": 0.0345,
    "phase_start": "2026-03-04T18:31:15Z"
  }
}
```

---

### Get Phase Timeline

**Endpoint:** `GET /api/jobs/{job_id}/phases`

Returns a detailed timeline of all phases the job has completed.

**Parameters:**

- `job_id` (path): The job ID

**Response:** `200 OK`

```json
{
  "job_id": "j_abc123def456",
  "phases": {
    "pending": {
      "start": "2026-03-04T18:30:00Z",
      "end": "2026-03-04T18:30:05Z",
      "duration_ms": 5000
    },
    "analyzing": {
      "start": "2026-03-04T18:30:05Z",
      "end": "2026-03-04T18:31:15Z",
      "duration_ms": 70000
    },
    "executing": {
      "start": "2026-03-04T18:31:15Z",
      "end": null,
      "duration_ms": null
    }
  }
}
```

---

### Get Cost Breakdown

**Endpoint:** `GET /api/jobs/{job_id}/costs`

Returns a detailed cost breakdown for a job, broken down by phase, tool, agent, and model.

**Parameters:**

- `job_id` (path): The job ID

**Response:** `200 OK`

```json
{
  "job_id": "j_abc123def456",
  "costs": {
    "by_phase": {
      "analyzing": 0.012,
      "executing": 0.0225
    },
    "by_tool": {
      "shell_execute": 0.018,
      "grep_search": 0.0055,
      "file_read": 0.001
    },
    "by_agent": {
      "coder_agent": 0.03,
      "database_agent": 0.0045
    },
    "by_model": {
      "claude-opus-4-6": 0.025,
      "gemini-2.5-flash": 0.0095
    }
  },
  "total_cost": 0.0345,
  "tool_usage": {
    "shell_execute": 12,
    "grep_search": 5,
    "file_read": 2
  }
}
```

---

### Get Active Jobs Overview

**Endpoint:** `GET /api/monitoring/active`

Returns a summary of all currently active jobs across all projects.

**Response:** `200 OK`

```json
{
  "active_jobs": 3,
  "jobs": {
    "j_abc123def456": {
      "project": "openclaw",
      "phase": "executing",
      "progress": 65,
      "active_tools": ["shell_execute"],
      "cost": 0.0345
    },
    "j_xyz789abc123": {
      "project": "barber-crm",
      "phase": "analyzing",
      "progress": 40,
      "active_tools": ["grep_search", "file_read"],
      "cost": 0.012
    }
  }
}
```

---

### Get Project Costs

**Endpoint:** `GET /api/monitoring/costs`

Returns cost metrics for a specific project over a time period.

**Query Parameters:**

- `project` (required): Project name (e.g., `openclaw`, `barber-crm`)
- `days` (optional): Number of days to look back (default: 7)

**Response:** `200 OK`

```json
{
  "project": "openclaw",
  "period_days": 7,
  "total_cost": 2.345,
  "daily_breakdown": {
    "2026-02-26": 0.234,
    "2026-02-27": 0.312,
    "2026-02-28": 0.189,
    "2026-03-01": 0.298,
    "2026-03-02": 0.412,
    "2026-03-03": 0.56,
    "2026-03-04": 0.34
  },
  "jobs_completed": 23,
  "avg_cost_per_job": 0.102
}
```

---

### Get Pipeline Phase Definitions

**Endpoint:** `GET /api/monitoring/phases`

Returns the definition of all pipeline phases and their standard durations.

**Response:** `200 OK`

```json
{
  "phases": [
    {
      "name": "pending",
      "description": "Job queued, waiting for analysis",
      "typical_duration_ms": 5000
    },
    {
      "name": "analyzing",
      "description": "AI agent analyzing task and planning approach",
      "typical_duration_ms": 60000
    },
    {
      "name": "executing",
      "description": "Agent executing task (running tools, code, tests)",
      "typical_duration_ms": 180000
    },
    {
      "name": "pr_ready",
      "description": "PR created, awaiting approval",
      "typical_duration_ms": null
    },
    {
      "name": "approved",
      "description": "PR approved, deploying changes",
      "typical_duration_ms": 120000
    },
    {
      "name": "done",
      "description": "Job completed successfully",
      "typical_duration_ms": null
    }
  ]
}
```

---

## Events

### Event Stream (Server-Sent Events)

**Endpoint:** `GET /api/events/stream`

Returns a real-time event stream of all job state changes. Uses Server-Sent Events (SSE) with `text/event-stream` content type.

**Response:** `200 OK` (stream)

```
data: {"type":"job.created","job_id":"j_abc123","project":"openclaw","task":"Fix bug","created_at":"2026-03-04T18:30:00Z"}

data: {"type":"job.status_changed","job_id":"j_abc123","status":"analyzing","timestamp":"2026-03-04T18:30:05Z"}

data: {"type":"job.cost_updated","job_id":"j_abc123","cost":0.0120,"timestamp":"2026-03-04T18:31:00Z"}

data: {"type":"job.completed","job_id":"j_abc123","status":"done","final_cost":0.0345,"timestamp":"2026-03-04T18:35:00Z"}
```

**Event Types:**

- `job.created`: New job created
- `job.status_changed`: Job status updated
- `job.cost_updated`: Cost increased (batched, ~5 min intervals)
- `job.completed`: Job finished
- `job.failed`: Job failed
- `job.kill_flag_set`: Kill flag activated

---

### Get Recent Events

**Endpoint:** `GET /api/events/recent`

Returns the last 50 events from the system.

**Query Parameters:**

- `limit` (optional): Number of events to return (default: 50, max: 500)
- `job_id` (optional): Filter events for a specific job

**Response:** `200 OK`

```json
{
  "events": [
    {
      "type": "job.created",
      "job_id": "j_abc123def456",
      "project": "openclaw",
      "task": "Fix authentication bug",
      "timestamp": "2026-03-04T18:30:00Z"
    },
    {
      "type": "job.status_changed",
      "job_id": "j_abc123def456",
      "status": "analyzing",
      "timestamp": "2026-03-04T18:30:05Z"
    }
  ],
  "total": 142
}
```

---

## Runner Control

### Queue Job for Execution

**Endpoint:** `POST /api/runner/execute/{job_id}`

Queues a job for immediate execution by the runner.

**Parameters:**

- `job_id` (path): The job ID

**Response:** `202 Accepted`

```json
{
  "job_id": "j_abc123def456",
  "status": "queued",
  "queue_position": 1,
  "estimated_start": "2026-03-04T18:36:00Z"
}
```

---

### Get Execution Progress

**Endpoint:** `GET /api/runner/progress/{job_id}`

Returns detailed progress information for a running job.

**Parameters:**

- `job_id` (path): The job ID

**Response:** `200 OK`

```json
{
  "job_id": "j_abc123def456",
  "phase": "executing",
  "progress_percent": 65,
  "elapsed_ms": 125000,
  "estimated_remaining_ms": 65000,
  "current_step": "Running tests...",
  "steps_completed": 7,
  "steps_total": 10,
  "output_tail": "Test 1: PASS\nTest 2: PASS\nTest 3: Running..."
}
```

---

### Cancel Running Job

**Endpoint:** `DELETE /api/runner/cancel/{job_id}`

Cancels a running job and sets its kill flag.

**Parameters:**

- `job_id` (path): The job ID

**Response:** `200 OK`

```json
{
  "job_id": "j_abc123def456",
  "status": "cancelled",
  "kill_flag_set": true,
  "reason": "Manual cancellation via API"
}
```

---

## Kill Switch

### Set Kill Flag on Job

**Endpoint:** `POST /api/jobs/{job_id}/kill`

Immediately terminates a running job by setting its kill flag.

**Parameters:**

- `job_id` (path): The job ID

**Request (optional):**

```json
{
  "reason": "Cost limit exceeded"
}
```

**Response:** `200 OK`

```json
{
  "job_id": "j_abc123def456",
  "kill_flag_set": true,
  "reason": "Cost limit exceeded",
  "timestamp": "2026-03-04T18:36:00Z"
}
```

---

### List Active Kill Flags

**Endpoint:** `GET /api/jobs/kill-flags`

Returns all currently active kill flags across all jobs.

**Response:** `200 OK`

```json
{
  "kill_flags": [
    {
      "job_id": "j_abc123def456",
      "reason": "Cost limit exceeded",
      "set_at": "2026-03-04T18:36:00Z",
      "set_by": "api"
    },
    {
      "job_id": "j_xyz789abc123",
      "reason": "Manual user cancellation",
      "set_at": "2026-03-04T18:37:15Z",
      "set_by": "user"
    }
  ],
  "total": 2
}
```

---

## WebSocket

### Real-Time Job Events

**Endpoint:** `WS /ws/jobs/{job_id}`

Establishes a bidirectional WebSocket connection for real-time job state updates. The server sends snapshots and heartbeats; the client can send commands.

**Parameters:**

- `job_id` (path): The job ID

**Server → Client (Snapshot):**

```json
{
  "type": "snapshot",
  "job_id": "j_abc123def456",
  "state": {
    "status": "executing",
    "phase": "executing",
    "progress": 65,
    "active_tools": ["shell_execute"],
    "cost": 0.0345,
    "phase_start": "2026-03-04T18:31:15Z",
    "timestamp": "2026-03-04T18:33:45Z"
  }
}
```

**Server → Client (Heartbeat):**

```json
{
  "type": "heartbeat",
  "ts": 1741200825.345
}
```

**Client → Server (Ping):**

```
"ping"
```

**Server → Client (Pong Response):**

```json
{
  "type": "pong",
  "ts": 1741200825.345
}
```

**Client → Server (Refresh):**

```
"refresh"
```

**Server → Client (New Snapshot in Response):**

```json
{
  "type": "snapshot",
  "job_id": "j_abc123def456",
  "state": { ... }
}
```

**Connection Behavior:**

- Server sends a snapshot immediately upon connection
- Server sends heartbeats every 30 seconds
- Server sends a new snapshot whenever the job state changes
- Connection closes when the job transitions to `done` or `failed`
- Maximum message size: 1 MB

---

## Error Responses

All error responses follow this format:

```json
{
  "error": "Invalid request",
  "error_code": "INVALID_REQUEST",
  "message": "Missing required parameter: project",
  "timestamp": "2026-03-04T18:30:00Z"
}
```

**Common HTTP Status Codes:**

| Code | Meaning                                   |
| ---- | ----------------------------------------- |
| 200  | Success                                   |
| 202  | Accepted (async operation)                |
| 400  | Bad Request (invalid parameters)          |
| 401  | Unauthorized (missing/invalid auth token) |
| 404  | Not Found (resource doesn't exist)        |
| 429  | Too Many Requests (rate limited)          |
| 500  | Internal Server Error                     |
| 503  | Service Unavailable                       |

**Rate Limiting:**

- 100 requests per minute per API token
- WebSocket connections: 5 concurrent per token
- Returns `429 Too Many Requests` with `Retry-After` header when exceeded

---

## Authentication

All endpoints (except health checks) require the `Authorization` header:

```
Authorization: Bearer <GATEWAY_AUTH_TOKEN>
```

Obtain a gateway auth token from the OpenClaw dashboard or environment variable `GATEWAY_AUTH_TOKEN`.

**Token Format:** Base64-encoded string (typically 64-256 characters)

**Example Request:**

```bash
curl -X GET https://<your-domain>/api/jobs \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

## Versioning

Current API version: **v1**

Future breaking changes will be released as `/api/v2/...` with the v1 endpoints deprecated for 6 months.
