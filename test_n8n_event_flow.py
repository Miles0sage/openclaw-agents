#!/usr/bin/env python3
"""
Test script to verify end-to-end n8n event flow.

This script:
1. Creates a test event by emitting a job.completed event
2. Verifies that the event_engine subscriber reaches n8n webhook
3. Confirms the complete flow: emit -> n8n_webhook_notify -> n8n receives event

Usage:
    python3 ./test_n8n_event_flow.py
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

# Add openclaw to path
sys.path.insert(0, '.')

from event_engine import init_event_engine, get_event_engine

# Global to capture webhook POST
received_events = []

class WebhookHandler(BaseHTTPRequestHandler):
    """Simple HTTP server to capture webhook POSTs from event_engine."""

    def do_POST(self):
        """Handle POST requests."""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)

        try:
            event_data = json.loads(body.decode('utf-8'))
            received_events.append({
                'path': self.path,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'data': event_data
            })

            # Respond with 200 OK
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True, 'received': True}).encode('utf-8'))

            print(f"[WEBHOOK] Received event: {event_data.get('event_type')}")
        except Exception as e:
            print(f"[ERROR] Failed to parse webhook: {e}")
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def start_test_webhook_server(port=19999):
    """Start a local webhook server to capture events."""
    server = HTTPServer(('localhost', port), WebhookHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_event_flow():
    """Test the complete event flow."""
    print("=" * 70)
    print("OpenClaw n8n Event Flow Test")
    print("=" * 70)

    # Start test webhook server
    print("\n[1] Starting test webhook server on localhost:19999...")
    test_server = start_test_webhook_server(19999)
    time.sleep(0.5)
    print("[✓] Webhook server started")

    # Override environment to point to test webhook server
    print("\n[2] Configuring event_engine to use test webhook...")
    os.environ['N8N_BASE_URL'] = 'http://localhost:19999'
    os.environ['N8N_WEBHOOK_MODE'] = 'webhook'
    os.environ['N8N_WEBHOOK_PATH'] = 'openclaw-events'
    print(f"[✓] N8N_BASE_URL: {os.environ['N8N_BASE_URL']}")

    # Initialize event engine
    print("\n[3] Initializing event_engine...")
    engine = init_event_engine()
    print("[✓] Event engine initialized")

    # Emit test event
    print("\n[4] Emitting test job.completed event...")
    test_event = {
        'job_id': 'test-job-12345',
        'agent': 'test_agent',
        'task_type': 'test_task',
        'status': 'success',
        'result': 'Test event for n8n integration validation'
    }
    engine.emit('job.completed', test_event)
    print(f"[✓] Event emitted: {json.dumps(test_event, indent=2)}")

    # Wait for async processing
    print("\n[5] Waiting for event to reach webhook (2 seconds)...")
    time.sleep(2)

    # Check results
    print("\n[6] Checking webhook capture...")
    if received_events:
        print(f"[✓] SUCCESS! Received {len(received_events)} event(s):")
        for i, evt in enumerate(received_events, 1):
            print(f"\n    Event {i}:")
            print(f"      Path: {evt['path']}")
            print(f"      Received: {evt['timestamp']}")
            print(f"      Data: {json.dumps(evt['data'], indent=8)}")

        # Verify event structure
        first_event = received_events[0]['data']
        assert first_event.get('event_type') == 'job.completed', "Event type mismatch"
        assert first_event.get('data', {}).get('job_id') == 'test-job-12345', "Job ID mismatch"
        print("\n[✓] Event structure validated")

        return True
    else:
        print("[✗] FAILED! No events received by webhook")
        print("\n    Possible causes:")
        print("    1. event_engine._n8n_webhook_notify() is not being called")
        print("    2. The subscriber registration failed")
        print("    3. Event filtering is excluding this event type")
        return False


if __name__ == '__main__':
    try:
        success = test_event_flow()
        print("\n" + "=" * 70)
        if success:
            print("Result: n8n event flow is WORKING ✓")
            print("\nNext steps:")
            print("1. Deploy Cost Alert workflow for cost.alert events")
            print("2. Deploy Daily Digest workflow with cron trigger at 9am")
            print("3. Test with real job completions from autonomous_runner")
        else:
            print("Result: n8n event flow FAILED ✗")
            print("\nDebugging:")
            print("1. Check ./logs/openclaw.log for event_engine errors")
            print("2. Verify event_engine subscribers: grep '_n8n_webhook_notify' event_engine.py")
            print("3. Check if events are being emitted: grep 'engine.emit' gateway.py")
        print("=" * 70)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[ERROR] Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
