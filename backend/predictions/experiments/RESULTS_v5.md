# v5: model improvements

## 4. Out-of-sample dispersion

The negative-binomial alphas that price hits and blocks (0.12 / 0.08) were set by hand on the same test seasons they were scored on. Training now fits alpha for every count target from the validation split, using maximum likelihood of the NB2 (variance = mu(1 + alpha mu)) on the validation model's predictions. The alphas are saved in the skater and goalie bundles and in `metrics.json`, so they refresh with the nightly retrain (`predictions/dispersion.py`).

**The rule:**
- Alpha is clamped to [0, 1].
- A target is priced as a negative binomial only if that beats the Poisson by at least 0.0005 nats per row of validation log likelihood. Otherwise it stays Poisson (alpha 0).
- Method of moments is reported next to the MLE as a cross-check.

**Fitted alphas:**

| Target | Old (hand-set) | Nightly (validation 2024–26) | Out of sample, fold → 2024-25 / 2025-26 | Fit on the test season itself ("oracle") | Moments (nightly) |
|---|---|---|---|---|---|
| Hits | 0.12 | **0.131** | 0.142 / 0.137 | 0.138 / 0.106 | 0.090 |
| Blocked shots | 0.08 | **0.087** | 0.089 / 0.088 | 0.090 / 0.084 | 0.078 |
| Skater SOG | 0 | **0.054** | 0.048 / 0.058 | 0.059 / 0.060 | 0.038 |
| Goalie saves | 0 | **0.030** | 0.029 / 0.029 | 0.029 / 0.029 | 0.027 |
| Goalie SOG against | 0 | **0.021** | 0.020 / 0.020 | 0.020 / 0.020 | 0.019 |
| Goals, assists, points, PP points, goals against | 0 | 0 | 0 | 0 | 0 |

- **Goals, assists, points and PP points are under-dispersed** given their mean, which is expected for counts that are mostly 0/1. The likelihood peaks at alpha 0, so they stay Poisson. Nothing changed for them.
- **Moments come in lower than the MLE for hits.** The moment estimate is driven by a few large squared residuals and is noisier from season to season (0.068–0.099), so pricing uses the MLE.

**Test-season scoring** (`experiments/dispersion_eval.py`). The setup:
- `props_models` folds: train on seasons before the validation season, early-stop on it, and fit alpha on the same season. The test season is never used.
- Every skater-game is scored, about 47k per season.
- "P(over) near-mean" is the log loss at the half-point line nearest each player's mean, which is where books put their lines.

| | Poisson | Old alphas | **Fitted out of sample** | Oracle |
|---|---|---|---|---|
| Hits, log lik/row 2024-25 / 2025-26 | −1.34760 / −1.29610 | −1.34052 / −1.29188 | **−1.34044 / −1.29208** | −1.34043 / −1.29183 |
| Hits, P(over) near-mean | 0.65658 / 0.65112 | 0.65492 / 0.64950 | **0.65471 / 0.64935** | 0.65474 / 0.64964 |
| Blocks, P(over) near-mean | 0.65723 / 0.65018 | 0.65695 / 0.64965 | **0.65694 / 0.64961** | 0.65694 / 0.64963 |
| SOG, P(over) near-mean | 0.66209 / 0.66711 | (Poisson) | **0.66150 / 0.66708** | 0.66139 / 0.66708 |
| Goalie saves, P(over) near-mean (2.6k rows/season) | 0.69196 / 0.69359 | (Poisson) | 0.69132 / 0.69412 | 0.69132 / 0.69413 |

**Against prop prices** (`props_benchmark`, Shin vig removal, ESPN history, 2024-25 + 2025-26):

| Market | Lines | Model − market log loss: Poisson / old / **fitted** | Flat-bet ROI at 2%+ edge: Poisson / old / **fitted** (95% CI for fitted) |
|---|---|---|---|
| **Hits** | 2.8k | −0.0045 / −0.0063 / **−0.0064** (CI −0.0119 to −0.0007) | +3.5% / +7.7% / **+7.8%** (+2.5% to +13.1%) |
| **Blocked shots** | 7.3k | −0.0033 / −0.0044 / **−0.0044** (CI −0.0074 to −0.0014) | +4.4% / +4.8% / **+4.9%** (+1.6% to +8.0%); 2025-26 +1.9% → +3.5% |
| Saves | 3.3k | −0.0025 / (Poisson) / **−0.0045** (CI −0.0094 to +0.0006) | +5.1% / (Poisson) / **+6.7%** (+2.4% to +11.0%); still about 0 in 2025-26 |
| Shots on goal | 6.1k | +0.0015 / (Poisson) / +0.0013 | −0.7% / (Poisson) / −2.7% |

**Reading this honestly:**
- **The fitted alphas match the hand-set ones where those existed, and the market edge holds without the in-sample choice.** Hits and blocks with out-of-sample alphas are as good as the old values on log loss and ROI. The hits edge over the market (−0.0064, CI excluding 0) no longer depends on an alpha picked on those seasons.
- **The selection optimism in the old values is real but small.** The old hits alpha of 0.12 sits between the two test seasons' own optima (0.138, 0.106), which is what tuning on them would produce. Out of sample, 2025-26 wanted 0.137 against its oracle of 0.106. That cost 0.0002 nats per row of likelihood against the old value, and P(over) and market results are unchanged. Hits dispersion moves from season to season (scorer and arena effects), and a nightly refit tracks that better than a constant.
- **Goalie saves are clearly over-dispersed** (alpha 0.03 at about 25 saves makes the variance 1.75× the Poisson's) and were priced as Poisson until now. On market lines the NB improves log loss by 0.0020, and ROI rises at the 2% edge. The model was overpricing the over in its top fifth (0.614 predicted vs 0.552 actual; with the NB, 0.573). The near-mean scores on the 2.6k-row eval split one season each way, which is noise at that size. The market comparison is what supports it.
- **SOG is a wash, and it's the one to watch.** The NB is slightly better on the all-player likelihood and P(over) in both seasons, and on market log loss (+0.0015 → +0.0013). But it shifts the mean P(over) on market lines from 0.517 to 0.506, against an actual rate of 0.516. Flat-bet ROI drops from −0.7% to −2.7%. That isn't enough to override the validation rule, and the market beats the model on SOG either way, so it isn't a betting market. If SOG ever gets bet, revisit this.
- **No target got worse on P(over) log loss out of sample, so no NB target was restricted by hand.** The 0.0005-nat gate keeps every 0/1-type stat on the Poisson.

**What changed:**
- `_fit_count_models` fits `fit_alpha(y, mu)` on the validation predictions. It runs in both the nightly `train_models` job and `python -m predictions.train`, with no extra model fits.
- `predict.prop_dispersion()` reads the bundles. It is used by the live props endpoint and by the prediction-log scorer (through `prop_probability`).
- `config.PROP_DISPERSION` is now only the fallback for bundles trained before this change.
- `props_models` saves the per-fold alpha. `props_benchmark --fitted-alpha` prices with it.

**Caveats:**
- **The validation predictions come from the early-stopped model.** The number of trees was chosen on the same rows, which slightly understates residual variance. The served model is refit on all games, which leaves slightly less. The two effects run in opposite directions, and both are small.
- **The prediction-log scorer prices old logs with the current bundle's alphas.** The log stores expected values, not alphas. Nightly alphas move in the third decimal place, so this barely matters. A strictly frozen forward test should pin the bundle, as noted in v4.
