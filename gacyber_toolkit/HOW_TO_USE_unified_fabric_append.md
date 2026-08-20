Appendix: Unified Security Fabric usage

This short section documents the Unified Security Fabric additions and how to use them.

- New API endpoints (on branch feature/unified-security-fabric):
  - GET /api/unified_fabric/modules — list available micro-modules in the Unified Security Fabric
  - GET /api/unified_fabric/cheatsheets?module=<key>&q=<term> — search cheatsheet entries by module or keyword
  - POST /api/unified_fabric/draft_payload — generate a safe, human-review-only payload template using the AIP (LLM)

- Safety: Draft payloads are gated by ENABLE_HUMAN_IN_LOOP in config. If enabled, operator_id is required and the API will persist an audit log entry. Drafts are not executed.

Usage example (curl):

curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"module_key":"mdr","cheatsheet_id":"Active Scanning","target_context":"target.example.com","operator_id":"alice"}' \
  http://localhost:8000/api/unified_fabric/draft_payload

