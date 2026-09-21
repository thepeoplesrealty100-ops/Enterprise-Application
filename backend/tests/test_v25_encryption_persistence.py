"""
test_v25_encryption_persistence.py — tests for the v2.5 encryption-key
persistence fix (crypto/encryption_manager.py + database.py).

Background: EncryptionManager used to generate a fresh AES/ChaCha session
key in memory on every process start and never persist it anywhere, so
anything encrypted via encrypt_report() became permanently unreadable the
instant the process restarted. Separately, database.py's encryption_keys
table (register/rotate/revoke/list) had zero callers anywhere in the app,
so GET/POST /crypto/keys operated on a table that was always empty. This
suite exercises the fix: KEK-wrapped session keys are persisted to
encryption_keys and rehydrated on the next EncryptionManager(db=...) call
when JAKAL_MASTER_KEY is set, and the rotate/revoke lifecycle keeps the
in-memory store and the DB in sync.

Run: cd backend && python -m pytest tests/test_v25_encryption_persistence.py -q
"""
import os
import sys
import uuid
from pathlib import Path

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from database import DuckDBManager
from crypto.encryption_manager import EncryptionManager

_ENV_VAR = "JAKAL_MASTER_KEY"


class _MasterKeyEnv:
    """Context manager: set/clear JAKAL_MASTER_KEY for one test, restoring
    whatever was there before on exit (there shouldn't be anything in this
    sandbox, but be a good citizen about the process environment)."""

    def __init__(self, value):
        self.value = value
        self._had_prev = _ENV_VAR in os.environ
        self._prev = os.environ.get(_ENV_VAR)

    def __enter__(self):
        if self.value is None:
            os.environ.pop(_ENV_VAR, None)
        else:
            os.environ[_ENV_VAR] = self.value
        return self

    def __exit__(self, *exc):
        if self._had_prev:
            os.environ[_ENV_VAR] = self._prev
        else:
            os.environ.pop(_ENV_VAR, None)


# ── Standalone (no db) — must behave exactly as before this fix ──────────

def test_standalone_manager_without_db_still_encrypts_and_decrypts():
    enc = EncryptionManager()  # no db arg, matches tests/test_20x_validation.py's usage
    envelope = enc.encrypt("hello world")
    assert enc.decrypt(envelope) == b"hello world"
    assert enc.status()["key_persistence"] == "in-memory-only"


# ── Core fix: keys survive a simulated process restart ────────────────────

def test_keys_persist_across_manager_restarts_with_master_key():
    db = DuckDBManager(db_path=":memory:")
    with _MasterKeyEnv("a-fixed-test-master-secret"):
        enc1 = EncryptionManager(db=db)
        envelope = enc1.encrypt("classified pentest finding")
        first_key_id = enc1._aes_key.key_id

        # Simulate a process restart: brand-new EncryptionManager instance,
        # same DB, same master key.
        enc2 = EncryptionManager(db=db)
        assert enc2._aes_key.key_id == first_key_id  # rehydrated, not regenerated

        # The envelope from BEFORE the "restart" must still decrypt.
        assert enc2.decrypt(envelope) == b"classified pentest finding"


def test_keys_are_recorded_in_encryption_keys_table():
    db = DuckDBManager(db_path=":memory:")
    with _MasterKeyEnv("another-fixed-secret"):
        enc = EncryptionManager(db=db)
        rows = db.list_encryption_key_material(status="active")
        key_ids = {r["key_id"] for r in rows}
        assert enc._aes_key.key_id in key_ids
        assert enc._chacha_key.key_id in key_ids
        # Never the raw key bytes -- only a wrapped (encrypted) blob.
        for r in rows:
            assert r["wrapped_key"] is not None
            assert r["wrapped_key"] != ""


def test_wrapped_key_material_never_contains_raw_key_bytes_as_plain_text():
    db = DuckDBManager(db_path=":memory:")
    with _MasterKeyEnv("secret-for-plaintext-check"):
        enc = EncryptionManager(db=db)
        raw_hex_fragment = enc._aes_key.key_bytes.hex()[:16]
        rows = db.list_encryption_key_material(status="active")
        for r in rows:
            assert raw_hex_fragment not in (r["wrapped_key"] or "")


