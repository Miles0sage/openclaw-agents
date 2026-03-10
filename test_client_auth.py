"""
Tests for the OpenClaw Client Authentication & Billing System

Test coverage:
- API key generation and validation
- Client creation and management
- Plan-based usage limits
- Billing cycle reset
- Stripe webhook handling (stubbed)
- Admin endpoints
- Authorization checks
"""

import pytest
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

# Import the client auth module
from client_auth import (
    router,
    authenticate_client,
    check_job_limit,
    deduct_credit,
    reset_monthly_credits,
    get_client_usage,
    _generate_api_key,
    _load_clients,
    _save_clients,
    _now_iso,
    CLIENTS_FILE,
    PLANS,
    get_client_by_api_key,
    can_submit_job,
    deduct_job_credit,
    log_client_cost,
)

# Create test app
app = FastAPI()
app.include_router(router)
client = TestClient(app)

# Test fixtures
@pytest.fixture(autouse=True)
def reset_clients_file():
    """Reset the clients file before and after each test."""
    # Clean before
    if os.path.exists(CLIENTS_FILE):
        os.remove(CLIENTS_FILE)
    _save_clients({})
    yield
    # Clean after
    if os.path.exists(CLIENTS_FILE):
        os.remove(CLIENTS_FILE)


@pytest.fixture
def admin_token():
    """Return a valid admin token."""
    return "admin-token-secret"


@pytest.fixture
def sample_client():
    """Create a sample client and return its data."""
    now = datetime.now(timezone.utc)
    return {
        "client_id": "test-client-123",
        "name": "Test Client",
        "email": "test@example.com",
        "api_key": "oc_live_abcdef123456",
        "plan": "starter",
        "credits_remaining": 50,
        "total_spent": 0.0,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "active": True,
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "billing_cycle_start": now.isoformat(),
        "billing_cycle_end": (now + timedelta(days=30)).isoformat(),
        "metadata": {},
    }


# ═══════════════════════════════════════════════════════════════════════
# TESTS: API Key Generation
# ═══════════════════════════════════════════════════════════════════════


def test_api_key_generation():
    """Test that API keys are generated with correct format."""
    key = _generate_api_key()
    assert key.startswith("oc_live_")
    assert len(key) == len("oc_live_") + 32  # 32 hex chars


def test_api_key_uniqueness():
    """Test that generated API keys are unique."""
    keys = set(_generate_api_key() for _ in range(100))
    assert len(keys) == 100  # All unique


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Client Authentication
# ═══════════════════════════════════════════════════════════════════════


def test_authenticate_valid_key(sample_client):
    """Test authenticating with a valid API key."""
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    auth_result = authenticate_client(sample_client["api_key"])
    assert auth_result is not None
    assert auth_result["client_id"] == sample_client["client_id"]
    assert auth_result["email"] == sample_client["email"]


def test_authenticate_invalid_key():
    """Test that invalid keys return None."""
    assert authenticate_client("invalid-key") is None
    assert authenticate_client("oc_live_fakefakefake") is None
    assert authenticate_client("") is None
    assert authenticate_client(None) is None


def test_authenticate_inactive_client(sample_client):
    """Test that inactive clients cannot authenticate."""
    sample_client["active"] = False
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    auth_result = authenticate_client(sample_client["api_key"])
    assert auth_result is None


def test_authenticate_wrong_key_format():
    """Test that keys without oc_live_ prefix are rejected."""
    # Valid format but invalid key
    assert authenticate_client("sk_test_invalidkey") is None
    assert authenticate_client("pk_live_invalidkey") is None


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Job Limits
# ═══════════════════════════════════════════════════════════════════════


def test_job_limit_free_plan():
    """Test that free plan has 5 job limit."""
    client = {
        "plan": "free",
        "credits_remaining": 5,
        "active": True,
    }
    allowed, reason = check_job_limit(client)
    assert allowed is True
    assert "5" in reason

    # Exhaust credits
    client["credits_remaining"] = 0
    allowed, reason = check_job_limit(client)
    assert allowed is False
    assert "limit reached" in reason.lower()


