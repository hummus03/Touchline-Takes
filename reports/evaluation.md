# Touchline Takes evaluation report

Fixture stories: 31 · guardrail (every published claim sourced): **PASS**

## Newsroom quality per writer configuration

| Metric | template_writer | scripted_llm_writer |
|---|---|---|
| drafts | 27 | 27 |
| published | 24 | 24 |
| rejected | 3 | 3 |
| claims_with_source_share_first_pass | 1.0 | 0.881 |
| claims_with_source_share_published | 1.0 | 1.0 |
| unsupported_claims_caught | 0 | 32 |
| contradictions_caught | 0 | 11 |
| factcheck_bounces | 0 | 10 |
| editor_reviews | 33 | 33 |
| editor_rejection_rate | 0.273 | 0.273 |
| retries_total | 6 | 16 |
| retries_mean | 0.222 | 0.593 |
| retries_max | 2 | 2 |
| llm_calls_per_article | 0.0 | 1.593 |
| cost_usd_per_article | 0.0 | 0.0 |
| projected_cost_usd_per_article_claude_opus_5_5 | 0.0 | 0.010513 |
| tokens_per_article | 0.0 | 1337.0 |
| agent_latency_s_per_article | 0.0104 | 0.0148 |
| pipeline_s_per_article | 0.0296 | 0.0356 |
| expectations passed | 21/21 | 21/21 |

### Rejections logged: template_writer

- **editor** (rev 0) on *Paris Saint-Germain v Marseille: the Touchline Take*: too short: 88 words (minimum 90)
- **editor** (rev 1) on *Paris Saint-Germain v Marseille: the Touchline Take*: too short: 89 words (minimum 90)
- **editor** (rev 2) on *Paris Saint-Germain v Marseille: the Touchline Take*: too short: 89 words (minimum 90)
- **editor** (rev 0) on *Bayern Munich v Bayer Leverkusen: the Touchline Take*: too short: 82 words (minimum 90)
- **editor** (rev 1) on *Bayern Munich v Bayer Leverkusen: the Touchline Take*: too short: 80 words (minimum 90)
- **editor** (rev 2) on *Bayern Munich v Bayer Leverkusen: the Touchline Take*: too short: 83 words (minimum 90)
- **editor** (rev 0) on *Celtic: the Touchline Take on the transfer talk*: too short: 69 words (minimum 90)
- **editor** (rev 1) on *Celtic: the Touchline Take on the transfer talk*: too short: 64 words (minimum 90)
- **editor** (rev 2) on *Celtic: the Touchline Take on the transfer talk*: too short: 66 words (minimum 90)

### Rejections logged: scripted_llm_writer

