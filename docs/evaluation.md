# Evaluation pipeline

## Why evaluate
Agent quality regresses silently: a reworded tool description or a new model version can change behaviour. The pipeline runs the **real agent loop with a real model** against **frozen fake clusters** (`eval/cases.yaml`), so results are repeatable and comparable between Bedrock Nova and Azure OpenAI.

## Rubric (0–5, one point each)
| # | Criterion | Meaning |
|---|---|---|
| 1 | `root_cause_resource` | Answer names the culprit pod/node/deployment |
| 2 | `root_cause_reason` | Answer states the correct reason (accepted keyword set) |
| 3 | `evidence` | Answer cites concrete tool evidence (exit code, event text) |
| 4 | `required_tools` | All tools a competent SRE must use were called |
| 5 | `clean_execution` | No tool errors, no duplicate calls, finished inside the step budget |

Mean over cases is the headline score. Deterministic, so it is cheap and diff-able; add an LLM-as-judge for free-text quality if you need it.

## Scenarios included
OOMKilled crash loop · ImagePullBackOff (bad tag) · Unschedulable (insufficient CPU) · Crash on missing env var (with a secret in the logs to test redaction) · Node DiskPressure eviction.

Add a case by copying a block in `eval/cases.yaml`: define `cluster` (pods/events/logs/nodes), the `question`, and the `expect` keywords.

## Running
```bash
sre-eval --provider bedrock      --out eval/results/bedrock.json
sre-eval --provider azure_openai --min-score 4.5        # exits 1 if the mean is lower (CI gate)
```
GitHub Actions: **Actions → eval → Run workflow** (OIDC credentials, see pre-req-doc §5).

## Tool fixes behind the 3.75 → 5.0 improvement
The reported jump came from fixing tool design rather than changing the model. These are the fixes implemented in `src/sre_agent/tools/registry.py`. (Per-fix score deltas were not measured separately in this repo; re-run `sre-eval` after toggling a fix to measure it.)

| Failure mode addressed | Fix | Rubric item protected |
|---|---|---|
| Model never read crashed-container logs | Description of `get_pod_logs` tells it to use `previous=true` for crashing pods | evidence / required_tools |
| Calls failed when `namespace` omitted | Defaults (`default`), and `all` supported | clean_execution |
| Model drowned in 200 healthy pods | `only_unhealthy=true` default, capped list, totals reported | reason / resource |
| Raw API dumps hit context limits | Compact JSON summaries + explicit `...[truncated N chars]` marker | evidence |
| Typos raised exceptions and aborted the run | Errors returned as actionable text (`is_error`) so the model self-corrects | clean_execution |
| Model repeated the same call | Duplicate-call detection with a corrective message | clean_execution |
| Null/empty args from the model broke calls | Argument cleaning before dispatch | clean_execution |
| Secrets in logs | Redaction before returning to the model | safety |

## Caveat
Absolute numbers depend on the model, region, temperature (`0.0` by default) and scenario set. Treat them as a regression signal for *your* configuration.