def test_job_limit_starter_plan():
    """Test that starter plan has 50 job limit."""
    client = {
        "plan": "starter",
        "credits_remaining": 50,
        "active": True,
    }
    allowed, reason = check_job_limit(client)
    assert allowed is True

    # Exhaust credits
    client["credits_remaining"] = 0
    allowed, reason = check_job_limit(client)
    assert allowed is False


def test_job_limit_pro_plan():
    """Test that pro plan has 200 job limit."""
    client = {
        "plan": "pro",
        "credits_remaining": 200,
        "active": True,
    }
    allowed, reason = check_job_limit(client)
    assert allowed is True


def test_job_limit_enterprise_plan():
    """Test that enterprise plan has unlimited jobs."""
    client = {
        "plan": "enterprise",
        "credits_remaining": 0,  # Doesn't matter for enterprise
        "active": True,
    }
    allowed, reason = check_job_limit(client)
    assert allowed is True
    assert "unlimited" in reason.lower()


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Credit Management
# ═══════════════════════════════════════════════════════════════════════


def test_deduct_credit_success(sample_client):
    """Test successfully deducting a credit."""
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    original = sample_client["credits_remaining"]
    result = deduct_credit(sample_client["client_id"])
    assert result is True

    clients = _load_clients()
    assert clients[sample_client["client_id"]]["credits_remaining"] == original - 1


def test_deduct_credit_nonexistent_client():
    """Test deducting credit for nonexistent client."""
    result = deduct_credit("nonexistent-client-id")
    assert result is False


def test_deduct_credit_enterprise_plan():
    """Test that enterprise plans don't deduct credits."""
    sample_client = {
        "client_id": "enterprise-client",
        "plan": "enterprise",
        "credits_remaining": 0,
        "active": True,
    }
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    deduct_credit(sample_client["client_id"])
    clients = _load_clients()
    # Enterprise should remain at 0 (not negative)
    assert clients[sample_client["client_id"]]["credits_remaining"] == 0


def test_deduct_credit_at_zero():
    """Test that deducting doesn't go below zero."""
    sample_client = {
        "client_id": "test-client",
        "plan": "starter",
        "credits_remaining": 0,
        "active": True,
    }
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    deduct_credit(sample_client["client_id"])
    clients = _load_clients()
    assert clients[sample_client["client_id"]]["credits_remaining"] == 0


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Billing Cycle Reset
# ═══════════════════════════════════════════════════════════════════════


def test_billing_cycle_not_reset_if_ongoing(sample_client):
    """Test that credits aren't reset if billing cycle is ongoing."""
    original_credits = sample_client["credits_remaining"]
    result = reset_monthly_credits(sample_client)
    assert result["credits_remaining"] == original_credits


def test_billing_cycle_reset_if_expired(sample_client):
    """Test that credits are reset when billing cycle expires."""
    now = datetime.now(timezone.utc)
    # Set cycle to have ended 1 day ago
    old_cycle_end = (now - timedelta(days=1)).isoformat()
    sample_client["billing_cycle_end"] = old_cycle_end
    sample_client["credits_remaining"] = 0  # Exhausted

    result = reset_monthly_credits(sample_client)
    # Should have reset to plan limit
    assert result["credits_remaining"] == PLANS["starter"]["job_limit"]
    # Cycle end should be updated (parse both as datetimes to compare correctly)
    new_cycle_end = datetime.fromisoformat(result["billing_cycle_end"])
    old_cycle_end_dt = datetime.fromisoformat(old_cycle_end)
    assert new_cycle_end > old_cycle_end_dt


def test_billing_cycle_reset_sets_correct_dates(sample_client):
    """Test that billing cycle reset sets correct start and end dates."""
    now = datetime.now(timezone.utc)
    sample_client["billing_cycle_end"] = (now - timedelta(hours=1)).isoformat()

    result = reset_monthly_credits(sample_client)
    cycle_end = datetime.fromisoformat(result["billing_cycle_end"])

    # End should be ~30 days from now (within 1 minute tolerance)
    expected = now + timedelta(days=30)
    assert abs((cycle_end - expected).total_seconds()) < 60


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Usage Reporting
# ═══════════════════════════════════════════════════════════════════════


