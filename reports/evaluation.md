# Touchline Takes evaluation report

Fixture stories: 25 · guardrail (every published claim sourced): **PASS**

## Newsroom quality per writer configuration

| Metric | template_writer | scripted_llm_writer |
|---|---|---|
| drafts | 26 | 26 |
| published | 21 | 21 |
| rejected | 5 | 5 |
| claims_with_source_share_first_pass | 1.0 | 0.88 |
| claims_with_source_share_published | 1.0 | 1.0 |
| unsupported_claims_caught | 0 | 32 |
| contradictions_caught | 0 | 14 |
| factcheck_bounces | 0 | 10 |
| editor_reviews | 36 | 36 |
| editor_rejection_rate | 0.417 | 0.417 |
| retries_total | 10 | 20 |
| retries_mean | 0.385 | 0.769 |
| retries_max | 2 | 2 |
| llm_calls_per_article | 0.0 | 1.769 |
| cost_usd_per_article | 0.0 | 0.0 |
| projected_cost_usd_per_article_claude_opus_5_5 | 0.0 | 0.011445 |
| tokens_per_article | 0.0 | 1468.9 |
| agent_latency_s_per_article | 0.0089 | 0.0137 |
| pipeline_s_per_article | 0.0303 | 0.0379 |
| expectations passed | 19/19 | 19/19 |

### Rejections logged: template_writer

- **editor** (rev 0) on *Real Madrid v Sevilla: the Touchline Take*: too short: 85 words (minimum 90)
- **editor** (rev 1) on *Real Madrid v Sevilla: the Touchline Take*: too short: 83 words (minimum 90)
- **editor** (rev 2) on *Real Madrid v Sevilla: the Touchline Take*: too short: 82 words (minimum 90)
- **editor** (rev 0) on *Paris Saint-Germain v Marseille: the Touchline Take*: too short: 82 words (minimum 90)
- **editor** (rev 1) on *Paris Saint-Germain v Marseille: the Touchline Take*: too short: 83 words (minimum 90)
- **editor** (rev 2) on *Paris Saint-Germain v Marseille: the Touchline Take*: too short: 83 words (minimum 90)
- **editor** (rev 0) on *Juventus v Napoli: the Touchline Take*: too short: 87 words (minimum 90)
- **editor** (rev 1) on *Juventus v Napoli: the Touchline Take*: too short: 84 words (minimum 90)
- **editor** (rev 2) on *Juventus v Napoli: the Touchline Take*: too short: 86 words (minimum 90)
- **editor** (rev 0) on *Bayern Munich v Bayer Leverkusen: the Touchline Take*: too short: 81 words (minimum 90)
- **editor** (rev 1) on *Bayern Munich v Bayer Leverkusen: the Touchline Take*: too short: 79 words (minimum 90)
- **editor** (rev 2) on *Bayern Munich v Bayer Leverkusen: the Touchline Take*: too short: 82 words (minimum 90)
- **editor** (rev 0) on *Celtic: what the transfer story really means*: too short: 82 words (minimum 90)
- **editor** (rev 1) on *Celtic: what the transfer story really means*: too short: 77 words (minimum 90)
- **editor** (rev 2) on *Celtic: what the transfer story really means*: too short: 79 words (minimum 90)

### Rejections logged: scripted_llm_writer

