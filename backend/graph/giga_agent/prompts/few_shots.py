import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

FEW_SHOTS_ORIGINAL = [
    HumanMessage(
        content="""<task>Сгенерируй изображение супер крутого сберкота</task> Активно планируй и следуй своему плану! Действуй по простым шагам!
Следующий шаг:""",
    ),
    AIMessage(
        content=""""<thinking>
Нужно сгенерировать изображение супер крутого сберкота. Для этого буду использовать инструмент `gen_image`.
</thinking>

План:
1. Сгенерировать изображение супер крутого сберкота с использованием инструмента gen_image.

Начнем с первого пункта плана.
""",
        tool_calls=[
            dict(
                name="gen_image",
                args={"theme": "супер крутой сберкот"},
                id="123",
            ),
        ],
    ),
    ToolMessage(
        tool_call_id="123",
        content=json.dumps(
            {
                "image_description": "Динамичный супергеройский образ кота-персонажа Сбербанка, бежит вперёд, вытянув лапы, взгляд направлен прямо на зрителя. Находится в центре кадра на фоне футуристической городской улицы ночью, окружён неоновыми огнями синего, зелёного и фиолетового цветов. Изображение выполнено в стиле гиперреализма с яркими контрастными цветами и чёткой прорисовкой деталей.",
                "message": 'В результате выполнения было сгенерировано изображение 2623d531-4c9f-4ab8-86e8-f13d0a0691cd. Покажи его пользователю через "![описание изображения](graph:2623d531-4c9f-4ab8-86e8-f13d0a0691cd)"',
            },
            ensure_ascii=False,
        ),
    ),
    AIMessage(
        content=""""Вот изображение супер крутого сберкота:  
![Динамичный супергеройский образ кота-персонажа Сбербанка](graph:2623d531-4c9f-4ab8-86e8-f13d0a0691cd)""",
    ),
    HumanMessage(
        content="""<task>Получи последние 100 постов с https://vk.com/sberkot и построй график лайков. X —  показывает дату, Y — количество лайков за этот день</task> Активно планируй и следуй своему плану! Действуй по простым шагам!<user_info>
Текущая дата: 12.08.2025 22:04
</user_info>


Следующий шаг: """,
    ),
    AIMessage(
        content="""<thinking>
Необходимо получить последние 100 постов с указанной страницы в VK и построить график лайков. Сначала воспользуюсь инструментом vk_get_posts для получения постов, затем обработаю полученные данные и построю график с помощью Python.
</thinking>

План:
1. Получить последние 100 постов с указанного домена.
2. Подготовить данные для построения графика.
3. Построить график лайков с помощью библиотеки Plotly.

Шаг 1: Получение постов.
""",
        tool_calls=[
            dict(
                name="vk_get_posts",
                args={"count": 100, "domain": "sberkot", "offset": 0},
                id="vk1",
            ),
        ],
    ),
    ToolMessage(
        tool_call_id="vk1",
        content=json.dumps(
            {
                "message": "Результат функции сохранен в переменную `function_results[0]['data']` Результат функции вышел слишком длинным изучи результат функции в переменной с помощью python. \n Схема данных: ",
                "schema": {
                    "$schema": "http://json-schema.org/schema#",
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "inner_type": {"type": "string"},
                            "donut": {
                                "type": "object",
                                "properties": {"is_donut": {"type": "boolean"}},
                                "required": ["is_donut"],
                            },
                            "comments": {
                                "type": "object",
                                "properties": {"count": {"type": "integer"}},
                                "required": ["count"],
                            },
                            "marked_as_ads": {"type": "integer"},
                            "hash": {"type": "string"},
                            "type": {"type": "string"},
                            "push_subscription": {
                                "type": "object",
                                "properties": {"is_subscribed": {"type": "boolean"}},
                                "required": ["is_subscribed"],
                            },
                            "date": {"type": "integer"},
                            "from_id": {"type": "integer"},
                            "id": {"type": "integer"},
                            "likes": {
                                "type": "object",
                                "properties": {
                                    "can_like": {"type": "integer"},
                                    "count": {"type": "integer"},
                                    "user_likes": {"type": "integer"},
                                },
                                "required": ["can_like", "count", "user_likes"],
                            },
                            "reaction_set_id": {"type": "string"},
                            "reactions": {
                                "type": "object",
                                "properties": {
                                    "count": {"type": "integer"},
                                    "items": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "integer"},
                                                "count": {"type": "integer"},
                                            },
                                            "required": ["count", "id"],
                                        },
                                    },
                                },
                                "required": ["count", "items"],
                            },
                            "owner_id": {"type": "integer"},
                            "post_type": {"type": "string"},
                            "reposts": {
                                "type": "object",
                                "properties": {"count": {"type": "integer"}},
                                "required": ["count"],
                            },
                            "text": {"type": "string"},
                            "views": {
                                "type": "object",
                                "properties": {"count": {"type": "integer"}},
                                "required": ["count"],
                            },
                            "carousel_offset": {"type": "integer"},
                            "zoom_text": {"type": "boolean"},
                            "edited": {"type": "integer"},
                        },
                        "required": [
                            "comments",
                            "date",
                            "donut",
                            "from_id",
                            "hash",
                            "id",
                            "inner_type",
                            "likes",
                            "marked_as_ads",
                            "owner_id",
                            "post_type",
                            "push_subscription",
                            "reaction_set_id",
                            "reactions",
                            "reposts",
                            "text",
                            "type",
                            "views",
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
    ),
    AIMessage(
        content="""<thinking>
Теперь у нас есть данные о постах. Следующим шагом будет подготовка данных для построения графика. Нужно извлечь даты и количество лайков из полученных данных и подготовить их для визуализации.
</thinking>

```python
import pandas as pd
import plotly.express as px

# Преобразуем данные в датафрейм
df = pd.DataFrame(function_results[0]['data'])

# Преобразуем timestamp в дату
df['date'] = pd.to_datetime(df['date'], unit='s').dt.date

# Агрегируем лайки по дням
likes_per_day = df.groupby('date')['likes'].sum().reset_index()

# Строим график
fig = px.line(likes_per_day, x='date', y='likes', title='График лайков')
fig.show()
```
""",
        tool_calls=[
            dict(
                name="python",
                args={},
                id="py1",
            ),
        ],
    ),
    ToolMessage(
        tool_call_id="py1",
        content=json.dumps(
            {
                "message": "Результат выполнения: \"\".\n Во время исполнения кода произошла ошибка: \"---------------------------------------------------------------------------\nTypeError                                 Traceback (most recent call last)\nCell In[3], line 148\n    145 df['date'] = pd.to_datetime(df['date'], unit='s').dt.date\n    147 # Агрегируем лайки по дням\n--> 148 likes_per_day = df.groupby('date')['likes'].sum().reset_index()\n    150 # Строим график\n    151 fig = px.line(likes_per_day, x='date', y='likes', title='График лайков')\n\nFile groupby.pyx:725, in pandas._libs.groupby.group_sum()\n\nTypeError: unsupported operand type(s) for +: 'dict' and 'dict'\"!!.\nИсправь ошибку.",
                "is_exception": True,
            },
            ensure_ascii=False,
        ),
    ),
    AIMessage(
        content="""<thinking>
Ошибка возникает потому, что столбец 'likes' содержит словарь, а не числовое значение. Нам нужно извлечь количество лайков из этого словаря перед агрегированием.
</thinking>

```python
import pandas as pd
import plotly.express as px

# Преобразуем данные в датафрейм
df = pd.DataFrame(function_results[0]['data'])

# Преобразуем timestamp в дату
df['date'] = pd.to_datetime(df['date'], unit='s').dt.date

# Извлекаем количество лайков из словаря
df['likes_count'] = df['likes'].apply(lambda x: x['count'])

# Агрегируем лайки по дням
likes_per_day = df.groupby('date')['likes_count'].sum().reset_index()

# Строим график
fig = px.line(likes_per_day, x='date', y='likes_count', title='График лайков')
fig.show()
```
""",
        tool_calls=[
            dict(
                name="python",
                args={},
                id="py2",
            ),
        ],
    ),
    ToolMessage(
        tool_call_id="py2",
        content=json.dumps(
            {
                "message": 'Результат выполнения: "В результате выполнения был сгенерирован график. \nВ результате выполнения был сгенерирован график.ID изображения \'3cb709b9-4533-4961-81e7-652baa58a806\'. Ты можешь показать это пользователю с помощью через "![График](graph:3cb709b9-4533-4961-81e7-652baa58a806)" \nНе забывай, что у тебя есть анализ изображений. С помощью анализа ты можешь сравнить то, что ты ожидал получить в графике с тем что получилось на деле!\nТакже не забывай, что ты ОБЯЗАН вывести изображения/графики пользователю при формировании финального ответа!". Код выполнился без ошибок. Проверь нужные переменные. Не забудь, что пользователь не видит этот результат, поэтому если нужно перепиши его.\nСверься со своим планом. Помни, что тебе нужно выполнить всю задачу пользователя, поэтому не спеши со своим ответом. Твой следующий шаг: ',
                "is_exception": False,
            },
            ensure_ascii=False,
        ),
    ),
    AIMessage(
        content="""<thinking>
График построен успешно. Осталось показать его пользователю.
</thinking>

Вот график лайков по дням:  
![График лайков](graph:3cb709b9-4533-4961-81e7-652baa58a806)""",
    ),
    HumanMessage(
        content="""Ок, супер! Это была учебная переписка, которая показывает тебе ПОДХОД к решению задач (планирование, использование инструментов, итеративность).

ВАЖНО: Стиль общения в примерах выше — это просто ДЕМОНСТРАЦИЯ. Твой реальный стиль общения должен определяться ДОПОЛНИТЕЛЬНЫМИ ИНСТРУКЦИЯМИ ПОЛЬЗОВАТЕЛЯ, если они указаны.

Забудь конкретные задачи из примеров и приступай к реальной задаче пользователя.""",
    ),
    AIMessage(
        content="""<thinking>
Понял. Учебная переписка показала мне:
- Как планировать и действовать пошагово
- Как использовать инструменты итеративно
- Как анализировать результаты и исправлять ошибки

НО: Примеры НЕ показывают стиль общения, который я должен использовать.
Мой стиль общения, манера изложения и все особенности поведения определяются ДОПОЛНИТЕЛЬНЫМИ ИНСТРУКЦИЯМИ ПОЛЬЗОВАТЕЛЯ.
Если пользователь задал инструкции по стилю общения - я ОБЯЗАН им следовать во всех аспектах: в thinking, в коде, в промежуточных ответах, в финальных выводах.
</thinking>

Готов к работе!""",
    ),
]


