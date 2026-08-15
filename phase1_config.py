#!/usr/bin/env python3
"""
JAKAL Configuration Management
Centralized settings for development and production environments
"""

import os
from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field

class Config(BaseSettings):
    """Application configuration from environment variables."""
    
    # Environment
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    
    # API Configuration
    api_port: int = Field(default=8000, validation_alias="API_PORT")
    api_host: str = Field(default="0.0.0.0", validation_alias="API_HOST")
    api_base_url: str = Field(default="http://localhost:8000", validation_alias="API_BASE_URL")
    
    # Database
    database_url: str = Field(default="data/jakal.duckdb", validation_alias="DATABASE_URL")
    
    # CORS
    allowed_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        validation_alias="ALLOWED_ORIGINS"
    )
    
    # Supabase (Cloud Database)
    supabase_url: str = Field(default="", validation_alias="SUPABASE_URL")
    supabase_anon_key: str = Field(default="", validation_alias="SUPABASE_ANON_KEY")
    supabase_service_key: str = Field(default="", validation_alias="SUPABASE_SERVICE_KEY")
    
    # Firebase (Authentication)
    firebase_project_id: str = Field(default="", validation_alias="FIREBASE_PROJECT_ID")
    firebase_api_key: str = Field(default="", validation_alias="FIREBASE_API_KEY")
    firebase_service_account_key: str = Field(default="", validation_alias="FIREBASE_SERVICE_ACCOUNT_KEY")
    
    # Google Gemini (LLM)
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-1.5-flash", validation_alias="GEMINI_MODEL")
    gemini_rate_limit: int = Field(default=60, validation_alias="GEMINI_RATE_LIMIT")  # requests/minute
    
    # IBM Quantum
    ibm_quantum_token: str = Field(default="", validation_alias="IBM_QUANTUM_TOKEN")
    ibm_quantum_instance: str = Field(default="ibm-q/open/main", validation_alias="IBM_QUANTUM_INSTANCE")
    
    # Shodan (OSINT)
    shodan_api_key: str = Field(default="", validation_alias="SHODAN_API_KEY")
    
    # GitHub
    github_token: str = Field(default="", validation_alias="GITHUB_TOKEN")
    
    # DockerHub
    dockerhub_username: str = Field(default="", validation_alias="DOCKERHUB_USERNAME")
    dockerhub_token: str = Field(default="", validation_alias="DOCKERHUB_TOKEN")
    
    # Timeout settings
    api_timeout: int = Field(default=30, validation_alias="API_TIMEOUT")
    scan_timeout: int = Field(default=3600, validation_alias="SCAN_TIMEOUT")  # 1 hour
    exploit_timeout: int = Field(default=600, validation_alias="EXPLOIT_TIMEOUT")  # 10 minutes
    
    # Rate limiting
    rate_limit_requests: int = Field(default=100, validation_alias="RATE_LIMIT_REQUESTS")
    rate_limit_window: int = Field(default=60, validation_alias="RATE_LIMIT_WINDOW")  # seconds
    
    # Security
    jwt_secret_key: str = Field(default="your-secret-key-change-in-production", validation_alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_expiration: int = Field(default=3600, validation_alias="JWT_EXPIRATION")  # seconds
    
    # Encryption
    encryption_key: str = Field(default="", validation_alias="ENCRYPTION_KEY")
    
    # Logging
    log_file: str = Field(default="logs/jakal.log", validation_alias="LOG_FILE")
    log_format: str = Field(
        default="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        validation_alias="LOG_FORMAT"
    )
    
    # Feature flags
    enable_local_llm: bool = Field(default=False, validation_alias="ENABLE_LOCAL_LLM")
    enable_quantum_simulation: bool = Field(default=True, validation_alias="ENABLE_QUANTUM_SIMULATION")
    enable_compliance_checks: bool = Field(default=True, validation_alias="ENABLE_COMPLIANCE_CHECKS")
    
    # GACyber Tool Kit
    gacyber_toolkit_path: str = Field(default="./GACyber Tool Kit", validation_alias="GACYBER_TOOLKIT_PATH")
    
    # Tool paths
    nmap_path: str = Field(default="nmap", validation_alias="NMAP_PATH")
    nikto_path: str = Field(default="nikto", validation_alias="NIKTO_PATH")
    nuclei_path: str = Field(default="nuclei", validation_alias="NUCLEI_PATH")
    sqlmap_path: str = Field(default="sqlmap", validation_alias="SQLMAP_PATH")
    gobuster_path: str = Field(default="gobuster", validation_alias="GOBUSTER_PATH")
    
    # Ollama (Local LLM)
    ollama_base_url: str = Field(default="http://localhost:11434", validation_alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama2", validation_alias="OLLAMA_MODEL")
    
    class Config:
        env_file = ".env"
        case_sensitive = False
    
    def get_allowed_origins(self) -> List[str]:
        """Parse allowed origins from string or list."""
        if isinstance(self.allowed_origins, str):
            return [o.strip() for o in self.allowed_origins.split(",")]
        return self.allowed_origins
    
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.environment.lower() == "production"
    
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.environment.lower() in ("development", "dev")
    
    def get_database_url(self) -> str:
        """Get database connection URL."""
        if self.supabase_url and self.is_production():
            # Use Supabase in production
            from urllib.parse import urljoin
            return f"postgresql://postgres@{self.supabase_url.replace('https://', '')}"
        # Use local DuckDB
        return self.database_url
    
    def get_llm_provider(self) -> str:
        """Determine which LLM provider to use."""
        if self.gemini_api_key:
            return "gemini"
        elif self.enable_local_llm:
            return "ollama"
        else:
            return "none"

def get_config() -> Config:
    """Factory function to get configuration instance."""
    return Config()

def load_env_file(env_file: str = ".env") -> None:
    """Load environment variables from .env file."""
    if os.path.exists(env_file):
        from dotenv import load_dotenv
        load_dotenv(env_file)

# Example of how to use in code:
# config = get_config()
# print(config.api_port)  # 8000
# print(config.is_production())  # False
# print(config.get_llm_provider())  # "gemini" or "ollama"
