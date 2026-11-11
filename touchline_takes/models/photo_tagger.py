"""Photo tagger: VGG16 transfer learning for match photos.

Two-stage transfer learning, the standard recipe for small datasets:

1. **Feature extraction**: VGG16's convolutional base, pre-trained on ImageNet and
   frozen, turns each photo into a 512-d vector (global average pooling). A small
   dense head (Dense 256 -> Dropout -> softmax) is trained on those vectors.
2. **Fine-tuning** (optional): the head is put on top of the base, VGG16's last
   convolutional block (``block5``) is unfrozen, and the whole thing trains end to
   end at a low learning rate with light data augmentation.

Evaluation uses a stratified train/test split and compares against a majority-class
baseline and a colour-histogram logistic regression (what you get without a
pre-trained network). Keras runs on the JAX backend (CPU is fine).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

import numpy as np
from PIL import Image, UnidentifiedImageError
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, precision_score,
                             recall_score)
from sklearn.model_selection import train_test_split

os.environ.setdefault("KERAS_BACKEND", "jax")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
WEIGHTS_FILE = "vgg16_weights_tf_dim_ordering_tf_kernels_notop.h5"


def keras_module():
    """Import Keras lazily (it is slow to import and only the tagger needs it)."""
    import keras  # pylint: disable=import-outside-toplevel
    return keras


def vgg16_weights_cached() -> bool:
    """True if the ImageNet VGG16 weights are already in the Keras cache."""
    base = Path(os.environ.get("KERAS_HOME", Path.home() / ".keras"))
    return (base / "models" / WEIGHTS_FILE).exists()


def load_image(source: str | Path | bytes, size: int = 224) -> np.ndarray:
    """Decode an image file/bytes into an RGB ``size x size`` float array (0-255)."""
    import io  # pylint: disable=import-outside-toplevel
    try:
        img = Image.open(io.BytesIO(source) if isinstance(source, bytes) else source)
        img = img.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"not a readable image: {exc}") from exc
    # Centre-crop to a square, then resize.
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize((size, size))
    return np.asarray(img, dtype=np.float32)


def load_folder(root: str | Path, size: int = 224
                ) -> tuple[np.ndarray, list[str], list[str]]:
    """Load ``root/<tag>/*.jpg`` into ``(images, tags, paths)``."""
    images, tags, paths = [], [], []
    for folder in sorted(p for p in Path(root).iterdir() if p.is_dir()):
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() in IMAGE_EXTENSIONS:
                images.append(load_image(path, size))
                tags.append(folder.name)
                paths.append(str(path))
    if not images:
        raise ValueError(f"no images found under {root}/<tag>/")
    return np.stack(images), tags, paths


def vgg_preprocess(images: np.ndarray) -> np.ndarray:
    """VGG16's ImageNet preprocessing (RGB->BGR, mean subtraction)."""
    return keras_module().applications.vgg16.preprocess_input(
        np.array(images, dtype=np.float32, copy=True))


class Backbone(Protocol):
    """Anything that maps an image batch to feature vectors."""

    input_size: int
    name: str

    def features(self, images: np.ndarray) -> np.ndarray:
        """``(N, H, W, 3)`` 0-255 images -> ``(N, D)`` features."""
        raise NotImplementedError


class VGG16Backbone:
    """Frozen VGG16 convolutional base with global average pooling (512-d features).

    ``weights=None`` builds the same architecture with random weights; the tests use
    that (with a tiny input size) so they run offline.
    """

    name = "vgg16"

    def __init__(self, weights: str | None = "imagenet", input_size: int = 224) -> None:
        keras = keras_module()
        self.weights = weights
        self.input_size = input_size
        self.base = keras.applications.VGG16(
            include_top=False, weights=weights, input_shape=(input_size, input_size, 3))
        self.base.trainable = False
        inputs = keras.Input((input_size, input_size, 3))
        pooled = keras.layers.GlobalAveragePooling2D()(self.base(inputs, training=False))
        self.extractor = keras.Model(inputs, pooled, name="vgg16_features")

    def features(self, images: np.ndarray) -> np.ndarray:
        """512-d pooled VGG16 features for a batch of 0-255 RGB images."""
        return np.asarray(self.extractor.predict(vgg_preprocess(images), batch_size=16,
                                                 verbose=0))


def colour_histogram(images: np.ndarray, bins: int = 8) -> np.ndarray:
    """Baseline features: a joint RGB colour histogram per image (no deep learning)."""
    quantised = np.clip((images / 256 * bins).astype(int), 0, bins - 1)
    codes = quantised[..., 0] * bins * bins + quantised[..., 1] * bins + quantised[..., 2]
    hists = np.stack([np.bincount(c.ravel(), minlength=bins ** 3) for c in codes])
    return hists / hists.sum(axis=1, keepdims=True)


def _metrics(y_true: Sequence[str], y_pred: Sequence[str], labels: list[str]) -> dict[str, Any]:
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision_macro": round(float(precision_score(y_true, y_pred, labels=labels,
                                                       average="macro", zero_division=0)), 4),
        "recall_macro": round(float(recall_score(y_true, y_pred, labels=labels,
                                                 average="macro", zero_division=0)), 4),
        "f1_macro": round(float(f1_score(y_true, y_pred, labels=labels, average="macro",
                                         zero_division=0)), 4),
        "confusion_matrix": {"labels": labels, "matrix": confusion_matrix(
            y_true, y_pred, labels=labels).tolist()},
    }


def build_head(keras, n_inputs: int, n_classes: int):
    """The classification head trained on VGG16 features."""
    return keras.Sequential([
        keras.Input((n_inputs,)),
        keras.layers.Dense(256, activation="relu"),
        keras.layers.Dropout(0.3),
        keras.layers.Dense(n_classes, activation="softmax"),
    ], name="tag_head")


@dataclass
class PhotoTagger:
    """Trains, evaluates, saves and serves the tagger."""

    backbone: Backbone
    labels: list[str] = field(default_factory=list)
    head: Any = None
    finetuned: Any = None
    report: dict[str, Any] = field(default_factory=dict)
    seed: int = 7

    # ------------------------------------------------------------------ training
    def _fit_head(self, features: np.ndarray, y: np.ndarray, epochs: int) -> Any:
        keras = keras_module()
        keras.utils.set_random_seed(self.seed)
        head = build_head(keras, features.shape[1], len(self.labels))
        head.compile(optimizer=keras.optimizers.Adam(1e-3),
                     loss="sparse_categorical_crossentropy", metrics=["accuracy"])
        head.fit(features, y, epochs=epochs, batch_size=16, verbose=0, validation_split=0.15,
                 callbacks=[keras.callbacks.EarlyStopping(patience=5,
                                                          restore_best_weights=True)])
        return head

    def fit(self, images: np.ndarray, tags: Sequence[str], test_size: float = 0.25,
            epochs: int = 40) -> dict[str, Any]:
        """Stratified split, train the head on frozen-VGG16 features, evaluate vs baselines,
        then refit the head on all images."""
        self.labels = sorted(set(tags))
        y = np.array([self.labels.index(t) for t in tags], dtype=np.int32)
        idx_train, idx_test = train_test_split(np.arange(len(y)), test_size=test_size,
                                               random_state=self.seed, stratify=y)
        features = self.backbone.features(images)
        head = self._fit_head(features[idx_train], y[idx_train], epochs)
        pred = head.predict(features[idx_test], verbose=0).argmax(axis=1)
        names = np.array(self.labels)
        y_test = names[y[idx_test]]
        hist = colour_histogram(images)
        hist_model = LogisticRegression(max_iter=2000).fit(hist[idx_train], y[idx_train])
        majority = DummyClassifier(strategy="most_frequent").fit(hist[idx_train], y[idx_train])
        self.report = {
            "backbone": self.backbone.name, "labels": self.labels,
            "n_images": len(y), "n_train": len(idx_train), "n_test": len(idx_test),
            "transfer_vgg16": _metrics(y_test, names[pred], self.labels),
            "baselines": {
                "majority_class": _metrics(y_test, names[majority.predict(hist[idx_test])],
                                           self.labels),
                "colour_histogram_logreg": _metrics(
                    y_test, names[hist_model.predict(hist[idx_test])], self.labels)},
        }
        self.head = self._fit_head(features, y, epochs)  # final head uses every image
        self.finetuned = None
        return self.report

    def fine_tune(self, images: np.ndarray, tags: Sequence[str], epochs: int = 3,
                  learning_rate: float = 1e-5, head_epochs: int = 40) -> dict[str, Any]:
        """Unfreeze VGG16's ``block5`` and train base + head end to end (with augmentation).

        Uses the same stratified split as :meth:`fit`. Only training images are seen:
        a fresh head is trained on frozen features of the training split, then a fresh
        VGG16 base (the shared feature extractor is left untouched) is fine-tuned with it.
        The fine-tuned model is kept for inference.
        """
        if not isinstance(self.backbone, VGG16Backbone):
            raise RuntimeError("fine-tuning needs a VGG16 backbone")
        keras = keras_module()
        self.labels = self.labels or sorted(set(tags))
        y = np.array([self.labels.index(t) for t in tags], dtype=np.int32)
        idx_train, idx_test = train_test_split(np.arange(len(y)), test_size=0.25,
                                               random_state=self.seed, stratify=y)
        head = self._fit_head(self.backbone.features(images[idx_train]), y[idx_train],
                              head_epochs)
        size = self.backbone.input_size
        base = keras.applications.VGG16(include_top=False,
                                        weights=getattr(self.backbone, "weights", "imagenet"),
                                        input_shape=(size, size, 3))
        for layer in base.layers:
            layer.trainable = layer.name.startswith("block5")
        inputs = keras.Input((size, size, 3))
        augmented = keras.layers.RandomFlip("horizontal")(inputs)
        augmented = keras.layers.RandomZoom(0.1)(augmented)
        pooled = keras.layers.GlobalAveragePooling2D()(base(augmented))
        model = keras.Model(inputs, head(pooled), name="vgg16_finetuned")
        model.compile(optimizer=keras.optimizers.Adam(learning_rate),
                      loss="sparse_categorical_crossentropy", metrics=["accuracy"])
        x = vgg_preprocess(images)
        model.fit(x[idx_train], y[idx_train], epochs=epochs, batch_size=8, verbose=0)
        pred = model.predict(x[idx_test], verbose=0).argmax(axis=1)
        names = np.array(self.labels)
        self.report["fine_tuned_block5"] = _metrics(names[y[idx_test]], names[pred],
                                                    self.labels)
        self.report["fine_tune_epochs"] = epochs
        self.finetuned = model
        return self.report

    # ------------------------------------------------------------------ inference
    def predict_proba(self, images: np.ndarray) -> np.ndarray:
        """Tag probabilities, columns in :attr:`labels` order."""
        if self.finetuned is not None:
            return np.asarray(self.finetuned.predict(vgg_preprocess(images),
                                                     verbose=0))
        if self.head is None:
            raise RuntimeError("tagger is not trained")
        return np.asarray(self.head.predict(self.backbone.features(images), verbose=0))

    def tag(self, images: np.ndarray, top_k: int = 2, min_prob: float = 0.2
            ) -> list[list[dict[str, float]]]:
        """Top tags per image: ``[[{"tag": "crowd", "prob": 0.81}, ...], ...]``."""
        out = []
        for row in self.predict_proba(images):
            order = np.argsort(-row)[:top_k]
            tags = [{"tag": self.labels[i], "prob": round(float(row[i]), 3)} for i in order
                    if row[i] >= min_prob]
            out.append(tags or [{"tag": self.labels[int(order[0])],
                                 "prob": round(float(row[order[0]]), 3)}])
        return out

    # ------------------------------------------------------------------ persistence
    def save(self, directory: str | Path) -> None:
        """Save the head (and the fine-tuned model, if any), labels and report."""
        out = Path(directory)
        out.mkdir(parents=True, exist_ok=True)
        self.head.save(out / "head.keras")
        if self.finetuned is not None:
            self.finetuned.save(out / "finetuned.keras")
        elif (out / "finetuned.keras").exists():
            (out / "finetuned.keras").unlink()
        (out / "meta.json").write_text(json.dumps({
            "labels": self.labels, "backbone": self.backbone.name,
            "input_size": self.backbone.input_size, "report": self.report}, indent=2),
            encoding="utf-8")

    @classmethod
    def load(cls, directory: str | Path,
             backbone_factory: Callable[[int], Backbone] | None = None) -> "PhotoTagger":
        """Load a saved tagger (builds the VGG16 backbone unless a factory is given)."""
        keras = keras_module()
        src = Path(directory)
        meta = json.loads((src / "meta.json").read_text(encoding="utf-8"))
        factory = backbone_factory or (lambda size: VGG16Backbone("imagenet", size))
        tagger = cls(backbone=factory(meta["input_size"]), labels=meta["labels"],
                     report=meta.get("report", {}))
        tagger.head = keras.models.load_model(src / "head.keras")
        if (src / "finetuned.keras").exists():
            tagger.finetuned = keras.models.load_model(src / "finetuned.keras")
        return tagger


def model_available(directory: str | Path) -> bool:
    """True if a trained tagger has been saved in ``directory``."""
    return (Path(directory) / "meta.json").exists() and (Path(directory) / "head.keras").exists()
