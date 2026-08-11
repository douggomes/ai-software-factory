---
spec_id: SPEC-TICKET-001
schema_version: 1
title: Implement user authentication module
---

# Implement user authentication module

## TASK-001 — Create user model

**Depends on:**

**Allowed paths:**
- src/auth/models.py
- tests/test_models.py

**Acceptance criteria:**
- AC-001 — User model has name and email fields with validation
- AC-002 — Duplicate email is rejected with a clear error

**Validation commands:**
- uv run pytest tests/test_models.py -q

## TASK-002 — Implement login endpoint

**Depends on:**
- TASK-001

**Allowed paths:**
- src/auth/endpoints.py
- tests/test_endpoints.py

**Acceptance criteria:**
- AC-001 — Valid credentials return a session token
- AC-002 — Invalid credentials return 401 without leaking details

**Validation commands:**
- uv run pytest tests/test_endpoints.py -q
