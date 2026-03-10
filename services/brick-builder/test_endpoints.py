"""Quick test script for brick-builder endpoints."""

import json
import requests
from time import sleep
import subprocess
import sys

BASE_URL = "http://localhost:8001"

def test_health():
    """Test health endpoint."""
    print("Testing /health...")
    resp = requests.get(f"{BASE_URL}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "service" in data
    print("✓ Health check passed")


def test_save_build():
    """Test save build endpoint."""
    print("\nTesting POST /api/builds/save...")
    payload = {
        "name": "Test Tower",
        "description": "A simple test tower",
        "bricks": [
            {"x": 0, "y": 0, "z": 0, "color": "red", "size": "standard"},
            {"x": 0, "y": 0, "z": 1, "color": "blue", "size": "standard"},
            {"x": 0, "y": 0, "z": 2, "color": "yellow", "size": "standard"}
        ]
    }
    resp = requests.post(f"{BASE_URL}/api/builds/save", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Tower"
    assert len(data["bricks"]) == 3
    build_id = data["id"]
    print(f"✓ Build saved with ID: {build_id}")
    return build_id


def test_load_build(build_id):
    """Test load build endpoint."""
    print(f"\nTesting POST /api/builds/load with ID {build_id}...")
    resp = requests.post(
        f"{BASE_URL}/api/builds/load",
        json={"build_id": build_id}
    )
    # Try as query param if body doesn't work
    if resp.status_code != 200:
        resp = requests.post(
            f"{BASE_URL}/api/builds/load?build_id={build_id}"
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Tower"
    print("✓ Build loaded successfully")


def test_list_builds():
    """Test list builds endpoint."""
    print("\nTesting GET /api/builds/list...")
    resp = requests.get(f"{BASE_URL}/api/builds/list")
    assert resp.status_code == 200
    data = resp.json()
    assert "builds" in data
    assert "count" in data
    print(f"✓ Listed {data['count']} builds")


def start_server():
    """Start the FastAPI server in background."""
    print("Starting server...")
    proc = subprocess.Popen(
        ["python3", "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8001"],
        cwd="./services/brick-builder",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    sleep(2)  # Give server time to start
    return proc


if __name__ == "__main__":
    proc = start_server()

    try:
        test_health()
        build_id = test_save_build()
        test_load_build(build_id)
        test_list_builds()
        print("\n✅ All tests passed!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    finally:
        proc.terminate()
        proc.wait()
