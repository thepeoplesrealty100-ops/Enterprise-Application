# JAKAL Backend Configuration Management
import os
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

class Config:
    """Base configuration for JAKAL backend."""
    
    # Database Configuration
    DUCKDB_PATH = os.getenv('DUCKDB_PATH', 'jakal.duckdb')
    SUPABASE_URL = os.getenv('SUPABASE_URL', '')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY', '')
    
    # API Configuration
    API_HOST = os.getenv('API_HOST', '0.0.0.0')
    API_PORT = int(os.getenv('API_PORT', '8000'))
    API_WORKERS = int(os.getenv('API_WORKERS', '4'))
    
    # LLM Configuration
    CLAUDE_API_KEY = os.getenv('CLAUDE_API_KEY', '')
    CLAUDE_MODEL = os.getenv('CLAUDE_MODEL', 'claude-3-5-sonnet-20241022')
    OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
    OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama2')
    LLM_ENGINE = os.getenv('LLM_ENGINE', 'claude')  # 'claude' or 'ollama'
    
    # Quantum Configuration
    IBM_QUANTUM_TOKEN = os.getenv('IBM_QUANTUM_TOKEN', '')
    IBM_QUANTUM_CHANNEL = os.getenv('IBM_QUANTUM_CHANNEL', 'ibm_quantum')
    IBM_QUANTUM_INSTANCE = os.getenv('IBM_QUANTUM_INSTANCE', 'ibm-q/open/main')
    QISKIT_AER_BACKEND = os.getenv('QISKIT_AER_BACKEND', 'qasm_simulator')
    
    # Security Tools Configuration
    NMAP_TIMEOUT = int(os.getenv('NMAP_TIMEOUT', '300'))
    NUCLEI_TIMEOUT = int(os.getenv('NUCLEI_TIMEOUT', '300'))
    NUCLEI_TEMPLATES_PATH = os.getenv('NUCLEI_TEMPLATES_PATH', '/opt/nuclei-templates')
    
    # Firebase Configuration (Optional)
    FIREBASE_CONFIG = os.getenv('FIREBASE_CONFIG', '')
    
    # Logging Configuration
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'jakal.log')
    
    # Security
    ENABLE_HUMAN_IN_LOOP = os.getenv('ENABLE_HUMAN_IN_LOOP', 'True').lower() == 'true'
    MAX_CONCURRENT_AGENTS = int(os.getenv('MAX_CONCURRENT_AGENTS', '5'))
    EXPLOITATION_TIMEOUT = int(os.getenv('EXPLOITATION_TIMEOUT', '600'))
    # v2.5: root secret for encryption_manager.py's KEK — wraps persisted
    # session keys in encryption_keys. Unset means keys are still generated
    # and persisted, but wrapped under a per-process random key instead, so
    # they're unrecoverable after a restart. See that module's docstring.
    JAKAL_MASTER_KEY = os.getenv('JAKAL_MASTER_KEY', '')
    
    # CORS
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', 'http://localhost:3000,http://localhost:8080').split(',')
    
    @classmethod
    def validate(cls):
        """Validate critical configuration at startup."""
        if cls.LLM_ENGINE == 'claude' and not cls.CLAUDE_API_KEY:
            raise ValueError('CLAUDE_API_KEY required when using Claude LLM engine')
        if cls.IBM_QUANTUM_TOKEN and not cls.IBM_QUANTUM_CHANNEL:
            raise ValueError('IBM_QUANTUM_CHANNEL required when IBM_QUANTUM_TOKEN is set')
        return True

class DevelopmentConfig(Config):
    """Development environment configuration."""
    DEBUG = True
    TESTING = False

class ProductionConfig(Config):
    """Production environment configuration."""
    DEBUG = False
    TESTING = False

class TestingConfig(Config):
    """Testing environment configuration."""
    DEBUG = True
    TESTING = True
    DUCKDB_PATH = ':memory:'  # Use in-memory database for tests

def get_config() -> Config:
    """Get appropriate config based on environment."""
    env = os.getenv('ENVIRONMENT', 'development').lower()
    if env == 'production':
        return ProductionConfig()
    elif env == 'testing':
        return TestingConfig()
    else:
        return DevelopmentConfig()
