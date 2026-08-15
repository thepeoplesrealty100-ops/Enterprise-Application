#!/usr/bin/env python3
"""Database initialization script - runs on container startup"""

import sys
import os
import logging
from pathlib import Path

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.database import DuckDBManager
from backend.monitoring import setup_logging, audit_logger

# Setup logging
logger = setup_logging()

def initialize_database():
    """Initialize database and schema"""
    logger.info("=" * 80)
    logger.info("JAKAL Database Initialization")
    logger.info("=" * 80)
    
    try:
        # Initialize database
        db_path = os.getenv("DATABASE_URL", "/app/data/jakal.duckdb")
        logger.info(f"Database path: {db_path}")
        
        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Create database manager
        db = DuckDBManager(db_path)
        logger.info("Database connection established")
        
        # Initialize schema
        db.initialize_schema()
        logger.info("✅ Database schema initialized successfully")
        
        # Verify schema
        tables = db.query("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'main'
        """)
        
        table_names = [t[0] for t in tables] if tables else []
        logger.info(f"Initialized tables ({len(table_names)}): {', '.join(table_names)}")
        
        # Log initialization event
        audit_logger.log_admin_action(
            "system",
            "database_initialization",
            f"Initialized {len(table_names)} tables in {db_path}"
        )
        
        # Insert seed data for demonstration
        seed_data()
        
        # Close connection
        db.close()
        logger.info("✅ Database initialization completed successfully")
        logger.info("=" * 80)
        return 0
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {str(e)}", exc_info=True)
        audit_logger.log_admin_action("system", "database_initialization_failed", str(e))
        return 1

def seed_data():
    """Insert seed data for testing and demonstration"""
    logger.info("Seeding demonstration data...")
    
    try:
        db = DuckDBManager(os.getenv("DATABASE_URL", "/app/data/jakal.duckdb"))
        
        # Seed scopes
        db.execute("""
            INSERT OR IGNORE INTO scopes (scope_id, client_name, target_ips, target_domains, status, expires_at)
            VALUES (?, ?, ?, ?, ?, datetime('now', '+90 days'))
        """, ("demo-scope-001", "Demo Organization", "192.168.1.0/24,10.0.0.0/8", "demo.local,internal.local", "active"))
        
        # Seed insurance policies
        db.execute("""
            INSERT OR IGNORE INTO insurance_policies (policy_number, provider, coverage_amount, expiry, status)
            VALUES (?, ?, ?, datetime('now', '+365 days'), 'active')
        """, ("POL-2024-001", "CyberSecure Insurance Co.", 2000000.00))
        
        # Seed fleet nodes
        db.execute("""
            INSERT OR IGNORE INTO fleet_nodes (node_name, region, status, cpu_usage, memory_usage, quantum_sync_status, last_ping)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """, ("node-us-east-1", "us-east-1", "online", 12.5, 34.2, "synchronized", datetime.utcnow()))
        
        logger.info("✅ Seed data inserted successfully")
        db.close()
        
    except Exception as e:
        logger.warning(f"Seed data insertion skipped (may already exist): {str(e)}")

if __name__ == "__main__":
    from datetime import datetime
    exit_code = initialize_database()
    sys.exit(exit_code)
