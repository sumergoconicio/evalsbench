# 📊 Benchmark Results: BFCL

* **Model**: `master-lite`
* **Endpoint**: `http://localhost:12468/v1`
* **Samples Evaluated**: 25
* **Execution Time**: 185.7 seconds (~3.1 min)
* **Log Directory**: `/home/sumergoconicio/Documents/Code/EvalsBench/logs/20260922_master-lite_bfcl`
* **Timestamp**: 2026-09-22 12:11:46

## 🎯 Evaluated Metrics

| Metric Name | Score |
| :--- | :--- |
| `│` | **80.000** |


## 📝 Raw Inspect Output
```text
Monitor from another shell: inspect ctl task list   (inspect ctl --help)
╭──────────────────────────────────────────────────────────────────────────────╮
│bfcl (25 samples): openai/master-lite                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭───────────────────── Traceback (most recent call last) ──────────────────────╮
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_ai/_eval/ta… │
│ in task_run                                                                  │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_ai/_eval/ta… │
│ in run                                                                       │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/anyio/_core/_tasks.… │
│ in _run_coro                                                                 │
│                                                                              │
│   272 │   │                                                                  │
│   273 │   │   with self._cancel_scope:                                       │
│   274 │   │   │   try:                                                       │
│ ❱ 275 │   │   │   │   retval = await self._coro                              │
│   276 │   │   │   except BaseException as exc:                               │
│   277 │   │   │   │   self._exception = exc                                  │
│   278 │   │   │   │   raise                                                  │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_ai/_eval/ta… │
│ in run_one                                                                   │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_ai/_eval/ta… │
│ in run_sample                                                                │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_ai/_eval/ta… │
│ in task_run_sample                                                           │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_ai/_eval/ta… │
│ in task_run_sample                                                           │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_evals/bfcl/… │
│ in score                                                                     │
│                                                                              │
│   178 │   │   elif config.matching_function == "relevance":                  │
│   179 │   │   │   return relevance_match(state, target)                      │
│   180 │   │   elif config.matching_function == "multi_turn":                 │
│ ❱ 181 │   │   │   return multi_turn_match(state, target)                     │
│   182 │   │   else:                                                          │
│   183 │   │   │   raise ValueError(f"Unknown scorer type: {config.matching_f │
│   184                                                                        │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_evals/bfcl/… │
│ in multi_turn_match                                                          │
│                                                                              │
│    74 │                                                                      │
│    75 │   # Response check: GT results ⊆ cumulative model results (per turn) │
│    76 │   cumulative_model_results: list[Any] = []                           │
│ ❱  77 │   for turn_idx, (gt_turn_results, model_turn_results) in enumerate(  │
│    78 │   │   zip(gt_results_per_turn, model_results, strict=True)           │
│    79 │   ):                                                                 │
│    80 │   │   cumulative_model_results.extend(model_turn_results)            │
╰──────────────────────────────────────────────────────────────────────────────╯
ValueError: zip() argument 2 is shorter than argument 1                         
                                                                                
Task interrupted (no samples completed before interruption)                     
                                                                                
Log:                                                                            
logs/20260922_master-lite_bfcl/2026-09-22T10-08-43-00-00_bfcl_VQjx23DWAjLXiUBRFn
9uex.eval                                                                       
                                                                                
```
