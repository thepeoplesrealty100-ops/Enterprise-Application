#!/usr/bin/env python3
"""JAKAL Configuration Management"""
import os
from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field

class Config(BaseSettings):
    """Application configuration."""
    
    # Environment
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    
    # API
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
    
    # Cloud Services
    supabase_url: str = Field(default="", validation_alias="SUPABASE_URL")
    supabase_anon_key: str = Field(default="", validation_alias="SUPABASE_ANON_KEY")
    firebase_project_id: str = Field(default="", validation_alias="FIREBASE_PROJECT_ID")
    firebase_api_key: str = Field(default="", validation_alias="FIREBASE_API_KEY")
    
    # LLM & Quantum
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-1.5-flash", validation_alias="GEMINI_MODEL")
    ibm_quantum_token: str = Field(default="", validation_alias="IBM_QUANTUM_TOKEN")
    ibm_quantum_instance: str = Field(default="ibm-q/open/main", validation_alias="IBM_QUANTUM_INSTANCE")
    
    # OSINT
    shodan_api_key: str = Field(default="", validation_alias="SHODAN_API_KEY")
    github_token: str = Field(default="", validation_alias="GITHUB_TOKEN")
    
    # Timeouts
    api_timeout: int = Field(default=30, validation_alias="API_TIMEOUT")
    scan_timeout: int = Field(default=3600, validation_alias="SCAN_TIMEOUT")
    exploit_timeout: int = Field(default=600, validation_alias="EXPLOIT_TIMEOUT")
    
    # Security
    jwt_secret_key: str = Field(default="your-secret-key-change-in-production", validation_alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    
    # Logging
    log_file: str = Field(default="logs/jakal.log", validation_alias="LOG_FILE")
    
    # Features
    enable_local_llm: bool = Field(default=False, validation_alias="ENABLE_LOCAL_LLM")
    enable_quantum_simulation: bool = Field(default=True, validation_alias="ENABLE_QUANTUM_SIMULATION")
    enable_compliance_checks: bool = Field(default=True, validation_alias="ENABLE_COMPLIANCE_CHECKS")
    
    # Tools
    ollama_base_url: str = Field(default="http://localhost:11434", validation_alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama2", validation_alias="OLLAMA_MODEL")
    
    class Config:
        env_file = ".env"
        case_sensitive = False
    
    def is_production(self) -> bool:
        return self.environment.lower() == "production"
    
    def is_development(self) -> bool:
        return self.environment.lower() in ("development", "dev")
    
    def get_llm_provider(self) -> str:
        if self.gemini_api_key:
            return "gemini"
        elif self.enable_local_llm:
            return "ollama"
        else:
            return "none"

def get_config() -> Config:
    """Get configuration instance."""
    return Config()
