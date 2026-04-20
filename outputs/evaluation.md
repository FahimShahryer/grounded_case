# Evaluation — v1 vs v2

`v1` is the pre-learning baseline (generated with no learned patterns). `v2` is post-learning (the current active template with mined rules enforced by the verifier retry loop). Both run through diskcache so repeat evaluations are free.


## title_review_summary
v1: draft #33 (template_version=0) · v2: draft #34 (template_version=1)

| Metric | v1 | v2 | Δ |
|---|---|---|---|
| Grounded-claim coverage        | 0.86 (18/21) | 0.95 (20/21) | +0.10 ↑ |
| Structural fidelity            | 0.40 (2/5) | 0.80 (4/5) | +0.40 ↑ |
| Rule compliance                | 0.33 (3/9) | 0.67 (6/9) | +0.33 ↑ |
| Citation accuracy              | 0.19 (3/16) | 0.24 (4/17) | +0.05 ↑ |
| Hallucination rate             | 0.00 (0/12) | 0.07 (1/15) | +0.07 ↓ |

## case_status_memo
v1: draft #35 (template_version=0) · v2: draft #36 (template_version=1)

| Metric | v1 | v2 | Δ |
|---|---|---|---|
| Grounded-claim coverage        | 0.88 (14/16) | 0.88 (14/16) | +0.00 |
| Structural fidelity            | 0.67 (2/3) | 0.67 (2/3) | +0.00 |
| Rule compliance                | 0.80 (4/5) | 0.80 (4/5) | +0.00 |
| Citation accuracy              | 0.95 (19/20) | 0.56 (10/18) | -0.39 ↓ |
| Hallucination rate             | 0.00 (0/15) | 0.00 (0/14) | +0.00 |
