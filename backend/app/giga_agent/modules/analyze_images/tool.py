from langchain_core.tools import tool


@tool
async def ask_about_image(image_path: str, question: str):
    """Анализирует изображение. Используй если нужно узнать информацию по изображению
    Используй этот инструмент итеративно, если в ответе недостаточно информации, сделай уточняющий запрос!

    Args:
        image_path: Путь до изображения (в директориях /runs/, /files/)
        question: Запрос для анализа изображения. Детально пропиши все, что ты хочешь узнать от изображения. Это полноценный промпт к V-LLM, поэтому используй все мощности нейросетей!

    """
    llm = load_llm().with_config(tags=["nostream"])

    image_path = image_path.removeprefix("attachment:")
    if not image_path.startswith("/runs/") and not image_path.startswith("/files/"):
        return "image_id должен хранить путь до него"
    client = get_client(url=settings.internal.langgraph_api_url)
    try:
        data = (await client.store.get_item(("attachments",), key=image_path))["value"]
    except HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Изображение c ID {image_path} не найдено"
        raise e
    if not data.get("image_id") and not data.get("image_path"):
        return "Вложение не возможно проанализировать с помощью анализа изображений!"
    if is_llm_image_inline():
        return (
            (
                await llm.ainvoke(
                    [
                        HumanMessage(
                            content=question,
                            additional_kwargs={"attachments": [data.get("image_id")]},
                        ),
                    ],
                )
            ).content
            + "\nИспользуй этот инструмент итеративно, если в ответе недостаточно информации, сделай уточняющий запрос!"
        )
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.internal.front_base_url}{data['image_path']}",
        )
        img_content = base64.b64encode(resp.content).decode()
    return (
        (
            await llm.ainvoke(
                [
                    HumanMessage(
                        content=[
                            {
                                "type": "text",
                                "text": question,
                            },
                            {
                                "type": "image",
                                "source_type": "base64",
                                "data": img_content,
                                "mime_type": "image/png",
                            },
                        ],
                    ),
                ],
            )
        ).content
        + "\nИспользуй этот инструмент итеративно, если в ответе недостаточно информации, сделай уточняющий запрос!"
    )
