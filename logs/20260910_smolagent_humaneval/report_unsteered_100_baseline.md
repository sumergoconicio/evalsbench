# 📊 Benchmark Results: HumanEval

* **Model**: `smolagent`
* **Endpoint**: `http://localhost:2468/v1`
* **Samples Evaluated**: 100
* **Execution Time**: 2797.2 seconds (~46.6 min)
* **Log Directory**: `/home/sumergoconicio/Documents/Code/EvalsBench/logs/20260910_smolagent_humaneval`
* **Timestamp**: 2026-09-10 21:26:04

## 🎯 Evaluated Metrics

| Metric Name | Score |
| :--- | :--- |
| `accuracy` | **0.360** |
| `stderr` | **0.048** |


## 📝 Raw Inspect Output
```text
Loading dataset openai/openai_humaneval from Hugging Face...

Saving the dataset (0/1 shards):   0%|          | 0/164 [00:00<?, ? examples/s]
Saving the dataset (1/1 shards): 100%|██████████| 164/164 [00:00<00:00, 107866.69 examples/s]
Saving the dataset (1/1 shards): 100%|██████████| 164/164 [00:00<00:00, 103625.47 examples/s]
Monitor from another shell: inspect ctl task list   (inspect ctl --help)
time="2026-09-10T20:39:30+02:00" level=warning msg="No services to build"
Service default: using local image 'aisiuk/inspect-tool-support'.

╭──────────────────────────────────────────────────────────────────────────────╮
│humaneval (100 samples): openai/smolagent                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
max_connections: 4, sample_shuffle: 42, dataset: openai/openai_humaneval        
                                                                                
total time:         0:46:33                                                     
openai/smolagent    647,305 tokens [I: 14,885, CW: 0, CR: 3,236, O: 629,184]    
                                                                                
verify                                                                          
accuracy  0.360                                                                 
stderr    0.048                                                                 
                                                                                
Log:                                                                            
logs/20260910_smolagent_humaneval/2026-09-10T18-39-30-00-00_humaneval_AV6bbG9p9g
UVQG9bf8CwwY.eval                                                               
                                                                                
```
