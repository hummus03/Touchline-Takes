"""Train the VGG16 photo tagger: ``python scripts/train_photo_tagger.py``.

Data: ``data/photos/<tag>/*.jpg`` (your own labelled photos, one folder per tag). If that
folder has no images, a synthetic dataset is generated into ``data/photos_synthetic`` and
used instead. Use ``--synthetic`` to force that.

Writes the model to ``PHOTO_MODEL_DIR`` (default ``data/models/photo_tagger``) and a
report to ``reports/photo_tagger.md`` / ``.json``. The ImageNet VGG16 weights (58 MB) are
downloaded to ``~/.keras/models`` on first use.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# pylint: disable=wrong-import-position
from touchline_takes.config import DATA_DIR, PROJECT_ROOT, Settings
from touchline_takes.models.photo_tagger import (IMAGE_EXTENSIONS, PhotoTagger, VGG16Backbone,
                                                 load_folder)
from touchline_takes.tools.synthetic_photos import write_dataset


def has_images(root: Path) -> bool:
    """True if ``root/<tag>/`` contains any image."""
    return root.is_dir() and any(p.suffix.lower() in IMAGE_EXTENSIONS
                                 for p in root.glob("*/*"))


def to_markdown(report: dict, data_note: str) -> str:
    """Human-readable training report."""
    rows = [("VGG16 transfer (frozen base + head)", report["transfer_vgg16"])]
    if "fine_tuned_block5" in report:
        rows.append((f"VGG16 fine-tuned block5 ({report['fine_tune_epochs']} epochs, "
                     "training split only)",
                     report["fine_tuned_block5"]))
    rows += [("Colour-histogram logistic regression", report["baselines"][
        "colour_histogram_logreg"]), ("Majority class", report["baselines"]["majority_class"])]
    lines = ["# Photo tagger report", "", data_note, "",
             f"Tags: {', '.join(report['labels'])} · {report['n_images']} images · stratified "
             f"split {report['n_train']} train / {report['n_test']} test.", "",
             "| Model | Accuracy | Precision (macro) | Recall (macro) | F1 (macro) |",
             "|---|---|---|---|---|"]
    lines += [f"| {name} | {m['accuracy']} | {m['precision_macro']} | {m['recall_macro']} | "
              f"{m['f1_macro']} |" for name, m in rows]
    best = report.get("fine_tuned_block5", report["transfer_vgg16"])
    matrix = best["confusion_matrix"]
    lines += ["", f"Confusion matrix (rows = actual, cols = predicted, order "
              f"{' / '.join(matrix['labels'])}):", ""]
    lines += ["    " + "  ".join(f"{v:>4}" for v in row) for row in matrix["matrix"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Train the VGG16 photo tagger.")
    parser.add_argument("--data", default=str(DATA_DIR / "photos"))
    parser.add_argument("--synthetic", action="store_true", help="train on synthetic photos")
    parser.add_argument("--per-tag", type=int, default=60, help="synthetic photos per tag")
    parser.add_argument("--epochs", type=int, default=40, help="max head epochs")
    parser.add_argument("--fine-tune", type=int, default=0, metavar="EPOCHS",
                        help="also fine-tune VGG16 block5 for EPOCHS (slow on CPU)")
    parser.add_argument("--out", default=None, help="model directory")
    parser.add_argument("--report-dir", default=str(PROJECT_ROOT / "reports"))
    args = parser.parse_args(argv)
    data = Path(args.data)
    if args.synthetic or not has_images(data):
        data = DATA_DIR / "photos_synthetic"
        if not has_images(data):
            write_dataset(data, per_tag=args.per_tag)
        note = ("**Data: synthetic.** Procedurally generated scenes "
                "(`touchline_takes/tools/synthetic_photos.py`). These scores show the pipeline "
                "works; they say little about real match photos. Add real photos under "
                "`data/photos/<tag>/` and retrain.")
    else:
        note = f"**Data:** `{data}` (your labelled photos)."
    print(f"Loading photos from {data} ...")
    images, tags, _ = load_folder(data)
    start = time.perf_counter()
    tagger = PhotoTagger(VGG16Backbone("imagenet"))
    report = tagger.fit(images, tags, epochs=args.epochs)
    if args.fine_tune:
        report = tagger.fine_tune(images, tags, epochs=args.fine_tune)
    report["train_seconds"] = round(time.perf_counter() - start, 1)
    report["data"] = str(data)
    out = args.out or Settings.from_env().photo_model_dir
    tagger.save(out)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "photo_tagger.json").write_text(json.dumps(
        {**report, "data_note": note}, indent=2), encoding="utf-8")
    markdown = to_markdown(report, note)
    (report_dir / "photo_tagger.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Saved model to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