def test_get_client_usage_basic(sample_client):
    """Test basic usage reporting."""
    usage = get_client_usage(sample_client)
    assert usage.client_id == sample_client["client_id"]
    assert usage.plan == "starter"
    assert usage.credits_remaining == 50
    assert usage.credits_limit == 50
    assert usage.status == "active"


def test_get_client_usage_percentage():
    """Test usage percentage calculation."""
    sample = {
        "client_id": "test",
        "plan": "starter",  # 50 job limit
        "credits_remaining": 25,  # Used 25
        "billing_cycle_start": _now_iso(),
        "billing_cycle_end": (datetime.now(timezone.utc) + timedelta(days=15)).isoformat(),
        "total_spent": 49.0,
    }
    usage = get_client_usage(sample)
    assert usage.usage_pct == 50.0  # 25 used out of 50


def test_get_client_usage_at_limit():
    """Test usage status when at limit."""
    sample = {
        "client_id": "test",
        "plan": "starter",
        "credits_remaining": 0,
        "billing_cycle_start": _now_iso(),
        "billing_cycle_end": (datetime.now(timezone.utc) + timedelta(days=15)).isoformat(),
        "total_spent": 0.0,
    }
    usage = get_client_usage(sample)
    assert usage.status == "at_limit"
    assert usage.usage_pct == 100.0


# ═══════════════════════════════════════════════════════════════════════
# TESTS: API Endpoints - Billing Plans
# ═══════════════════════════════════════════════════════════════════════


def test_list_billing_plans():
    """Test GET /api/billing/plans endpoint."""
    response = client.get("/api/billing/plans")
    assert response.status_code == 200
    plans = response.json()
    assert "free" in plans
    assert "starter" in plans
    assert "pro" in plans
    assert "enterprise" in plans
    assert plans["free"]["price"] == 0.0
    assert plans["starter"]["price"] == 49.0
    assert plans["pro"]["price"] == 199.0


def test_billing_plans_content():
    """Test that billing plans have all required fields."""
    response = client.get("/api/billing/plans")
    plans = response.json()
    for plan_id, plan in plans.items():
        assert "plan_id" in plan
        assert "name" in plan
        assert "price" in plan
        assert "currency" in plan
        assert "billing_period" in plan
        assert "job_limit" in plan
        assert "features" in plan
        assert isinstance(plan["features"], list)


# ═══════════════════════════════════════════════════════════════════════
# TESTS: API Endpoints - Client Usage
# ═══════════════════════════════════════════════════════════════════════


def test_get_usage_without_key():
    """Test that usage endpoint requires X-Client-Key."""
    response = client.get("/api/billing/usage")
    assert response.status_code == 401
    assert "X-Client-Key" in response.json()["detail"]


def test_get_usage_with_invalid_key():
    """Test that invalid API key is rejected."""
    response = client.get(
        "/api/billing/usage",
        headers={"X-Client-Key": "invalid-key"}
    )
    assert response.status_code == 401


def test_get_usage_with_valid_key(sample_client):
    """Test getting usage with valid client key."""
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    response = client.get(
        "/api/billing/usage",
        headers={"X-Client-Key": sample_client["api_key"]}
    )
    assert response.status_code == 200
    usage = response.json()
    assert usage["client_id"] == sample_client["client_id"]
    assert usage["plan"] == "starter"
    assert usage["status"] == "active"


# ═══════════════════════════════════════════════════════════════════════
# TESTS: API Endpoints - Checkout (Stub)
# ═══════════════════════════════════════════════════════════════════════


def test_checkout_without_key():
    """Test that checkout requires X-Client-Key."""
    response = client.post(
        "/api/billing/checkout?plan_id=starter"
    )
    assert response.status_code == 401


def test_checkout_invalid_plan():
    """Test that invalid plan is rejected."""
    sample_client = {
        "client_id": "test",
        "api_key": "oc_live_test123",
        "active": True,
    }
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    response = client.post(
        "/api/billing/checkout?plan_id=invalid_plan",
        headers={"X-Client-Key": sample_client["api_key"]}
    )
    assert response.status_code == 400


