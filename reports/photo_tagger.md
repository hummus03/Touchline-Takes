# Photo tagger report

**Data: synthetic.** Procedurally generated scenes (`touchline_takes/tools/synthetic_photos.py`). These scores show the pipeline works; they say little about real match photos. Add real photos under `data/photos/<tag>/` and retrain.

Tags: crowd, match_action, press_conference, stadium · 240 images · stratified split 180 train / 60 test.

| Model | Accuracy | Precision (macro) | Recall (macro) | F1 (macro) |
|---|---|---|---|---|
| VGG16 transfer (frozen base + head) | 1.0 | 1.0 | 1.0 | 1.0 |
| VGG16 fine-tuned block5 (3 epochs, training split only) | 1.0 | 1.0 | 1.0 | 1.0 |
| Colour-histogram logistic regression | 0.8 | 0.7975 | 0.8 | 0.7934 |
| Majority class | 0.25 | 0.0625 | 0.25 | 0.1 |

Confusion matrix (rows = actual, cols = predicted, order crowd / match_action / press_conference / stadium):

      15     0     0     0
       0    15     0     0
       0     0    15     0
       0     0     0    15