- **factcheck** (rev 0) on *Arsenal v Chelsea: the Touchline Take*: unsupported claim (not in cited evidence: insiders, 200, january): Insiders claim the club will spend 200 million in January [S1].; unsupported claim (not in cited evidence: rival, juventus): Rival scouts from Juventus w
- **factcheck** (rev 0) on *Manchester City v Wolves: the Touchline Take*: contradicted claim (contradicts source: claim says Wolves beat Manchester City 4-0, source says Manchester City beat Wolves 4-0): Wolves beat Manchester City 4-0, as reported by Eval Wire [S1].; contradicted claim (wrong
- **editor** (rev 0) on *Real Madrid v Sevilla: the Touchline Take*: too short: 85 words (minimum 90)
- **editor** (rev 1) on *Real Madrid v Sevilla: the Touchline Take*: too short: 83 words (minimum 90)
- **editor** (rev 2) on *Real Madrid v Sevilla: the Touchline Take*: too short: 82 words (minimum 90)
- **factcheck** (rev 0) on *Manchester United v Fulham: the Touchline Take*: contradicted claim (contradicts source: claim says Manchester United beat Fulham 2-1, source says Fulham beat Manchester United 2-1): Manchester United beat Fulham 2-1, as reported by Eval Wire [S1].; contradicted claim 
- **editor** (rev 0) on *Paris Saint-Germain v Marseille: the Touchline Take*: too short: 82 words (minimum 90)
- **editor** (rev 1) on *Paris Saint-Germain v Marseille: the Touchline Take*: too short: 83 words (minimum 90)
- **editor** (rev 2) on *Paris Saint-Germain v Marseille: the Touchline Take*: too short: 83 words (minimum 90)
- **editor** (rev 0) on *Juventus v Napoli: the Touchline Take*: too short: 87 words (minimum 90)
- **editor** (rev 1) on *Juventus v Napoli: the Touchline Take*: too short: 84 words (minimum 90)
- **editor** (rev 2) on *Juventus v Napoli: the Touchline Take*: too short: 86 words (minimum 90)
- **factcheck** (rev 0) on *Newcastle v Southampton: the Touchline Take*: contradicted claim (contradicts source: claim says Southampton beat Newcastle 5-0, source says Newcastle beat Southampton 5-0): Southampton beat Newcastle 5-0, as reported by Eval Wire [S1].; unsupported claim (not in ci
- **editor** (rev 0) on *Bayern Munich v Bayer Leverkusen: the Touchline Take*: too short: 81 words (minimum 90)
- **editor** (rev 1) on *Bayern Munich v Bayer Leverkusen: the Touchline Take*: too short: 79 words (minimum 90)
- **editor** (rev 2) on *Bayern Munich v Bayer Leverkusen: the Touchline Take*: too short: 82 words (minimum 90)
- **factcheck** (rev 0) on *Aston Villa v Manchester City: the Touchline Take*: contradicted claim (contradicts source: claim says Manchester City beat Aston Villa 1-0, source says Aston Villa beat Manchester City 1-0): Manchester City beat Aston Villa 1-0, as reported by Eval Wire [S1].; contradict
- **factcheck** (rev 0) on *Tottenham: what the dugout story really means*: unsupported claim (not in cited evidence: insiders, 200, january): Insiders claim the club will spend 200 million in January [S1].; unsupported claim (not in cited evidence: rival, juventus): Rival scouts from Juventus w
- **factcheck** (rev 0) on *Chelsea: what the dugout story really means*: unsupported claim (not in cited evidence: insiders, 200, january): Insiders claim the club will spend 200 million in January [S1].; unsupported claim (not in cited evidence: rival, juventus): Rival scouts from Juventus w
- **factcheck** (rev 0) on *Newcastle: what the transfer story really means*: unsupported claim (not in cited evidence: insiders, 200): Insiders claim the club will spend 200 million in January [S1].; unsupported claim (not in cited evidence: rival, juventus): Rival scouts from Juventus were repor
- **editor** (rev 0) on *Celtic: what the transfer story really means*: too short: 82 words (minimum 90)
- **editor** (rev 1) on *Celtic: what the transfer story really means*: too short: 77 words (minimum 90)
- **editor** (rev 2) on *Celtic: what the transfer story really means*: too short: 79 words (minimum 90)
- **factcheck** (rev 0) on *Aston Villa: what the injury story really means*: contradicted claim (wrong team for 0 draw: Fulham (the evidence gives it to Aston Villa)): In our synthetic sample results, Fulham have 3 wins, 0 draws and 2 defeats from their last 5 league games: 9 points, 10 scored an
- **factcheck** (rev 0) on *Brentford: what the refereeing story really means*: unsupported claim (not in cited evidence: insiders, 200, january): Insiders claim the club will spend 200 million in January [S1].; unsupported claim (not in cited evidence: rival, juventus): Rival scouts from Juventus w

## Fact-checker on labelled claims (positive class = unsupported)

`dev` cases were used while building the relation checks; `heldout` cases were written afterwards and not tuned on.

| Checker / split | Cases | Accuracy | Precision | Recall | F1 | False-positive rate |
|---|---|---|---|---|---|---|
| token_only/dev | 38 | 0.632 | 1.0 | 0.263 | 0.417 | 0.0 |
| token_only/heldout | 18 | 0.611 | 1.0 | 0.3 | 0.462 | 0.0 |
| relation_aware/dev | 38 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 |
| relation_aware/heldout | 18 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 |

Correct verdicts per category:

| Category | token_only/dev | token_only/heldout | relation_aware/dev | relation_aware/heldout |
|---|---|---|---|---|
| correct | 19/19 | 8/8 | 19/19 | 8/8 |
| draw_vs_win | 0/2 | 0/1 | 2/2 | 1/1 |
| flipped_winner | 0/5 | 0/2 | 5/5 | 2/2 |
| invented_entity | 1/1 | 1/1 | 1/1 | 1/1 |
| invented_number | 2/2 | 1/1 | 2/2 | 1/1 |
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
| topic | 0.96 |
| sentiment | 0.92 |
| teams | 1.0 |

Misses:
- Celtic boss Rory Quinn signs new contrac: topic expected 'manager', got 'transfer'
- Aston Villa stun Manchester City with 1-: sentiment expected 'positive', got 'neutral'
- Crystal Palace winger handed three-match: sentiment expected 'negative', got 'neutral'

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