def test_checkout_enterprise_plan(sample_client):
    """Test that enterprise plan checkout is rejected (contact sales)."""
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    response = client.post(
        "/api/billing/checkout?plan_id=enterprise",
        headers={"X-Client-Key": sample_client["api_key"]}
    )
    assert response.status_code == 400
    assert "enterprise" in response.json()["detail"].lower()


def test_checkout_success(sample_client):
    """Test successful checkout session creation."""
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    response = client.post(
        "/api/billing/checkout?plan_id=starter",
        headers={"X-Client-Key": sample_client["api_key"]}
    )
    assert response.status_code == 200
    checkout = response.json()
    assert "session_id" in checkout
    assert "checkout_url" in checkout
    assert checkout["plan_id"] == "starter"
    assert checkout["price"] == 49.0


# ═══════════════════════════════════════════════════════════════════════
# TESTS: API Endpoints - Admin Create Client
# ═══════════════════════════════════════════════════════════════════════


def test_create_client_without_auth():
    """Test that client creation requires admin token."""
    response = client.post(
        "/api/admin/clients",
        json={
            "name": "New Client",
            "email": "new@example.com",
            "plan": "starter",
        }
    )
    assert response.status_code == 401


def test_create_client_with_invalid_token():
    """Test that invalid admin token is rejected."""
    response = client.post(
        "/api/admin/clients",
        json={
            "name": "New Client",
            "email": "new@example.com",
            "plan": "starter",
        },
        headers={"X-Auth-Token": "wrong-token"}
    )
    assert response.status_code == 401


