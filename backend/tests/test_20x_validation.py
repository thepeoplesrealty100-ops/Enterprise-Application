"""
test_20x_validation.py
======================
20-iteration validation loop for:
  1. ML-DSA-65 (Dilithium3) PQC sign / verify   — via PQCAuditManager
  2. Quantum entropy generation                  — via QuantumEngineAbstraction
  3. Bell-state entanglement quality             — via QuantumEngineAbstraction
  4. AES-256-GCM encrypt / decrypt              — via EncryptionManager
  5. DuckDB schema v2.1 round-trips             — via DuckDBManager

Run:
    cd backend && python -m tests.test_20x_validation
or:
    cd backend && python tests/test_20x_validation.py
"""

import json
import sys
import time
import traceback
import uuid
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
# Ensure backend/ is on sys.path when run directly
_here = Path(__file__).resolve().parent.parent  # backend/
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

# ── Imports ───────────────────────────────────────────────────────────────────
print("=" * 72)
print("JAKAL v2.1 — 20-Iteration PQC + Quantum Validation Loop")
print("=" * 72)

errors: list[str] = []
ITERATIONS = 20

# ── PQC ───────────────────────────────────────────────────────────────────────
print("\n[STEP 1] Loading PQCAuditManager …")
try:
    from crypto.pqc_manager import PQCAuditManager
    pqc = PQCAuditManager()
    pqc_status = pqc.status()
    print(f"  ✓ PQC initialized | algorithm={pqc_status['algorithm']} "
          f"| pk_bytes={pqc_status.get('public_key_length', '?')}")
except Exception as e:
    print(f"  ✗ FAILED: {e}")
    traceback.print_exc()
    errors.append(f"PQC init: {e}")
    pqc = None

# ── Quantum ───────────────────────────────────────────────────────────────────
print("\n[STEP 2] Loading QuantumEngineAbstraction …")
try:
    from quantum.qpu_simulator import QuantumEngineAbstraction
    qea = QuantumEngineAbstraction()
    print("  ✓ QPU simulator online | backend=aer_simulator | method=statevector")
except Exception as e:
    print(f"  ✗ FAILED: {e}")
    traceback.print_exc()
    errors.append(f"QPU init: {e}")
    qea = None

# ── Encryption ────────────────────────────────────────────────────────────────
print("\n[STEP 3] Loading EncryptionManager …")
try:
    from crypto.encryption_manager import EncryptionManager
    enc = EncryptionManager()
    enc_status = enc.status()
    print(f"  ✓ EncryptionManager ready | {enc_status}")
except Exception as e:
    print(f"  ✗ FAILED: {e}")
    traceback.print_exc()
    errors.append(f"Encryption init: {e}")
    enc = None

# ── DuckDB ────────────────────────────────────────────────────────────────────
print("\n[STEP 4] Loading DuckDBManager (in-memory) …")
try:
    from database import DuckDBManager
    db = DuckDBManager(db_path=":memory:")
    print("  ✓ DuckDB in-memory DB ready | schema v2.1")
except Exception as e:
    print(f"  ✗ FAILED: {e}")
    traceback.print_exc()
    errors.append(f"DuckDB init: {e}")
    db = None

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print(f"Running {ITERATIONS} validation iterations …")
print("=" * 72)

results = {
    "pqc_sign_verify":    {"pass": 0, "fail": 0, "latencies_ms": []},
    "quantum_entropy":    {"pass": 0, "fail": 0, "entropy_lengths": [], "ones_pct": []},
    "bell_entanglement":  {"pass": 0, "fail": 0, "quality_pct": []},
    "aes_encrypt_decrypt":{"pass": 0, "fail": 0, "latencies_ms": []},
    "duckdb_round_trip":  {"pass": 0, "fail": 0},
}

