from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    demo_mode: bool = True
    frontend_origin: str = "http://localhost:5173"
    demo_session_secret: str = "CHANGE-ME-IN-DEVELOPMENT-ONLY"
    demo_session_minutes: int = 60
    database_url: str = "sqlite:///./aggieconnect_dev.db"
    entra_tenant_id: str = ""
    entra_api_client_id: str = ""
    entra_spa_client_id: str = ""

settings = Settings()
