"""List Gemini models available to the configured API key."""
from app.config import get_settings


def main() -> None:
    from google import genai

    settings = get_settings()
    if not settings.google_api_key:
        raise SystemExit("Configure GOOGLE_API_KEY no arquivo .env")
    client = genai.Client(api_key=settings.google_api_key)
    print("=== MODELOS GEMINI DISPONÍVEIS ===")
    for model in client.models.list():
        print(" -", getattr(model, "name", model))


if __name__ == "__main__":
    main()
