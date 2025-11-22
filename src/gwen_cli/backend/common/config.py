"""Configuration management for the multi-agent system."""

from typing import Optional
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # API Configuration
    app_name: str = "Gwen Multi-Agent System"
    app_version: str = "1.0.0"
    debug: bool = True
    
    # Agent API Keys (placeholder for real authentication)
    cloudflare_api_key: Optional[str] = None
    cloudflare_email: Optional[str] = None
    azure_subscription_id: Optional[str] = None
    azure_tenant_id: Optional[str] = None
    azure_client_id: Optional[str] = None
    azure_client_secret: Optional[str] = None
    atlassian_email: Optional[str] = None
    atlassian_api_token: Optional[str] = None
    atlassian_domain: Optional[str] = None
    github_token: Optional[str] = None
    github_org: Optional[str] = None
    datadog_api_key: Optional[str] = None
    datadog_app_key: Optional[str] = None
    
    # Execution Configuration
    agent_timeout_seconds: int = 30
    max_concurrent_agents: int = 5
    enable_detailed_logging: bool = True
    
    # Dashboard Configuration
    dashboard_refresh_interval: int = 5  # seconds
    max_log_entries: int = 100
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
