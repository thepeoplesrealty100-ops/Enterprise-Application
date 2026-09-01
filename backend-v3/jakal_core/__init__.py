"""JAKAL Core v3 — production persistence + service layer.

A clean-room rebuild of the JAKAL backend's data and service tier addressing
the P0 findings from the architecture teardown:

  * GAP-01  real identity/RBAC gate (auth.py) — operator_id is derived from a
            verified token, never from the request body.
  * GAP-02  async SQLAlchemy 2.0 over a pooled engine (db.py); one
            session-per-request dependency replaces 15 module-level singletons.
            Runs on Postgres in production and SQLite (aiosqlite) for tests —
            identical ORM code, no engine-specific SQL.
  * GAP-03  identity/UUID primary keys (no shared sequence state) remove the
            duplicate-key collision; rotate/revoke return real rowcounts.
  * GAP-05  hybrid ML-DSA-65 + Ed25519 signing with per-signature algorithm
            agility (crypto/pqc.py).
"""

__version__ = "3.0.0"
