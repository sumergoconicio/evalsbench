# 📊 Benchmark Results: IFEval

* **Model**: `nemotron3.5-lightning`
* **Endpoint**: `http://localhost:2468/v1`
* **Samples Evaluated**: 1
* **Execution Time**: 402.8 seconds (~6.7 min)
* **Log Directory**: `/home/sumergoconicio/Documents/Code/EvalsBench/logs/20260824_nemotron3.5-lightning_ifeval`
* **Timestamp**: 2026-08-24 22:25:17

## 🎯 Evaluated Metrics

| Metric Name | Score |
| :--- | :--- |
| `prompt_strict_acc` | **1.000** |
| `prompt_strict_stderr` | **0.000** |
| `prompt_loose_acc` | **1.000** |
| `prompt_loose_stderr` | **0.000** |
| `inst_strict_acc` | **1.000** |
| `inst_strict_stderr` | **0.000** |
| `inst_loose_acc` | **1.000** |
| `inst_loose_stderr` | **0.000** |
| `final_acc` | **1.000** |
| `final_stderr` | **0.000** |


## 📝 Raw Inspect Output
```text
Loading dataset google/IFEval from Hugging Face...
╭──────────────────────────────────────────────────────────────────────────────╮
│ifeval (1 sample): openai/nemotron3.5-lightning                               │
╰──────────────────────────────────────────────────────────────────────────────╯
max_connections: 8, sample_shuffle: 42, dataset: google/IFEval                  
                                                                                
total time:                         0:06:36                                     
openai/nemotron3.5-lightning        4,644 tokens [I: 75, O: 4,569, R: 0]        
                                                                                
instruction_following                                                           
prompt_strict_acc      1.000                                                    
prompt_strict_stderr   0.000                                                    
prompt_loose_acc       1.000                                                    
prompt_loose_stderr    0.000                                                    
inst_strict_acc        1.000                                                    
inst_strict_stderr     0.000                                                    
inst_loose_acc         1.000                                                    
inst_loose_stderr      0.000                                                    
final_acc              1.000                                                    
final_stderr           0.000                                                    
                                                                                
Log:                                                                            
logs/20260824_nemotron3.5-lightning_ifeval/2026-08-24T20-18-39-00-00_ifeval_f893
GXornTjL35m9RQ3LzW.eval                                                         
                                                                                

Saving the dataset (0/1 shards):   0%|          | 0/541 [00:00<?, ? examples/s]
Saving the dataset (1/1 shards): 100%|██████████| 541/541 [00:00<00:00, 138546.74 examples/s]
Saving the dataset (1/1 shards): 100%|██████████| 541/541 [00:00<00:00, 133438.31 examples/s]
Monitor from another shell: inspect ctl task list   (inspect ctl --help)

```
