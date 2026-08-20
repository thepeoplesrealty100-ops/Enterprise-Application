@@
 app = FastAPI(title="JAKAL Backend", version="1.2")
@@
 db = DuckDBManager()
 orchestrator = AgentOrchestrator(config)
 quantum = QuantumEngine(config)
@@
 vm_orchestrator = VMOrchestrator(db)
 compliance_axiom = ComplianceAxiom(db)
 edr_mdr = EdrMdrEngine(db)
+# Unified Security Fabric router
+try:
+    from unified_fabric import api as unified_fabric_api
+    app.include_router(unified_fabric_api.get_router(db, orchestrator, config), prefix="/api/unified_fabric")
+except Exception as e:
+    logger.warning("Unified Fabric router not available: %s", e)
@@
 if __name__ == "__main__":
     uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
