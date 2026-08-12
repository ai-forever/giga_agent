# Что в этой папке?
Здесь хранится демонстрационная упрощенная модель, которая позволяет с помощью GigaChat эмбедингов делать sentiment анализ.

Текущая модель сгенерирована под модель эмбедингов 'EmbeddingsGigaR', которая находится на продакш url гигачата.

Если вы хотите использовать другую модель/на другом урле, лучше всего сгенерить модель по новому в файле [sentiment_model.ipynb](sentiment_model.ipynb)

Для обновления production-модели используйте `train_sentiment_embeddings2.py`. Он сохраняет
только параметры линейного классификатора в формате `.npz`, поэтому production runtime не
требует `scikit-learn` или `scipy`. Обучение выполняется в окружении `jupyter-full`.

Или использовать другой способ sentiment analysis.

**ВАЖНО**: Вы можете взять csv файл для sentiment анализа, [отсюда](/backend/additional_data/sentiment_analysis/rusentiment_random_posts.csv)
