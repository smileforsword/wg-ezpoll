from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="YOURVPN_",
        extra="ignore",
    )

    app_name: str = "WirePortal"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./wireportal.dev.sqlite3"
    public_base_url: str = "http://localhost:5566"
    wg_agent_socket_path: str = "/run/yourvpn/wg-agent.sock"
    artifacts_dir: Path = Field(default=Path(".m1-out/artifacts"))
    build_tmp_dir: Path = Field(default=Path(".m1-out/build-tmp"))
    session_cookie_name: str = "wireportal_session"
    session_cookie_secure: bool = False
    session_ttl_minutes: int = 480
    csrf_header_name: str = "x-csrf-token"
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_minutes: int = 15
    admin_ip_whitelist: str = ""
    password_setup_token_ttl_hours: int = 72
    smtp_host: str = ""
    smtp_port: int = 25
    smtp_from: str = ""
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False
    smtp_timeout_seconds: int = 10
    vpn_cidr: str = "10.77.0.0/20"
    vpn_server_ip: str = "10.77.0.1"
    install_package_download_window_minutes: int = 120
    install_package_max_download_attempts: int = 5
    fake_builder_enabled: bool = True
    installer_builder_mode: str = "auto"
    wireguard_msi_path: str = ""
    wireguard_msi_sha256: str = "6DAA5D37A9E2950DFB8C48B95AB8E562CB2BAD1C785D020F38F97BEA4C6A5566"
    wireguard_installer_version: str = "1.1"
    wireguard_server_public_key: str = ""
    wireguard_endpoint: str = ""
    wireguard_persistent_keepalive_seconds: int = 25
    wireguard_tunnel_name_prefix: str = "WirePortal"
    wg_interface: str = "wg0"
    nft_table_name: str = "yourvpn"
    outbound_interface: str = "eth0"
    enable_masquerade: bool = True
    wg_agent_dry_run: bool = False
    master_key_file: str = ""

    def admin_ip_whitelist_cidrs(self) -> list[str]:
        return [item.strip() for item in self.admin_ip_whitelist.split(",") if item.strip()]

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)


@lru_cache(maxsize=1)
def load_settings() -> AppSettings:
    return AppSettings()


def clear_settings_cache() -> None:
    load_settings.cache_clear()
