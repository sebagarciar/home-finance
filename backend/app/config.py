from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "sqlite:///./home_finance.db"

    # Reporting currency. Hardcoded for Phase 1 — do not expose to UI.
    base_currency: str = "CLP"

    # FX — provider options, all behind FxProvider:
    # "free" (default) = CurrencyApiProvider: fawazahmed0/currency-api via CDN.
    #   No key, fast, daily snapshots incl. weekends, covers CLP.
    # "mindicador" = FreeCompositeFxProvider: mindicador.cl (official BCCh
    #   fixings) for anything<->CLP + frankfurter.app (ECB) for the rest. No
    #   key, but mindicador.cl is slow and flaky (measured 13 s+ responses and
    #   intermittent 500s/rate-limiting).
    # "exchangerate_host" requires a paid FX_API_KEY since late 2024.
    fx_provider: str = "free"
    fx_api_base: str = "https://api.exchangerate.host"
    fx_api_key: str | None = None
    frankfurter_api_base: str = "https://api.frankfurter.app"
    mindicador_api_base: str = "https://mindicador.cl/api"

    # Prices (holdings valuation). yfinance is free and requires no key.
    price_provider: str = "yfinance"
    # Price cache strategy: daily. The price_cache table is keyed on
    # (ticker, date) — the first read of a ticker on a given calendar day
    # fetches from the provider and writes a row; every subsequent read that
    # day returns the cached row. Set `price_cache_enabled=false` to refetch
    # on every read instead (useful for debugging).
    price_cache_enabled: bool = True

    # Categorization
    ollama_enabled: bool = True
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    anthropic_enabled: bool = False
    anthropic_api_key: str | None = None

    # Email ingest (Santander ES transaction-notification emails).
    # Read over IMAP with a Gmail *app password* (requires 2FA on the account).
    # Fetch is read-only: messages are never marked seen or deleted, so the
    # import dedup hash — not IMAP flags — owns idempotency. Leaving creds unset
    # disables the feature (the /import/email/sync endpoint returns 503).
    gmail_imap_host: str = "imap.gmail.com"
    gmail_user: str | None = None
    gmail_app_password: str | None = None
    # Sender to filter on (Santander ES notification address).
    santander_email_sender: str = "SantanderInforma@emailing.bancosantander-mail.es"
    # Default Account that email rows post to (the Santander ES checking account).
    santander_email_account_id: int | None = None

    # Auth — change these via .env in production
    app_username: str = "home"
    app_password: str = "home_finance"
    secret_key: str = "dev-secret-change-in-production"
    token_expire_days: int = 7

    # Server
    cors_origins: list[str] = ["http://localhost:5173"]

    # Import: reject statement uploads larger than this (bytes). Bank statements
    # are tiny; this guards against memory exhaustion from a runaway upload.
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB


@lru_cache
def get_settings() -> Settings:
    return Settings()