def test_create_client_success(admin_token):
    """Test successful client creation."""
    response = client.post(
        "/api/admin/clients",
        json={
            "name": "New Client",
            "email": "new@example.com",
            "plan": "starter",
        },
        headers={"X-Auth-Token": admin_token}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Client"
    assert data["email"] == "new@example.com"
    assert data["plan"] == "starter"
    assert data["api_key"].startswith("oc_live_")
    assert data["credits_remaining"] == 50
    assert data["active"] is True


def test_create_client_invalid_plan(admin_token):
    """Test that invalid plan is rejected."""
    response = client.post(
        "/api/admin/clients",
        json={
            "name": "New Client",
            "email": "new@example.com",
            "plan": "invalid_plan",
        },
        headers={"X-Auth-Token": admin_token}
    )
    assert response.status_code == 400


def test_create_client_duplicate_email(admin_token):
    """Test that duplicate emails are rejected."""
    # Create first client
    client.post(
        "/api/admin/clients",
        json={
            "name": "Client 1",
            "email": "test@example.com",
            "plan": "free",
        },
        headers={"X-Auth-Token": admin_token}
    )
    # Try to create with same email
    response = client.post(
        "/api/admin/clients",
        json={
            "name": "Client 2",
            "email": "test@example.com",
            "plan": "starter",
        },
        headers={"X-Auth-Token": admin_token}
    )
    assert response.status_code == 409


def test_create_client_free_plan(admin_token):
    """Test creating client on free plan."""
    response = client.post(
        "/api/admin/clients",
        json={
            "name": "Free Client",
            "email": "free@example.com",
            "plan": "free",
        },
        headers={"X-Auth-Token": admin_token}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["credits_remaining"] == 5  # Free plan limit


# ═══════════════════════════════════════════════════════════════════════
# TESTS: API Endpoints - Admin List Clients
# ═══════════════════════════════════════════════════════════════════════


def test_list_clients_without_auth():
    """Test that listing clients requires admin token."""
    response = client.get("/api/admin/clients")
    assert response.status_code == 401


def test_list_clients_with_valid_token(admin_token, sample_client):
    """Test listing clients with valid admin token."""
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    response = client.get(
        "/api/admin/clients",
        headers={"X-Auth-Token": admin_token}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["clients"]) == 1
    # Ensure API key is not returned
    assert "api_key" not in data["clients"][0]


def test_list_clients_filter_active(admin_token, sample_client):
    """Test filtering clients by active status."""
    clients_data = _load_clients()
    clients_data[sample_client["client_id"]] = sample_client
    clients_data["inactive"] = {**sample_client, "client_id": "inactive", "active": False}
    _save_clients(clients_data)

    response = client.get(
        "/api/admin/clients?status=active",
        headers={"X-Auth-Token": admin_token}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["clients"][0]["active"] is True


def test_list_clients_filter_inactive(admin_token, sample_client):
    """Test filtering clients by inactive status."""
    clients_data = _load_clients()
    clients_data[sample_client["client_id"]] = sample_client
    clients_data["inactive"] = {**sample_client, "client_id": "inactive", "active": False}
    _save_clients(clients_data)

    response = client.get(
        "/api/admin/clients?status=inactive",
        headers={"X-Auth-Token": admin_token}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["clients"][0]["active"] is False


# ═══════════════════════════════════════════════════════════════════════
# TESTS: API Endpoints - Admin Add Credits
# ═══════════════════════════════════════════════════════════════════════


def test_add_credits_without_auth():
    """Test that adding credits requires admin token."""
    response = client.put(
        "/api/admin/clients/test-id/credits",
        json={"credits": 10}
    )
    assert response.status_code == 401


def test_add_credits_nonexistent_client(admin_token):
    """Test adding credits to nonexistent client."""
    response = client.put(
        "/api/admin/clients/nonexistent/credits",
        json={"credits": 10},
        headers={"X-Auth-Token": admin_token}
    )
    assert response.status_code == 404


def test_add_credits_success(admin_token, sample_client):
    """Test successfully adding credits."""
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    response = client.put(
        f"/api/admin/clients/{sample_client['client_id']}/credits",
        json={"credits": 10, "reason": "promotional credit"},
        headers={"X-Auth-Token": admin_token}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["previous_credits"] == 50
    assert data["credits_added"] == 10
    assert data["new_credits"] == 60


def test_add_credits_enterprise_plan(admin_token):
    """Test that adding credits to enterprise plan fails."""
    enterprise_client = {
        "client_id": "enterprise",
        "plan": "enterprise",
        "active": True,
        "credits_remaining": 0,
    }
    clients = _load_clients()
    clients[enterprise_client["client_id"]] = enterprise_client
    _save_clients(clients)

    response = client.put(
        "/api/admin/clients/enterprise/credits",
        json={"credits": 10},
        headers={"X-Auth-Token": admin_token}
    )
    assert response.status_code == 400


# ═══════════════════════════════════════════════════════════════════════
# TESTS: API Endpoints - Admin Deactivate Client
# ═══════════════════════════════════════════════════════════════════════


def test_deactivate_client_without_auth():
    """Test that deactivating requires admin token."""
    response = client.delete("/api/admin/clients/test-id")
    assert response.status_code == 401


def test_deactivate_client_nonexistent(admin_token):
    """Test deactivating nonexistent client."""
    response = client.delete(
        "/api/admin/clients/nonexistent",
        headers={"X-Auth-Token": admin_token}
    )
    assert response.status_code == 404


def test_deactivate_client_success(admin_token, sample_client):
    """Test successfully deactivating a client."""
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    response = client.delete(
        f"/api/admin/clients/{sample_client['client_id']}",
        headers={"X-Auth-Token": admin_token}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "deactivated"

    # Verify client is now inactive
    clients = _load_clients()
    assert clients[sample_client["client_id"]]["active"] is False


def test_deactivate_already_inactive_client(admin_token, sample_client):
    """Test deactivating an already-inactive client."""
    sample_client["active"] = False
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    response = client.delete(
        f"/api/admin/clients/{sample_client['client_id']}",
        headers={"X-Auth-Token": admin_token}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "was_inactive"


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Helper Functions
# ═══════════════════════════════════════════════════════════════════════


def test_get_client_by_api_key(sample_client):
    """Test the get_client_by_api_key helper."""
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    result = get_client_by_api_key(sample_client["api_key"])
    assert result is not None
    assert result["client_id"] == sample_client["client_id"]


def test_can_submit_job_success(sample_client):
    """Test can_submit_job for active client with credits."""
    allowed, reason = can_submit_job(sample_client)
    assert allowed is True


def test_can_submit_job_inactive_client(sample_client):
    """Test can_submit_job for inactive client."""
    sample_client["active"] = False
    allowed, reason = can_submit_job(sample_client)
    assert allowed is False
    assert "inactive" in reason.lower()


def test_can_submit_job_no_credits(sample_client):
    """Test can_submit_job when credits are exhausted."""
    sample_client["credits_remaining"] = 0
    allowed, reason = can_submit_job(sample_client)
    assert allowed is False
    assert "limit" in reason.lower()


def test_deduct_job_credit(sample_client):
    """Test the deduct_job_credit helper."""
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    result = deduct_job_credit(sample_client["client_id"])
    assert result is True

    clients = _load_clients()
    assert clients[sample_client["client_id"]]["credits_remaining"] == 49


def test_log_client_cost(sample_client):
    """Test logging costs to client account."""
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    result = log_client_cost(sample_client["client_id"], 5.50, "job-123")
    assert result is True

    clients = _load_clients()
    updated = clients[sample_client["client_id"]]
    assert updated["total_spent"] == 5.50
    assert len(updated["metadata"]["cost_log"]) == 1
    assert updated["metadata"]["cost_log"][0]["cost"] == 5.50


# ═══════════════════════════════════════════════════════════════════════
# TESTS: Stripe Webhook (Stub)
# ═══════════════════════════════════════════════════════════════════════


def test_webhook_checkout_completed():
    """Test Stripe webhook for checkout completion."""
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": "cus_test123",
                "subscription": "sub_test123",
            }
        }
    }
    response = client.post(
        "/api/billing/webhook",
        json=event,
        headers={"stripe-signature": "stub"}
    )
    assert response.status_code == 200


def test_webhook_subscription_updated():
    """Test Stripe webhook for subscription update."""
    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {}}
    }
    response = client.post(
        "/api/billing/webhook",
        json=event,
        headers={"stripe-signature": "stub"}
    )
    assert response.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASES & INTEGRATION
# ═══════════════════════════════════════════════════════════════════════


def test_multiple_credit_adjustments(admin_token, sample_client):
    """Test tracking multiple credit adjustments."""
    clients = _load_clients()
    clients[sample_client["client_id"]] = sample_client
    _save_clients(clients)

    # Add credits multiple times
    for i in range(3):
        client.put(
            f"/api/admin/clients/{sample_client['client_id']}/credits",
            json={"credits": 10},
            headers={"X-Auth-Token": admin_token}
        )

    clients = _load_clients()
    adjustments = clients[sample_client["client_id"]]["metadata"]["credit_adjustments"]
    assert len(adjustments) == 3


def test_client_lifecycle():
    """Test complete client lifecycle: create → use → upgrade → deactivate."""
    admin_token = "admin-token-secret"

    # 1. Create client on free plan
    create_resp = client.post(
        "/api/admin/clients",
        json={"name": "Growth Client", "email": "growth@test.com", "plan": "free"},
        headers={"X-Auth-Token": admin_token}
    )
    assert create_resp.status_code == 200
    client_id = create_resp.json()["client_id"]
    api_key = create_resp.json()["api_key"]

    # 2. Check usage
    usage_resp = client.get(
        "/api/billing/usage",
        headers={"X-Client-Key": api_key}
    )
    assert usage_resp.status_code == 200
    assert usage_resp.json()["plan"] == "free"
    assert usage_resp.json()["credits_remaining"] == 5

    # 3. Use up some credits
    clients_data = _load_clients()
    clients_data[client_id]["credits_remaining"] = 1
    _save_clients(clients_data)

    # 4. Check usage again
    usage_resp = client.get(
        "/api/billing/usage",
        headers={"X-Client-Key": api_key}
    )
    assert usage_resp.json()["credits_remaining"] == 1
    assert usage_resp.json()["usage_pct"] == 80.0

    # 5. Admin adds credits
    add_resp = client.put(
        f"/api/admin/clients/{client_id}/credits",
        json={"credits": 50},
        headers={"X-Auth-Token": admin_token}
    )
    assert add_resp.status_code == 200

    # 6. Deactivate
    deactivate_resp = client.delete(
        f"/api/admin/clients/{client_id}",
        headers={"X-Auth-Token": admin_token}
    )
    assert deactivate_resp.status_code == 200

    # 7. Verify deactivation
    clients_data = _load_clients()
    assert clients_data[client_id]["active"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
