# 📊 Benchmark Results: IFEval

* **Model**: `master-lite`
* **Endpoint**: `http://localhost:12468/v1`
* **Samples Evaluated**: 25
* **Execution Time**: 1096.1 seconds (~18.3 min)
* **Log Directory**: `/home/sumergoconicio/Documents/Code/EvalsBench/logs/20260922_master-lite_ifeval`
* **Timestamp**: 2026-09-22 12:00:17

## 🎯 Evaluated Metrics

| Metric Name | Score |
| :--- | :--- |
| `prompt_strict_acc` | **0.720** |
| `prompt_strict_stderr` | **0.092** |
| `prompt_loose_acc` | **0.720** |
| `prompt_loose_stderr` | **0.092** |
| `inst_strict_acc` | **0.769** |
| `inst_strict_stderr` | **0.081** |
| `inst_loose_acc` | **0.769** |
| `inst_loose_stderr` | **0.081** |
| `final_acc` | **0.745** |
| `final_stderr` | **0.099** |


## 📝 Raw Inspect Output
```text
Loading dataset google/IFEval from Hugging Face...

Saving the dataset (0/1 shards):   0%|          | 0/541 [00:00<?, ? examples/s]
Saving the dataset (1/1 shards): 100%|██████████| 541/541 [00:00<00:00, 120903.58 examples/s]
Saving the dataset (1/1 shards): 100%|██████████| 541/541 [00:00<00:00, 117821.20 examples/s]
Monitor from another shell: inspect ctl task list   (inspect ctl --help)
╭──────────────────────────────────────────────────────────────────────────────╮
│ifeval (25 samples): openai/master-lite                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
max_connections: 1, max_tool_output: 16384, reasoning_history: none,            
sample_shuffle: 42, turn_limit: 5, time_limit: 120, dataset: google/IFEval      
                                                                                
total time:           0:18:09                                                   
openai/master-lite    19,672 tokens [I: 1,256, CW: 0, CR: 8,008, O: 10,408]     
                                                                                
instruction_following                                                           
prompt_strict_acc      0.720                                                    
prompt_strict_stderr   0.092                                                    
prompt_loose_acc       0.720                                                    
prompt_loose_stderr    0.092                                                    
inst_strict_acc        0.769                                                    
inst_strict_stderr     0.081                                                    
inst_loose_acc         0.769                                                    
inst_loose_stderr      0.081                                                    
final_acc              0.745                                                    
final_stderr           0.099                                                    
                                                                                
Log:                                                                            
logs/20260922_master-lite_ifeval/2026-09-22T09-42-06-00-00_ifeval_nUtqoGjscS6qZQ
jBKbicKv.eval                                                                   
                                                                                
```
