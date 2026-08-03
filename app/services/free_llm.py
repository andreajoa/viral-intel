"""Small Gemini compatibility client used by manual diagnostics."""

from __future__ import annotations

from app.config import Settings, get_settings


class FreeVisionClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.api_key = api_key or self.settings.google_api_key
        self.model_name = model or self.settings.gemini_model
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY não configurada")

    def analyze(self, prompt: str, image_bytes_list: list[bytes] | None = None) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        parts = [types.Part.from_text(text=prompt)]
        parts.extend(
            types.Part.from_bytes(data=image, mime_type="image/jpeg") for image in (image_bytes_list or [])
        )
        response = client.models.generate_content(model=self.model_name, contents=parts)
        return response.text or ""
