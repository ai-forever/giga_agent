# Подагенты
## [Агент презентаций](backend/graph/giga_agent/agents/presentation_agent)
Создает презентации с помощью [Reveal.js](https://revealjs.com/). Генерирует слайды / изображения к ним.

Так же, имеет возможность подгружать в презентации изображения/графики из основного агента GigaAgent.

Пример работы: [переписка](/docs/examples/mortgage/landing_presentation_chat.pdf), [презентация](/docs/examples/mortgage/presentation.pdf)
## [Агент генерации подкастов](backend/graph/giga_agent/agents/podcast)
Создает подкаст на основе переписки / контента по ссылке. Использует синтез [SaluteSpeech](https://developers.sber.ru/portal/products/smartspeech).

Пример работы: [переписка](/docs/examples/mortgage_podcast/podcast_chat.pdf), [подкаст](/docs/examples/mortgage_podcast/podcast.mp3)
## [Агент Мемов](backend/graph/giga_agent/agents/meme_agent)
Создает мемы. Достаточно простой агент, можно использовать в качестве примера для создания своего.

Мемы со сберкотом, может генерить только на GigaChat API Kandinsky

Пример работы: [чат](/docs/examples/memes/chat.pdf)

![мем_1](/docs/examples/memes/meme1.jpeg), ![мем_2](/docs/examples/memes/meme2.jpg)
## [Агент по созданию Lean Canvas](backend/graph/giga_agent/agents/lean_canvas)
Создает LeanCanvas — популярный инструмента для описания бизнес-модели стартапов.

Пример работы: [переписка](docs/examples/lean_canvas/lean_canvas.pdf)
## [Агент по созданию лендингов](backend/graph/giga_agent/agents/landing_agent)
Создает лендинг

Пример работы: [переписка](/docs/examples/mortgage/landing_presentation_chat.pdf)
## [Агент исследователь города](backend/graph/giga_agent/agents/gis_agent)
Интересные места + карта с помощью 2GIS

Пример работы: [переписка](/docs/examples/city_explorer/city_explorer.pdf)