def test_without_master_key_env_boots_fine_but_does_not_claim_persistence():
    db = DuckDBManager(db_path=":memory:")
    with _MasterKeyEnv(None):
        enc = EncryptionManager(db=db)
        status = enc.status()
        assert status["key_persistence"] == "db-backed"  # a db IS wired...
        assert "ephemeral" in status["kek_source"]        # ...but the KEK itself is not durable
        # Still fully functional this run.
        env = enc.encrypt("still works without a fixed master key")
        assert enc.decrypt(env) == b"still works without a fixed master key"


# ── Rotation: old key stays decryptable, new key is the one used going forward ─

def test_rotation_keeps_old_key_decryptable_and_persists_new_one():
    db = DuckDBManager(db_path=":memory:")
    with _MasterKeyEnv("rotation-test-secret"):
        enc = EncryptionManager(db=db)
        old_key_id = enc._aes_key.key_id
        old_envelope = enc.encrypt("pre-rotation payload")

        new_key_info = enc.generate_new_session_key(algorithm="AES-256-GCM")
        assert new_key_info["key_id"] != old_key_id
        assert enc._aes_key.key_id == new_key_info["key_id"]

        new_envelope = enc.encrypt("post-rotation payload")
        assert new_envelope["key_id"] == new_key_info["key_id"]

        # Both old and new envelopes still decrypt correctly.
        assert enc.decrypt(old_envelope) == b"pre-rotation payload"
        assert enc.decrypt(new_envelope) == b"post-rotation payload"

        rows = {r["key_id"]: r for r in db.list_encryption_keys(status=None)}
        assert rows[old_key_id]["status"] == "rotated"
        assert rows[new_key_info["key_id"]]["status"] == "active"


# ── Revocation: strictly more destructive than rotation ──────────────────

def test_revoking_the_active_key_breaks_old_decrypt_and_replaces_it():
    db = DuckDBManager(db_path=":memory:")
    with _MasterKeyEnv("revocation-test-secret"):
        enc = EncryptionManager(db=db)
        compromised_key_id = enc._aes_key.key_id
        old_envelope = enc.encrypt("payload under the soon-to-be-revoked key")

        result = enc.revoke_session_key(compromised_key_id)
        assert result is True
        assert enc._aes_key.key_id != compromised_key_id  # replaced automatically

        # Old envelope is now permanently unreadable -- that's the point of revoke.
        try:
            enc.decrypt(old_envelope)
            assert False, "expected KeyError decrypting under a revoked key"
        except KeyError:
            pass

        # But the manager keeps working for new data.
        fresh = enc.encrypt("payload under the new key")
        assert enc.decrypt(fresh) == b"payload under the new key"

        rows = {r["key_id"]: r for r in db.list_encryption_keys(status=None)}
        assert rows[compromised_key_id]["status"] == "revoked"


def test_revoke_unknown_key_id_returns_false():
    db = DuckDBManager(db_path=":memory:")
    with _MasterKeyEnv("unknown-key-test-secret"):
        enc = EncryptionManager(db=db)
        assert enc.revoke_session_key("totally-unknown-key-id") is False


# ── list_keys() now reflects real, persisted state ────────────────────────

def test_list_keys_prefers_db_and_shows_full_lifecycle():
    db = DuckDBManager(db_path=":memory:")
    with _MasterKeyEnv("list-keys-test-secret"):
        enc = EncryptionManager(db=db)
        enc.generate_new_session_key(algorithm="AES-256-GCM")  # old -> rotated
        keys = enc.list_keys()
        statuses = {k["status"] for k in keys}
        assert "active" in statuses
        assert "rotated" in statuses
        # No wrapped key material leaks through the listing.
        for k in keys:
            assert "wrapped_key" not in k
            assert "key_bytes" not in k


# ── database.py: list_encryption_keys(status=None) ────────────────────────

def test_list_encryption_keys_status_none_returns_all_lifecycle_states():
    db = DuckDBManager(db_path=":memory:")
    db.register_encryption_key({"key_id": "a1", "algorithm": "AES-256-GCM",
                                 "key_purpose": "session", "operator_id": "op1"})
    db.register_encryption_key({"key_id": "a2", "algorithm": "AES-256-GCM",
                                 "key_purpose": "session", "operator_id": "op1"})
    db.rotate_encryption_key("a1")
    only_active = db.list_encryption_keys(status="active")
    assert {r["key_id"] for r in only_active} == {"a2"}
    everything = db.list_encryption_keys(status=None)
    assert {r["key_id"] for r in everything} == {"a1", "a2"}


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn(); passed += 1; print(f"  PASS  {fn.__name__}")
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {e}"); traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