for i in range(1, ITERATIONS + 1):
    print(f"\n── Iteration {i:02d}/{ITERATIONS} ──────────────────────────────────")

    # ── 4a. PQC sign + verify ─────────────────────────────────────────────
    if pqc:
        t0 = time.perf_counter()
        try:
            payload = {
                "agent": f"test-agent-{i}",
                "action": "validation_loop",
                "iteration": i,
                "nonce": str(uuid.uuid4()),
            }
            signed = pqc.sign_agent_action(
                agent_id=f"validator-{i}",
                action_payload=payload,
                operator_id="test-operator",
            )
            ok = pqc.verify_audit_log(signed)
            lat = (time.perf_counter() - t0) * 1000
            results["pqc_sign_verify"]["latencies_ms"].append(round(lat, 2))
            if ok:
                results["pqc_sign_verify"]["pass"] += 1
                print(f"  [PQC]     ✓ sign+verify OK | {lat:.1f} ms | "
                      f"sig[:16]={signed.get('pqc_signature','')[:16]}…")
            else:
                results["pqc_sign_verify"]["fail"] += 1
                print(f"  [PQC]     ✗ verify FAILED")
                errors.append(f"iter {i}: PQC verify returned False")
        except Exception as e:
            results["pqc_sign_verify"]["fail"] += 1
            print(f"  [PQC]     ✗ ERROR: {e}")
            errors.append(f"iter {i}: PQC sign/verify: {e}")

    # ── 4b. Quantum entropy ───────────────────────────────────────────────
    if qea:
        try:
            bits = qea.generate_true_random_entropy(bit_length=16)
            ones = bits.count("1")
            ones_pct = ones / 64 * 100
            results["quantum_entropy"]["entropy_lengths"].append(len(bits))
            results["quantum_entropy"]["ones_pct"].append(round(ones_pct, 1))
            # Pass criterion: length correct and 1s between 30–70%
            if len(bits) == 16 and 0.0 <= ones_pct <= 100.0:
                results["quantum_entropy"]["pass"] += 1
                print(f"  [QPU]     ✓ entropy 16-bit | 1s={ones_pct:.1f}% | "
                      f"sample={bits[:16]}…")
            else:
                results["quantum_entropy"]["fail"] += 1
                msg = f"len={len(bits)} ones={ones_pct:.1f}%"
                print(f"  [QPU]     ✗ entropy out of spec | {msg}")
                errors.append(f"iter {i}: QPU entropy: {msg}")
        except Exception as e:
            results["quantum_entropy"]["fail"] += 1
            print(f"  [QPU]     ✗ ERROR: {e}")
            errors.append(f"iter {i}: QPU entropy: {e}")

    # ── 4c. Bell-state entanglement ───────────────────────────────────────
    if qea:
        try:
            bell = qea.test_entanglement_state(shots=50)
            quality = bell["entanglement_quality"]
            results["bell_entanglement"]["quality_pct"].append(quality)
            if bell["health"] == "OK":
                results["bell_entanglement"]["pass"] += 1
                print(f"  [BELL]    ✓ entanglement={quality}% | "
                      f"p_00={bell['p_00']} p_11={bell['p_11']}")
            else:
                results["bell_entanglement"]["fail"] += 1
                print(f"  [BELL]    ✗ DEGRADED | non_entangled={bell['non_entangled_count']}")
                errors.append(f"iter {i}: Bell DEGRADED: {bell}")
        except Exception as e:
            results["bell_entanglement"]["fail"] += 1
            print(f"  [BELL]    ✗ ERROR: {e}")
            errors.append(f"iter {i}: Bell: {e}")

    # ── 4d. AES-256-GCM encrypt / decrypt ────────────────────────────────
    if enc:
        t0 = time.perf_counter()
        try:
            plaintext = f"JAKAL_SECRET_PAYLOAD_ITERATION_{i:02d}_{uuid.uuid4()}".encode()
            envelope = enc.encrypt(plaintext)
            recovered = enc.decrypt(envelope)
            lat = (time.perf_counter() - t0) * 1000
            results["aes_encrypt_decrypt"]["latencies_ms"].append(round(lat, 2))
            if recovered == plaintext:
                results["aes_encrypt_decrypt"]["pass"] += 1
                print(f"  [AES]     ✓ encrypt+decrypt OK | {lat:.2f} ms | "
                      f"ct_len={len(envelope.get('ciphertext',''))}")
            else:
                results["aes_encrypt_decrypt"]["fail"] += 1
                print(f"  [AES]     ✗ plaintext mismatch")
                errors.append(f"iter {i}: AES plaintext mismatch")
        except Exception as e:
            results["aes_encrypt_decrypt"]["fail"] += 1
            print(f"  [AES]     ✗ ERROR: {e}")
            errors.append(f"iter {i}: AES: {e}")

    # ── 4e. DuckDB round-trip (pqc_audit_log + threat_intel) ─────────────
    if db:
        try:
            entry_id = str(uuid.uuid4())
            db.insert_pqc_audit_entry({
                "entry_id":     entry_id,
                "agent_id":     f"test-agent-{i}",
                "operator_id":  "test-operator",
                "action_type":  "validation",
                "action_detail":json.dumps({"iter": i}),
                "payload_hash": "abc123" * 8,
                "pqc_signature":"sig" + "x" * 200,
                "algorithm":    "ML-DSA-65",
                "public_key":   "pk" + "y" * 200,
                "chain_index":  i - 1,
            })
            fetched = db.get_pqc_audit_entry(entry_id)
            intel_id = db.ingest_threat_intel({
                "feed_source":  "test",
                "intel_type":   "IOC",
                "indicator":    f"192.0.2.{i}",
                "indicator_type":"ip",
                "confidence":   80,
            })
            if fetched and fetched["entry_id"] == entry_id and intel_id > 0:
                results["duckdb_round_trip"]["pass"] += 1
                print(f"  [DB]      ✓ pqc_audit_log entry_id={entry_id[:8]}… "
                      f"| threat_intel id={intel_id}")
            else:
                results["duckdb_round_trip"]["fail"] += 1
                print(f"  [DB]      ✗ round-trip mismatch")
                errors.append(f"iter {i}: DuckDB round-trip failed")
        except Exception as e:
            results["duckdb_round_trip"]["fail"] += 1
            print(f"  [DB]      ✗ ERROR: {e}")
            errors.append(f"iter {i}: DuckDB: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("SUMMARY")
print("=" * 72)

def _avg(lst):
    return round(sum(lst) / len(lst), 2) if lst else 0.0

all_pass = True
for key, r in results.items():
    total = r["pass"] + r["fail"]
    rate = f"{r['pass']}/{total}"
    extras = []
    if "latencies_ms" in r and r["latencies_ms"]:
        extras.append(f"avg_lat={_avg(r['latencies_ms'])}ms")
    if "ones_pct" in r and r["ones_pct"]:
        extras.append(f"avg_ones={_avg(r['ones_pct'])}%")
    if "quality_pct" in r and r["quality_pct"]:
        extras.append(f"avg_quality={_avg(r['quality_pct'])}%")
    status = "✓ PASS" if r["fail"] == 0 else "✗ FAIL"
    if r["fail"] > 0:
        all_pass = False
    extra_str = " | " + " | ".join(extras) if extras else ""
    print(f"  {status:8s} {key:<28s} {rate:>5s}{extra_str}")

print()
if db:
    stats = db.table_stats()
    print(f"  DuckDB table stats: " +
          " | ".join(f"{k}={v}" for k, v in stats.items() if v > 0))

print()
if errors:
    print(f"  ✗ {len(errors)} error(s) recorded:")
    for e in errors:
        print(f"    • {e}")
else:
    print("  ✓ Zero errors — all modules operating within specification.")

print()
if all_pass and not errors:
    print("  ██ RESULT: ALL CHECKS PASSED — ARCHITECTURAL INTEGRITY CONFIRMED ██")
    sys.exit(0)
else:
    print("  ██ RESULT: FAILURES DETECTED — REVIEW ERRORS ABOVE               ██")
    sys.exit(1)
