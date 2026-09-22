# 📊 Benchmark Results: HumanEval

* **Model**: `master-lite`
* **Endpoint**: `http://localhost:12468/v1`
* **Samples Evaluated**: 25
* **Execution Time**: 436.4 seconds (~7.3 min)
* **Log Directory**: `/home/sumergoconicio/Documents/Code/EvalsBench/logs/20260922_master-lite_humaneval`
* **Timestamp**: 2026-09-22 12:08:22

## 🎯 Evaluated Metrics

| Metric Name | Score |
| :--- | :--- |
| `accuracy` | **0.840** |
| `stderr` | **0.075** |


## 📝 Raw Inspect Output
```text
Loading dataset openai/openai_humaneval from Hugging Face...

Saving the dataset (0/1 shards):   0%|          | 0/164 [00:00<?, ? examples/s]
Saving the dataset (1/1 shards): 100%|██████████| 164/164 [00:00<00:00, 42325.00 examples/s]
Saving the dataset (1/1 shards): 100%|██████████| 164/164 [00:00<00:00, 40438.91 examples/s]
Monitor from another shell: inspect ctl task list   (inspect ctl --help)
time="2026-09-22T12:01:10+02:00" level=warning msg="No services to build"
Service default: using local image 'aisiuk/inspect-tool-support'.

╭──────────────────────────────────────────────────────────────────────────────╮
│humaneval (25 samples): openai/master-lite                                    │
╰──────────────────────────────────────────────────────────────────────────────╯
max_connections: 1, max_tool_output: 16384, reasoning_history: none,            
sample_shuffle: 42, turn_limit: 5, time_limit: 120, dataset:                    
openai/openai_humaneval                                                         
                                                                                
total time:           0:07:11                                                   
openai/master-lite    24,523 tokens [I: 4,899, CW: 0, CR: 9,100, O: 10,524]     
                                                                                
verify                                                                          
accuracy  0.840                                                                 
stderr    0.075                                                                 
                                                                                
Log:                                                                            
logs/20260922_master-lite_humaneval/2026-09-22T10-01-10-00-00_humaneval_Q89Mn3Bx
tFebBhBvzHUJPu.eval                                                             
                                                                                
```
