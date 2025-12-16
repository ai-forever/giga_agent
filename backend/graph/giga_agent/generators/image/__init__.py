from __future__ import annotations

from giga_agent.generators.image.fusion_brain import FusionBrainImageGen
from giga_agent.generators.image.gigachat import GigaChatImageGen
from giga_agent.generators.image.image_gen import ImageGen
from giga_agent.generators.image.openai import OpenAIImageGen
from giga_agent.settings import settings


def load_image_gen(name: str = None) -> ImageGen:
    """Загружает и инициализирует генератор изображений по строке формата
    "provider:model".

    Примеры:
    - "openai:dall-e-3" → OpenAIImageGen(model="dall-e-3")
    - "gigachat:kandinsky-4.1:image" → GigaChatImageGen(model="kandinsky-4.1:image")
    - "fusion_brain:kandinsky" → FusionBrainImageGen(model="kandinsky")
    """
    if name is None:
        name = settings.image_gen.image_gen_name
    if name is None:
        raise ValueError(
            "Specify the image provider in the IMAGE_GEN_NAME environment variable",
        )
    provider, model = _parse_name(name)

    if provider == "openai":
        gen = OpenAIImageGen(model=model)
    elif provider == "gigachat":
        gen = GigaChatImageGen(model=model)
    elif provider == "fusion_brain":
        gen = FusionBrainImageGen(model=model)
    else:
        raise ValueError(
            f"Unknown image provider: {provider}. "
            f"Expected: openai, gigachat, fusion_brain",
        )

    return gen


def _parse_name(name: str) -> tuple[str, str]:
    if ":" not in name:
        raise ValueError("Invalid generator name format. Use 'provider:model'")
    provider, model = name.split(":", 1)
    provider = provider.strip().lower()
    model = model.strip()
    if not provider or not model:
        raise ValueError(
            "Invalid generator name format. Provider and model are required",
        )
    return provider, model
