#!/usr/bin/env python3
"""Quick validation of Backend Batch 1 files"""
import sys
sys.path.insert(0, '/app/backend')

try:
    print("✓ Testing core/enforcement.py imports...")
    from core.enforcement import AuditedHostIsolation, AuditedHostIsolationEngine
    print("  ✓ AuditedHostIsolation loaded")
    print("  ✓ AuditedHostIsolationEngine loaded")
    
    print("✓ Testing core/webhook_dispatcher.py imports...")
    from core.webhook_dispatcher import WebhookDispatcher
    print("  ✓ WebhookDispatcher loaded")
    
    print("✓ Testing core/audit_logger.py imports...")
    from core.audit_logger import AuditLogger, AuditEvent
    print("  ✓ AuditLogger loaded")
    print("  ✓ AuditEvent loaded")
    
    print("✓ Testing routers/resonance.py imports...")
    from routers.resonance import router as resonance_router
    print("  ✓ resonance_router loaded")
    
    print("✓ Testing routers/scripts.py imports...")
    from routers.scripts import router as scripts_router
    print("  ✓ scripts_router loaded")
    
    print("\n✅ All imports successful!")
    sys.exit(0)
    
except Exception as e:
    print(f"\n❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
