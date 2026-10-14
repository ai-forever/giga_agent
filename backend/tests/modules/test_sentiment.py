import tempfile
import unittest
from pathlib import Path

import numpy as np

from giga_agent.modules.repl.repl_tools.sentiment import (
    NumpySentimentModel,
    _preload_models,
)


class NumpySentimentModelTests(unittest.TestCase):
    def test_loads_npz_without_pickle_and_predicts_labels(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "sentiment_test.npz"
            np.savez_compressed(
                model_path,
                weights=np.array([[2.0, 0.0], [0.0, 2.0]]),
                bias=np.array([0.0, 0.0]),
                classes=np.array(["negative", "positive"]),
            )

            model = NumpySentimentModel.load(model_path)

        predictions = model.predict_labels(
            np.array([[1.0, 0.0], [0.0, 1.0], [2.0, -1.0]])
        )
        self.assertEqual(predictions.tolist(), ["negative", "positive", "negative"])

    def test_bundled_models_load(self):
        models = _preload_models()

        self.assertEqual(
            set(models),
            {"Embeddings-2", "EmbeddingsGigaR", "text-embedding-3-small"},
        )
        self.assertTrue(all(model.weights.shape[0] == 3 for model in models.values()))
        self.assertTrue(
            all(
                model.classes.tolist() == ["negative", "neutral", "positive"]
                for model in models.values()
            )
        )

    def test_rejects_wrong_embedding_dimension(self):
        model = NumpySentimentModel(
            weights=np.zeros((2, 3)),
            bias=np.zeros(2),
            classes=np.array(["negative", "positive"]),
        )

        with self.assertRaisesRegex(ValueError, "Embedding dimensions"):
            model.predict_labels(np.zeros((1, 2)))
