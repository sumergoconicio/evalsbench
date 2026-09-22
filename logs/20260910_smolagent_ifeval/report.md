# 📊 Benchmark Results: IFEval

* **Model**: `smolagent`
* **Endpoint**: `http://localhost:2468/v1`
* **Samples Evaluated**: 100
* **Execution Time**: 189.7 seconds (~3.2 min)
* **Log Directory**: `/home/sumergoconicio/Documents/Code/EvalsBench/logs/20260910_smolagent_ifeval`
* **Timestamp**: 2026-09-10 20:39:23

## 🎯 Evaluated Metrics

| Metric Name | Score |
| :--- | :--- |
| `prompt_strict_acc` | **0.910** |
| `prompt_strict_stderr` | **0.029** |
| `prompt_loose_acc` | **0.930** |
| `prompt_loose_stderr` | **0.026** |
| `inst_strict_acc` | **0.931** |
| `inst_strict_stderr` | **0.023** |
| `inst_loose_acc` | **0.945** |
| `inst_loose_stderr` | **0.021** |
| `final_acc` | **0.929** |
| `final_stderr` | **0.032** |


## 📝 Raw Inspect Output
```text
Loading dataset google/IFEval from Hugging Face...

Saving the dataset (0/1 shards):   0%|          | 0/541 [00:00<?, ? examples/s]
Saving the dataset (1/1 shards): 100%|██████████| 541/541 [00:00<00:00, 277907.96 examples/s]
Saving the dataset (1/1 shards): 100%|██████████| 541/541 [00:00<00:00, 267490.09 examples/s]
Monitor from another shell: inspect ctl task list   (inspect ctl --help)
╭──────────────────────────────────────────────────────────────────────────────╮
│ifeval (100 samples): openai/smolagent                                        │
╰──────────────────────────────────────────────────────────────────────────────╯
max_connections: 4, sample_shuffle: 42, dataset: google/IFEval                  
                                                                                
total time:          0:03:05                                                    
openai/smolagent     59,335 tokens [I: 5,302, CW: 0, CR: 429, O: 53,604]        
                                                                                
instruction_following                                                           
prompt_strict_acc      0.910                                                    
prompt_strict_stderr   0.029                                                    
prompt_loose_acc       0.930                                                    
prompt_loose_stderr    0.026                                                    
inst_strict_acc        0.931                                                    
inst_strict_stderr     0.023                                                    
inst_loose_acc         0.945                                                    
inst_loose_stderr      0.021                                                    
final_acc              0.929                                                    
final_stderr           0.032                                                    
                                                                                
Log:                                                                            
logs/20260910_smolagent_ifeval/2026-09-10T18-36-18-00-00_ifeval_BsrwY3r6R2h4UVax
vmcJnJ.eval                                                                     
                                                                                
```
