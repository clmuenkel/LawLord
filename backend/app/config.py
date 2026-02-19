from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    firm_name: str = "Law Office"
    database_url: str = ""
    courtlistener_api_token: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
