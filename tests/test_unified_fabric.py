---
# Unified Security Fabric tests
---
import json
from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


def test_list_modules():
    r = client.get("/api/unified_fabric/modules")
    assert r.status_code == 200
    data = r.json()
    assert 'modules' in data