- **factcheck** (rev 0) on *Arsenal v Chelsea: the Touchline Take*: unsupported claim (not in cited evidence: insiders, 200, january): Insiders claim the club will spend 200 million in January [S1].; unsupported claim (not in cited evidence: rival, juventus): Rival scouts from Juventus w
- **factcheck** (rev 0) on *Manchester United v Fulham: the Touchline Take*: contradicted claim (contradicts source: claim says Manchester United beat Fulham 2-1, source says Fulham beat Manchester United 2-1): Manchester United beat Fulham 2-1, as reported by Eval Wire [S1].; contradicted claim 
- **editor** (rev 0) on *Paris Saint-Germain v Marseille: the Touchline Take*: too short: 88 words (minimum 90)
- **editor** (rev 1) on *Paris Saint-Germain v Marseille: the Touchline Take*: too short: 89 words (minimum 90)
- **editor** (rev 2) on *Paris Saint-Germain v Marseille: the Touchline Take*: too short: 89 words (minimum 90)
- **factcheck** (rev 0) on *Newcastle v Southampton: the Touchline Take*: contradicted claim (contradicts source: claim says Southampton beat Newcastle 5-0, source says Newcastle beat Southampton 5-0): Southampton beat Newcastle 5-0, as reported by Eval Wire [S1].; unsupported claim (not in ci
- **editor** (rev 0) on *Bayern Munich v Bayer Leverkusen: the Touchline Take*: too short: 82 words (minimum 90)
- **editor** (rev 1) on *Bayern Munich v Bayer Leverkusen: the Touchline Take*: too short: 80 words (minimum 90)
- **editor** (rev 2) on *Bayern Munich v Bayer Leverkusen: the Touchline Take*: too short: 83 words (minimum 90)
- **factcheck** (rev 0) on *Aston Villa v Manchester City: the Touchline Take*: contradicted claim (contradicts source: claim says Manchester City beat Aston Villa 1-0, source says Aston Villa beat Manchester City 1-0): Manchester City beat Aston Villa 1-0, as reported by Eval Wire [S1].; contradict
- **factcheck** (rev 0) on *Tottenham: the Touchline Take on the dugout*: unsupported claim (not in cited evidence: insiders, 200, january): Insiders claim the club will spend 200 million in January [S1].; unsupported claim (not in cited evidence: rival, juventus): Rival scouts from Juventus w
- **factcheck** (rev 0) on *Chelsea: the Touchline Take on the dugout*: unsupported claim (not in cited evidence: insiders, 200, january): Insiders claim the club will spend 200 million in January [S1].; unsupported claim (not in cited evidence: rival, juventus): Rival scouts from Juventus w
- **factcheck** (rev 0) on *Newcastle: the Touchline Take on the transfer talk*: unsupported claim (not in cited evidence: insiders, 200): Insiders claim the club will spend 200 million in January [S1].; unsupported claim (not in cited evidence: rival, juventus): Rival scouts from Juventus were repor
- **editor** (rev 0) on *Celtic: the Touchline Take on the transfer talk*: too short: 69 words (minimum 90)
- **editor** (rev 1) on *Celtic: the Touchline Take on the transfer talk*: too short: 64 words (minimum 90)
- **editor** (rev 2) on *Celtic: the Touchline Take on the transfer talk*: too short: 66 words (minimum 90)
- **factcheck** (rev 0) on *Arsenal: the Touchline Take on the transfer talk*: unsupported claim (not in cited evidence: insiders, 200, january): Insiders claim the club will spend 200 million in January [S1].; unsupported claim (not in cited evidence: rival, juventus): Rival scouts from Juventus w
- **factcheck** (rev 0) on *Aston Villa: the Touchline Take on the injury news*: contradicted claim (wrong team for 0 draw: Fulham (the evidence gives it to Aston Villa)): In our synthetic sample results, Fulham have 3 wins, 0 draws and 2 defeats from their last 5 league games: 9 points, 10 scored an
- **factcheck** (rev 0) on *Brentford: the Touchline Take on the refereeing row*: unsupported claim (not in cited evidence: insiders, 200, january): Insiders claim the club will spend 200 million in January [S1].; unsupported claim (not in cited evidence: rival, juventus): Rival scouts from Juventus w

## Fact-checker on labelled claims (positive class = unsupported)

`dev` cases were used while building the relation checks; `heldout` cases were written afterwards and not tuned on.

| Checker / split | Cases | Accuracy | Precision | Recall | F1 | False-positive rate |
|---|---|---|---|---|---|---|
| token_only/dev | 42 | 0.643 | 1.0 | 0.286 | 0.444 | 0.0 |
| token_only/heldout | 18 | 0.611 | 1.0 | 0.3 | 0.462 | 0.0 |
| relation_aware/dev | 42 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 |
| relation_aware/heldout | 18 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 |

Correct verdicts per category:

| Category | token_only/dev | token_only/heldout | relation_aware/dev | relation_aware/heldout |
|---|---|---|---|---|
| correct | 19/19 | 8/8 | 19/19 | 8/8 |
| draw_vs_win | 0/2 | 0/1 | 2/2 | 1/1 |
| flipped_winner | 0/6 | 0/2 | 6/6 | 2/2 |
| formal_alias | 2/2 | - | 2/2 | - |
| invented_entity | 1/1 | 1/1 | 1/1 | 1/1 |
| invented_number | 2/2 | 1/1 | 2/2 | 1/1 |
| nickname | 1/1 | - | 1/1 | - |
| no_citation | 1/1 | - | 1/1 | - |
| swapped_probability | 0/1 | 0/1 | 1/1 | 1/1 |
| swapped_stats | 0/2 | 0/1 | 2/2 | 1/1 |
| unknown_citation | 1/1 | - | 1/1 | - |
| wrong_score | 0/1 | 1/1 | 1/1 | 1/1 |
| wrong_unit | 0/3 | 0/2 | 3/3 | 2/2 |

## Classifier (lexicon) vs labelled fixtures

| Field | Accuracy |
|---|---|
| league | 1.0 |
| topic | 0.968 |
| sentiment | 0.839 |
| teams | 1.0 |

Misses:
- Celtic boss Rory Quinn signs new contrac: topic expected 'manager', got 'transfer'
- Aston Villa stun Manchester City with 1-: sentiment expected 'positive', got 'neutral'
- Crystal Palace winger handed three-match: sentiment expected 'negative', got 'neutral'
- Arsenal had a long transfer shortlist to: sentiment expected 'neutral', got 'positive'
- The part-timers who won three Wembley fi: sentiment expected 'positive', got 'neutral'
- Midfielder reveals heart treatment at Wo: sentiment expected 'neutral', got 'positive'

## Analyst match-outcome model vs baselines

Chronological split: 832 train / 278 test matches (test period 2024-10-27 to 2025-05-06).

| Metric | Logistic regression | Majority class | Class prior |
|---|---|---|---|
| accuracy | 0.5432 | 0.4496 | 0.4496 |
| precision_macro | 0.3602 | 0.1499 | 0.1499 |
| recall_macro | 0.4679 | 0.3333 | 0.3333 |
| f1_macro | 0.4058 | 0.2068 | 0.2068 |
| roc_auc_ovr | 0.6708 | 0.5 | 0.5 |
| log_loss | 0.986 | 7.6035 | 1.078 |

Confusion matrix (rows = actual, cols = predicted, order H/D/A):

      99     0    26
      48     0    20
      33     0    52

Beats baseline: **yes**

## Photo tagger (from `reports/photo_tagger.json`)

**Data: synthetic.** Procedurally generated scenes (`touchline_takes/tools/synthetic_photos.py`). These scores show the pipeline works; they say little about real match photos. Add real photos under `data/photos/<tag>/` and retrain.

Test accuracy on 60 held-out photos:

| Model | Accuracy |
|---|---|
| VGG16 transfer | 1.0 |
| VGG16 fine-tuned | 1.0 |
| colour histogram | 0.8 |
| majority class | 0.25 |
