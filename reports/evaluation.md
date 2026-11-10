# Touchline Takes evaluation report

Fixture stories: 10 · guardrail (every published claim sourced): **PASS**

## Newsroom quality per writer configuration

| Metric | template_writer | scripted_llm_writer |
|---|---|---|
| drafts | 12 | 12 |
| published | 11 | 11 |
| rejected | 1 | 1 |
| claims_with_source_share_first_pass | 1.0 | 0.91 |
| claims_with_source_share_published | 1.0 | 1.0 |
| unsupported_claims_caught | 0 | 9 |
| factcheck_bounces | 0 | 3 |
| editor_reviews | 14 | 14 |
| editor_rejection_rate | 0.214 | 0.214 |
| retries_total | 2 | 5 |
| retries_mean | 0.167 | 0.417 |
| retries_max | 2 | 2 |
| llm_calls_per_article | 0.0 | 1.417 |
| cost_usd_per_article | 0.0 | 0.0 |
| projected_cost_usd_per_article_claude_opus_5_5 | 0.0 | 0.009065 |
| tokens_per_article | 0.0 | 1126.6 |
| agent_latency_s_per_article | 0.0052 | 0.0077 |
| pipeline_s_per_article | 0.0332 | 0.0359 |
| expectations passed | 10/10 | 10/10 |

### Rejections logged: template_writer

- **editor** (rev 0) on *Real Madrid v Sevilla: the Touchline Take*: too short: 85 words (minimum 90)
- **editor** (rev 1) on *Real Madrid v Sevilla: the Touchline Take*: too short: 83 words (minimum 90)
- **editor** (rev 2) on *Real Madrid v Sevilla: the Touchline Take*: too short: 82 words (minimum 90)

### Rejections logged: scripted_llm_writer

- **factcheck** (rev 0) on *Arsenal v Chelsea: the Touchline Take*: unsupported claim (not in cited evidence: insiders, 200, january): Insiders claim the club will spend 200 million in January [S1].; unsupported claim (not in cited evidence: rival, juventus): Rival scouts from Juventus w
- **editor** (rev 0) on *Real Madrid v Sevilla: the Touchline Take*: too short: 85 words (minimum 90)
- **editor** (rev 1) on *Real Madrid v Sevilla: the Touchline Take*: too short: 83 words (minimum 90)
- **editor** (rev 2) on *Real Madrid v Sevilla: the Touchline Take*: too short: 82 words (minimum 90)
- **factcheck** (rev 0) on *Tottenham: what the dugout story really means*: unsupported claim (not in cited evidence: insiders, 200, january): Insiders claim the club will spend 200 million in January [S1].; unsupported claim (not in cited evidence: rival, juventus): Rival scouts from Juventus w
- **factcheck** (rev 0) on *Preview: Arsenal v Liverpool, who has the edge?*: unsupported claim (not in cited evidence: insiders, 200, january): Insiders claim the club will spend 200 million in January [S1].; unsupported claim (not in cited evidence: rival, juventus): Rival scouts from Juventus w

## Classifier (lexicon) vs labelled fixtures

| Field | Accuracy |
|---|---|
| league | 1.0 |
| topic | 1.0 |
| sentiment | 1.0 |
| teams | 1.0 |

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
