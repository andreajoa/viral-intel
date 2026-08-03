"""Manual Gemini smoke test. Run only after configuring GOOGLE_API_KEY."""
from pathlib import Path

from app.services.free_llm import FreeVisionClient


def main() -> None:
    images = [Path("teste.jpg").read_bytes()] if Path("teste.jpg").is_file() else []
    client = FreeVisionClient()
    result = client.analyze(
        "Responda em uma frase e não invente dados: a integração multimodal está funcionando?",
        image_bytes_list=images,
    )
    print(result)


if __name__ == "__main__":
    main()
