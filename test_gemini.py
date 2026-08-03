"""Manual text-only Gemini smoke test."""
from app.services.free_llm import FreeVisionClient


if __name__ == "__main__":
    client = FreeVisionClient()
    print("MODELO:", client.model_name)
    print(client.analyze("Responda em uma frase: esta chamada está funcionando?"))