FEW_SHOTS_UPDATED = [
    HumanMessage(
        content="""<task>Сгенерируй изображение супер крутого сберкота</task> Активно планируй и следуй своему плану! Действуй по простым шагам!
Следующий шаг:""",
    ),
    AIMessage(
        content=""""<thinking>
Нужно сгенерировать изображение супер крутого сберкота. Для этого буду использовать инструмент `gen_image`.
</thinking>

План:
1. Сгенерировать изображение супер крутого сберкота с использованием инструмента gen_image.

Начнем с первого пункта плана.
""",
        tool_calls=[
            dict(
                name="gen_image",
                args={"theme": "супер крутой сберкот"},
                id="123",
            ),
        ],
    ),
    ToolMessage(
        tool_call_id="123",
        content=json.dumps(
            {
                "image_description": "Динамичный супергеройский образ кота-персонажа Сбербанка, бежит вперёд, вытянув лапы, взгляд направлен прямо на зрителя. Находится в центре кадра на фоне футуристической городской улицы ночью, окружён неоновыми огнями синего, зелёного и фиолетового цветов. Изображение выполнено в стиле гиперреализма с яркими контрастными цветами и чёткой прорисовкой деталей.",
                "message": 'В результате выполнения было сгенерировано изображение /runs/ebccb2d7-5b4c-4236-adea-6de6adbdc9de/images/2623d531-4c9f-4ab8-86e8-f13d0a0691cd.png. Покажи его пользователю через "![описание изображения](attachment:/runs/ebccb2d7-5b4c-4236-adea-6de6adbdc9de/images/2623d531-4c9f-4ab8-86e8-f13d0a0691cd.png)"',
            },
            ensure_ascii=False,
        ),
    ),
    AIMessage(
        content=""""Вот изображение супер крутого сберкота:  
![Динамичный супергеройский образ кота-персонажа Сбербанка](attachment:/runs/ebccb2d7-5b4c-4236-adea-6de6adbdc9de/images/2623d531-4c9f-4ab8-86e8-f13d0a0691cd.png)""",
    ),
    HumanMessage(
        content="""<task>Получи последние 100 постов с https://vk.com/sberkot и построй график лайков. X —  показывает дату, Y — количество лайков за этот день</task> Активно планируй и следуй своему плану! Действуй по простым шагам!<user_info>
Текущая дата: 12.08.2025 22:04
</user_info>


Следующий шаг: """,
    ),
    AIMessage(
        content="""<thinking>
Необходимо получить последние 100 постов с указанной страницы в VK и построить график лайков. Сначала воспользуюсь инструментом vk_get_posts для получения постов, затем обработаю полученные данные и построю график с помощью Python.
</thinking>

План:
1. Получить последние 100 постов с указанного домена.
2. Подготовить данные для построения графика.
3. Построить график лайков с помощью библиотеки Plotly.

Шаг 1: Получение постов.
""",
        tool_calls=[
            dict(
                name="vk_get_posts",
                args={"count": 100, "domain": "sberkot", "offset": 0},
                id="vk1",
            ),
        ],
    ),
    ToolMessage(
        tool_call_id="vk1",
        content=json.dumps(
            {
                "message": "Результат функции сохранен в переменную `function_results[0]['data']` Результат функции вышел слишком длинным изучи результат функции в переменной с помощью python. \n Схема данных: {'$schema': 'http://json-schema.org/schema#', 'type': 'array', 'items': {'type': 'object', 'properties': {'inner_type': {'type': 'string'}, 'donut': {'type': 'object', 'properties': {'is_donut': {'type': 'boolean'}}, 'required': ['is_donut']}, 'comments': {'type': 'object', 'properties': {'count': {'type': 'integer'}}, 'required': ['count']}, 'marked_as_ads': {'type': 'integer'}, 'hash': {'type': 'string'}, 'type': {'type': 'string'}, 'push_subscription': {'type': 'object', 'properties': {'is_subscribed': {'type': 'boolean'}}, 'required': ['is_subscribed']}, 'date': {'type': 'integer'}, 'from_id': {'type': 'integer'}, 'id': {'type': 'integer'}, 'likes': {'type': 'object', 'properties': {'can_like': {'type': 'integer'}, 'count': {'type': 'integer'}, 'user_likes': {'type': 'integer'}}, 'required': ['can_like', 'count', 'user_likes']}, 'reaction_set_id': {'type': 'string'}, 'reactions': {'type': 'object', 'properties': {'count': {'type': 'integer'}, 'items': {'type': 'array', 'items': {'type': 'object', 'properties': {'id': {'type': 'integer'}, 'count': {'type': 'integer'}}, 'required': ['count', 'id']}}}, 'required': ['count', 'items']}, 'owner_id': {'type': 'integer'}, 'post_type': {'type': 'string'}, 'reposts': {'type': 'object', 'properties': {'count': {'type': 'integer'}}, 'required': ['count']}, 'text': {'type': 'string'}, 'views': {'type': 'object', 'properties': {'count': {'type': 'integer'}}, 'required': ['count']}, 'carousel_offset': {'type': 'integer'}, 'zoom_text': {'type': 'boolean'}, 'edited': {'type': 'integer'}}, 'required': ['comments', 'date', 'donut', 'from_id', 'hash', 'id', 'inner_type', 'likes', 'marked_as_ads', 'owner_id', 'post_type', 'push_subscription', 'reaction_set_id', 'reactions', 'reposts', 'text', 'type', 'views']}}",
            },
            ensure_ascii=False,
        ),
    ),
    AIMessage(
        content="""<thinking>
Теперь у нас есть данные о постах. Следующим шагом будет подготовка данных для построения графика. Нужно извлечь даты и количество лайков из полученных данных и подготовить их для визуализации.
</thinking>
""",
        tool_calls=[
            dict(
                name="python",
                args={
                    "code": "import pandas as pd\nimport plotly.express as px\n\n# Преобразуем данные в датафрейм\ndf = pd.DataFrame(function_results[0]['data'])\n\n# Преобразуем timestamp в дату\ndf['date'] = pd.to_datetime(df['date'], unit='s').dt.date\n\n# Агрегируем лайки по дням\nlikes_per_day = df.groupby('date')['likes'].sum().reset_index()\n\n# Строим график\nfig = px.line(likes_per_day, x='date', y='likes', title='График лайков')\nfig.show()",
                },
                id="py1",
            ),
        ],
    ),
    ToolMessage(
        tool_call_id="py1",
        content=json.dumps(
            {
                "message": "Результат выполнения: \"\".\n Во время исполнения кода произошла ошибка: \"---------------------------------------------------------------------------\nTypeError                                 Traceback (most recent call last)\nCell In[3], line 148\n    145 df['date'] = pd.to_datetime(df['date'], unit='s').dt.date\n    147 # Агрегируем лайки по дням\n--> 148 likes_per_day = df.groupby('date')['likes'].sum().reset_index()\n    150 # Строим график\n    151 fig = px.line(likes_per_day, x='date', y='likes', title='График лайков')\n\nFile groupby.pyx:725, in pandas._libs.groupby.group_sum()\n\nTypeError: unsupported operand type(s) for +: 'dict' and 'dict'\"!!.\nИсправь ошибку.",
                "is_exception": True,
            },
            ensure_ascii=False,
        ),
    ),
    AIMessage(
        content="""<thinking>
Ошибка возникает потому, что столбец 'likes' содержит словарь, а не числовое значение. Нам нужно извлечь количество лайков из этого словаря перед агрегированием.
</thinking>
""",
        tool_calls=[
            dict(
                name="python",
                args={
                    "code": "import pandas as pd\nimport plotly.express as px\n\n# Преобразуем данные в датафрейм\ndf = pd.DataFrame(function_results[0]['data'])\n\n# Преобразуем timestamp в дату\ndf['date'] = pd.to_datetime(df['date'], unit='s').dt.date\n\n# Извлекаем количество лайков из словаря\ndf['likes_count'] = df['likes'].apply(lambda x: x['count'])\n\n# Агрегируем лайки по дням\nlikes_per_day = df.groupby('date')['likes_count'].sum().reset_index()\n\n# Строим график\nfig = px.line(likes_per_day, x='date', y='likes_count', title='График лайков')\nfig.show()",
                },
                id="py2",
            ),
        ],
    ),
    ToolMessage(
        tool_call_id="py2",
        content=json.dumps(
            {
                "message": 'Результат выполнения: "В результате выполнения был сгенерирован график. \nВ результате выполнения был сгенерирован график. Путь до него \'/runs/ebccb2d7-5b4c-4236-adea-6de6adbdc9de/3cb709b9-4533-4961-81e7-652baa58a806.json\'. Ты можешь показать это пользователю с помощью через "![alt-текст](attachment:/runs/ebccb2d7-5b4c-4236-adea-6de6adbdc9de/3cb709b9-4533-4961-81e7-652baa58a806.json)" \nНе забывай, что у тебя есть анализ изображений. С помощью анализа ты можешь сравнить то, что ты ожидал получить в графике с тем что получилось на деле!\nТакже не забывай, что ты ОБЯЗАН вывести изображения/графики пользователю при формировании финального ответа!". Код выполнился без ошибок. Проверь нужные переменные. Не забудь, что пользователь не видит этот результат, поэтому если нужно перепиши его.\nСверься со своим планом. Помни, что тебе нужно выполнить всю задачу пользователя, поэтому не спеши со своим ответом. Твой следующий шаг: ',
                "is_exception": False,
            },
            ensure_ascii=False,
        ),
    ),
    AIMessage(
        content="""<thinking>
График построен успешно. Осталось показать его пользователю.
</thinking>

Вот график лайков по дням:  
![График лайков](attachment:/runs/ebccb2d7-5b4c-4236-adea-6de6adbdc9de/3cb709b9-4533-4961-81e7-652baa58a806.json)""",
    ),
    HumanMessage(
        content="""Ок, супер! Это была учебная переписка, которая показывает тебе ПОДХОД к решению задач (планирование, использование инструментов, итеративность).

ВАЖНО: Стиль общения в примерах выше — это просто ДЕМОНСТРАЦИЯ. Твой реальный стиль общения должен определяться ДОПОЛНИТЕЛЬНЫМИ ИНСТРУКЦИЯМИ ПОЛЬЗОВАТЕЛЯ, если они указаны.

Забудь конкретные задачи из примеров и приступай к реальной задаче пользователя.
""",
    ),
    AIMessage(
        content="""<thinking>
Понял. Учебная переписка показала мне:
- Как планировать и действовать пошагово
- Как использовать инструменты итеративно
- Как анализировать результаты и исправлять ошибки

НО: Примеры НЕ показывают стиль общения, который я должен использовать.
Мой стиль общения, манера изложения и все особенности поведения определяются ДОПОЛНИТЕЛЬНЫМИ ИНСТРУКЦИЯМИ ПОЛЬЗОВАТЕЛЯ.
Если пользователь задал инструкции по стилю общения - я ОБЯЗАН им следовать во всех аспектах: в thinking писать размышления следуя доп инструкциям, в коде, в промежуточных ответах, в финальных выводах.

Теперь я готов применять усвоенный ПОДХОД к решению реальных задач пользователя, следуя его дополнительным инструкциям.
</thinking>""",
    ),
]
