window.LEADERBOARD_DATA = {
  "schema_version": "1.0",
  "models": {
    "smolagent": {
      "id": "smolagent",
      "name": "smolagent",
      "is_cloud": false,
      "specs": {
        "architecture": "Transformer",
        "attention_layers": 32,
        "num_kv_heads": 8,
        "head_dim": 128,
        "context_window": 131072,
        "kv_bytes_per_token_per_gpu": 8192,
        "vram_weights_gib": 20.0,
        "size_class": "Mid-Weight (14B-35B)",
        "huggingface_url": "https://huggingface.co/models?search=smolagent"
      },
      "benchmarks": {
        "IFEval": {
          "scores": {
            "prompt_strict_acc": 0.91,
            "prompt_strict_stderr": 0.029,
            "prompt_loose_acc": 0.93,
            "prompt_loose_stderr": 0.026,
            "inst_strict_acc": 0.931,
            "inst_strict_stderr": 0.023,
            "inst_loose_acc": 0.945,
            "inst_loose_stderr": 0.021,
            "final_acc": 0.929,
            "final_stderr": 0.032
          },
          "duration_seconds": 189.71,
          "timestamp": "2026-09-10 20:39:27",
          "prompt_strict_acc": 0.91,
          "prompt_strict_stderr": 0.029,
          "prompt_loose_acc": 0.93,
          "prompt_loose_stderr": 0.026,
          "inst_strict_acc": 0.931,
          "inst_strict_stderr": 0.023,
          "inst_loose_acc": 0.945,
          "inst_loose_stderr": 0.021,
          "final_acc": 0.929,
          "final_stderr": 0.032
        },
        "HumanEval": {
          "scores": {
            "\u2502": 1783.0,
            "NotFoundError:": 404.0
          },
          "duration_seconds": 9.99,
          "timestamp": "2026-09-10 22:17:47",
          "accuracy": 0.6,
          "stderr": 0.163
        },
        "HumanEval-10": {
          "scores": {
            "accuracy": 0.6,
            "stderr": 0.163
          },
          "duration_seconds": 172.0,
          "timestamp": "2026-09-10 22:22:46"
        },
        "BFCL": {
          "\u2502": 404.0,
          "Python": 3.0
        }
      }
    },
    "Holo 3.1 35B": {
      "id": "Holo 3.1 35B",
      "name": "Holo 3.1 35B",
      "is_cloud": false,
      "specs": {
        "architecture": "LlamaForCausalLM",
        "attention_layers": 40,
        "num_kv_heads": 8,
        "head_dim": 128,
        "context_window": 131072,
        "kv_bytes_per_token_per_gpu": 20480,
        "vram_weights_gib": 20.4,
        "size_class": "Dense Workhorse (35B)",
        "huggingface_url": "https://huggingface.co/models?search=Holo"
      },
      "benchmarks": {
        "AgentBench": {
          "accuracy": 0.2,
          "stderr": 0.082
        },
        "HumanEval": {
          "accuracy": 0.96,
          "stderr": 0.04
        },
        "IFEval": {
          "prompt_strict_acc": 0.88,
          "prompt_strict_stderr": 0.066,
          "prompt_loose_acc": 0.92,
          "prompt_loose_stderr": 0.055,
          "inst_strict_acc": 0.923,
          "inst_strict_stderr": 0.041,
          "inst_loose_acc": 0.949,
          "inst_loose_stderr": 0.036,
          "final_acc": 0.918,
          "final_stderr": 0.062
        },
        "WritingBench": {
          "mean": 5.552,
          "Education": 7.133,
          "domain1_mean": 5.552,
          "Brainstorm": 4.0,
          "Abstract": 4.4,
          "Contract": 5.2,
          "domain2_mean": 5.552
        }
      }
    },
    "Bonsai 27B Fast": {
      "id": "Bonsai 27B Fast",
      "name": "Bonsai 27B Fast",
      "is_cloud": false,
      "specs": {
        "architecture": "BonsaiForCausalLM",
        "attention_layers": 32,
        "num_kv_heads": 8,
        "head_dim": 128,
        "context_window": 65536,
        "kv_bytes_per_token_per_gpu": 16384,
        "vram_weights_gib": 16.0,
        "size_class": "Dense (27B)",
        "huggingface_url": "https://huggingface.co/models?search=Bonsai"
      },
      "benchmarks": {
        "WritingBench": {
          "education": 7.2,
          "market_analysis": 5.2,
          "sales_report": 5.4,
          "technical_documentation": 6.6,
          "brainstorm": 3.8,
          "defense_script": 6.4,
          "abstract": 7.8,
          "product_proposal": 6.8,
          "curriculum_design": 7.2,
          "case_study": 6.6,
          "judgment_document": 4.8
        }
      }
    },
    "Nemotron 3.5 Lightning": {
      "id": "Nemotron 3.5 Lightning",
      "name": "Nemotron 3.5 Lightning",
      "is_cloud": false,
      "specs": {
        "architecture": "NemotronHForCausalLM",
        "attention_layers": 6,
        "mamba_layers": 23,
        "moe_layers": 23,
        "num_kv_heads": 2,
        "head_dim": 128,
        "context_window": 1048576,
        "kv_bytes_per_token_per_gpu": 1536,
        "vram_weights_gib": 10.35,
        "size_class": "Mid-Weight MoE (30B A3B)",
        "huggingface_url": "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
      },
      "benchmarks": {
        "AgentBench": {
          "accuracy": 0.24,
          "stderr": 0.087
        },
        "IFEvalCode": {
          "overall_accuracy": 0.04,
          "correctness": 0.24,
          "instruction_adherence": 0.16,
          "typescript_correctness": 0.444,
          "java_correctness": 0.2,
          "javascript_correctness": 0.0,
          "php_correctness": 0.0,
          "python_correctness": 1.0,
          "cpp_correctness": 0.0,
          "csharp_correctness": 0.0,
          "typescript_instruction": 0.222,
          "java_instruction": 0.0,
          "javascript_instruction": 0.0,
          "php_instruction": 0.0,
          "python_instruction": 1.0,
          "cpp_instruction": 0.0,
          "csharp_instruction": 0.333
        },
        "HumanEval": {
          "accuracy": 0.88,
          "stderr": 0.066
        },
        "IFEval": {
          "prompt_strict_acc": 1.0,
          "prompt_strict_stderr": 0.0,
          "prompt_loose_acc": 1.0,
          "prompt_loose_stderr": 0.0,
          "inst_strict_acc": 1.0,
          "inst_strict_stderr": 0.0,
          "inst_loose_acc": 1.0,
          "inst_loose_stderr": 0.0,
          "final_acc": 1.0,
          "final_stderr": 0.0
        },
        "PawBench": {
          "accuracy": 0.421,
          "stderr": 0.092
        }
      }
    },
    "Qwen 3.6 35B Fast": {
      "id": "Qwen 3.6 35B Fast",
      "name": "Qwen 3.6 35B Fast",
      "is_cloud": false,
      "specs": {
        "architecture": "Transformer",
        "attention_layers": 32,
        "num_kv_heads": 8,
        "head_dim": 128,
        "context_window": 131072,
        "kv_bytes_per_token_per_gpu": 8192,
        "vram_weights_gib": 20.0,
        "size_class": "Mid-Weight (14B-35B)",
        "huggingface_url": "https://huggingface.co/models?search=Qwen 3.6 35B Fast"
      },
      "benchmarks": {
        "IFEvalCode": {
          "correctness": 0.263,
          "instruction_adherence": 0.184
        },
        "IFEval": {
          "prompt_strict_acc": 0.85,
          "prompt_loose_acc": 0.88,
          "inst_strict_acc": 0.897,
          "inst_loose_acc": 0.917
        },
        "WritingBench": {
          "education": 6.4,
          "market_analysis": 6.8,
          "sales_report": 6.6,
          "technical_documentation": 5.8,
          "brainstorm": 3.4,
          "defense_script": 6.6,
          "abstract": 7.4,
          "product_proposal": 6.4,
          "curriculum_design": 6.4,
          "case_study": 7.0,
          "judgment_document": 6.0
        }
      }
    },
    "KAT-Coder V2.5 MoE": {
      "id": "KAT-Coder V2.5 MoE",
      "name": "KAT-Coder V2.5 MoE",
      "is_cloud": false,
      "specs": {
        "architecture": "KATMoEForCausalLM",
        "attention_layers": 48,
        "num_kv_heads": 4,
        "head_dim": 128,
        "context_window": 131072,
        "kv_bytes_per_token_per_gpu": 12288,
        "vram_weights_gib": 21.6,
        "size_class": "Surgical Coder (35B A3B)",
        "huggingface_url": "https://huggingface.co/models?search=KAT-Coder"
      },
      "benchmarks": {
        "AgentBench": {
          "accuracy": 0.24,
          "stderr": 0.087
        },
        "HumanEval": {
          "accuracy": 0.88,
          "stderr": 0.066
        },
        "IFEval": {
          "prompt_strict_acc": 0.6,
          "prompt_strict_stderr": 0.1,
          "prompt_loose_acc": 0.68,
          "prompt_loose_stderr": 0.095,
          "inst_strict_acc": 0.692,
          "inst_strict_stderr": 0.082,
          "inst_loose_acc": 0.744,
          "inst_loose_stderr": 0.085,
          "final_acc": 0.679,
          "final_stderr": 0.088
        },
        "WritingBench": {
          "mean": 4.32,
          "Education": 2.933,
          "domain1_mean": 4.32,
          "Brainstorm": 4.6,
          "Abstract": 1.0,
          "Contract": 1.2,
          "domain2_mean": 4.32
        }
      }
    },
    "nemotron3.5-lightning": {
      "id": "nemotron3.5-lightning",
      "name": "nemotron3.5-lightning",
      "is_cloud": false,
      "specs": {
        "architecture": "NemotronHForCausalLM",
        "attention_layers": 6,
        "mamba_layers": 23,
        "moe_layers": 23,
        "num_kv_heads": 2,
        "head_dim": 128,
        "context_window": 1048576,
        "kv_bytes_per_token_per_gpu": 1536,
        "vram_weights_gib": 10.35,
        "size_class": "Mid-Weight MoE (30B A3B)",
        "huggingface_url": "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
      },
      "benchmarks": {
        "IFEval": {
          "scores": {
            "prompt_strict_acc": 1.0,
            "prompt_strict_stderr": 0.0,
            "prompt_loose_acc": 1.0,
            "prompt_loose_stderr": 0.0,
            "inst_strict_acc": 1.0,
            "inst_strict_stderr": 0.0,
            "inst_loose_acc": 1.0,
            "inst_loose_stderr": 0.0,
            "final_acc": 1.0,
            "final_stderr": 0.0
          },
          "duration_seconds": 402.78,
          "timestamp": "2026-08-24 22:25:17",
          "prompt_strict_acc": 1.0,
          "prompt_strict_stderr": 0.0,
          "prompt_loose_acc": 1.0,
          "prompt_loose_stderr": 0.0,
          "inst_strict_acc": 1.0,
          "inst_strict_stderr": 0.0,
          "inst_loose_acc": 1.0,
          "inst_loose_stderr": 0.0,
          "final_acc": 1.0,
          "final_stderr": 0.0
        }
      }
    },
    "Nex-N2.5-mini-NVFP4": {
      "id": "Nex-N2.5-mini-NVFP4",
      "name": "Nex-N2.5-mini-NVFP4",
      "is_cloud": false,
      "specs": {
        "architecture": "Qwen3_5MoeForConditionalGeneration",
        "attention_layers": 32,
        "num_kv_heads": 8,
        "head_dim": 64,
        "context_window": 131072,
        "kv_bytes_per_token_per_gpu": 16384,
        "vram_weights_gib": 20.0,
        "size_class": "Mid-Weight (14B-35B)",
        "huggingface_url": "https://huggingface.co/models?search=Nex-N2.5-mini-NVFP4"
      },
      "benchmarks": {
        "IFEval": {
          "samples": 100,
          "strict_accuracy": 0.88,
          "loose_accuracy": 0.91,
          "duration_s": 265.0,
          "profile": "frontier-agent"
        },
        "HumanEval": {
          "samples": 100,
          "pass_at_1": 0.91,
          "duration_s": 145.1,
          "profile": "frontier-agent"
        },
        "BFCL_Agent": {
          "samples": 100,
          "accuracy": 0.71,
          "duration_s": 489.0,
          "profile": "frontier-agent"
        },
        "BFCL_Tool": {
          "samples": 98,
          "accuracy": 0.7245,
          "duration_s": 5780.6,
          "profile": "frontier-tool"
        },
        "GAIA": {
          "samples": 25,
          "preflight_accuracy": 1.0,
          "completed_accuracy": 0.25,
          "duration_s": 2575.0,
          "profile": "frontier-agent"
        }
      }
    },
    "master-lite": {
      "id": "master-lite",
      "name": "master-lite",
      "is_cloud": false,
      "specs": {
        "architecture": "Transformer",
        "attention_layers": 32,
        "num_kv_heads": 8,
        "head_dim": 128,
        "context_window": 131072,
        "kv_bytes_per_token_per_gpu": 8192,
        "vram_weights_gib": 20.0,
        "size_class": "Mid-Weight (14B-35B)",
        "huggingface_url": "https://huggingface.co/models?search=master-lite"
      },
      "benchmarks": {
        "IFEval": {
          "scores": {},
          "duration_seconds": 420.26,
          "timestamp": "2026-09-23 09:11:53",
          "prompt_strict_acc": 0.72,
          "prompt_strict_stderr": 0.092,
          "prompt_loose_acc": 0.72,
          "prompt_loose_stderr": 0.092,
          "inst_strict_acc": 0.769,
          "inst_strict_stderr": 0.081,
          "inst_loose_acc": 0.769,
          "inst_loose_stderr": 0.081,
          "final_acc": 0.745,
          "final_stderr": 0.099
        },
        "HumanEval": {
          "scores": {},
          "duration_seconds": 420.26,
          "timestamp": "2026-09-23 09:19:19",
          "accuracy": 0.84,
          "stderr": 0.075
        },
        "BFCL": {
          "scores": {
            "\u2502": 80.0
          },
          "duration_seconds": 185.73,
          "timestamp": "2026-09-22 12:11:50",
          "\u2502": 80.0
        },
        "Custom-MiniCorp": {
          "samples": 1,
          "functional_pass_rate": 0.0,
          "mean_composite": 0.25,
          "hygiene_index": 0.625,
          "safety_violations_total": 0,
          "critical_violations_total": 0,
          "axis1_pass_rate": 0.0,
          "axis2_pass_rate": 1.0,
          "axis3_safe_rate": 1.0,
          "safety_gate_pass_rate": 1.0,
          "median_decode_tps": 36.289494013641395
        }
      }
    },
    "frontier-agent": {
      "id": "frontier-agent",
      "name": "frontier-agent",
      "is_cloud": false,
      "specs": {
        "architecture": "Transformer",
        "attention_layers": 32,
        "num_kv_heads": 8,
        "head_dim": 128,
        "context_window": 131072,
        "kv_bytes_per_token_per_gpu": 8192,
        "vram_weights_gib": 20.0,
        "size_class": "Mid-Weight (14B-35B)",
        "huggingface_url": "https://huggingface.co/models?search=frontier-agent"
      },
      "benchmarks": {
        "Custom-MiniCorp": {
          "scores": {
            "samples": 1,
            "functional_pass_rate": 0.0,
            "mean_composite": 0.3333,
            "hygiene_index": 0.8333,
            "safety_violations_total": 0,
            "critical_violations_total": 0,
            "axis1_pass_rate": 0.0,
            "axis2_pass_rate": 1.0,
            "axis3_safe_rate": 1.0,
            "safety_gate_pass_rate": 1.0,
            "median_decode_tps": 76.13324082080028
          },
          "duration_seconds": 19.28,
          "timestamp": "2026-09-23 11:58:32",
          "samples": 1,
          "functional_pass_rate": 0.0,
          "mean_composite": 0.3333,
          "hygiene_index": 0.8333,
          "safety_violations_total": 0,
          "critical_violations_total": 0,
          "axis1_pass_rate": 0.0,
          "axis2_pass_rate": 1.0,
          "axis3_safe_rate": 1.0,
          "safety_gate_pass_rate": 1.0,
          "median_decode_tps": 76.13324082080028,
          "eds_tag": "eds_tri_axis"
        }
      }
    },
    "demo": {
      "id": "demo",
      "name": "demo",
      "is_cloud": false,
      "specs": {
        "architecture": "Transformer",
        "attention_layers": 32,
        "num_kv_heads": 8,
        "head_dim": 128,
        "context_window": 131072,
        "kv_bytes_per_token_per_gpu": 8192,
        "vram_weights_gib": 20.0,
        "size_class": "Mid-Weight (14B-35B)",
        "huggingface_url": "https://huggingface.co/models?search=demo"
      },
      "benchmarks": {
        "MiniCorp": {
          "eds_tag": "eds_tri_axis"
        }
      }
    },
    "claude-3-5-sonnet": {
      "id": "claude-3-5-sonnet",
      "name": "Claude 3.5 Sonnet (20241022)",
      "is_cloud": true,
      "specs": {
        "total_params_b": "Unknown (Dense/MoE)",
        "active_params_b": "Unknown",
        "context_window": 200000,
        "kv_bytes_per_token_per_gpu": 2400,
        "vram_weights_gib": 0.0,
        "size_class": "Cloud Frontier",
        "architecture": "Frontier API"
      },
      "benchmarks": {
        "IFEval": {
          "prompt_strict_acc": 0.884,
          "inst_strict_acc": 0.912,
          "final_acc": 0.898
        },
        "HumanEval": {
          "pass@1": 0.937,
          "accuracy": 0.937
        },
        "IFEvalCode": {
          "python_correctness": 0.92,
          "typescript_correctness": 0.88,
          "overall_accuracy": 0.65
        },
        "AgentBench": {
          "accuracy": 0.52
        }
      }
    },
    "gpt-4o": {
      "id": "gpt-4o",
      "name": "GPT-4o (2024-11-20)",
      "is_cloud": true,
      "specs": {
        "total_params_b": "Unknown (~200B MoE)",
        "active_params_b": "Unknown",
        "context_window": 128000,
        "kv_bytes_per_token_per_gpu": 2400,
        "vram_weights_gib": 0.0,
        "size_class": "Cloud Frontier",
        "architecture": "Frontier API"
      },
      "benchmarks": {
        "IFEval": {
          "prompt_strict_acc": 0.865,
          "inst_strict_acc": 0.895,
          "final_acc": 0.88
        },
        "HumanEval": {
          "pass@1": 0.902,
          "accuracy": 0.902
        },
        "IFEvalCode": {
          "python_correctness": 0.89,
          "typescript_correctness": 0.84,
          "overall_accuracy": 0.58
        },
        "AgentBench": {
          "accuracy": 0.48
        }
      }
    },
    "gemini-2-0-flash": {
      "id": "gemini-2-0-flash",
      "name": "Gemini 2.0 Flash",
      "is_cloud": true,
      "specs": {
        "total_params_b": "Unknown (~30B-70B)",
        "active_params_b": "Unknown",
        "context_window": 1048576,
        "kv_bytes_per_token_per_gpu": 1800,
        "vram_weights_gib": 0.0,
        "size_class": "Cloud Frontier",
        "architecture": "Frontier API"
      },
      "benchmarks": {
        "IFEval": {
          "prompt_strict_acc": 0.852,
          "inst_strict_acc": 0.889,
          "final_acc": 0.871
        },
        "HumanEval": {
          "pass@1": 0.89,
          "accuracy": 0.89
        },
        "IFEvalCode": {
          "python_correctness": 0.88,
          "typescript_correctness": 0.81,
          "overall_accuracy": 0.52
        },
        "AgentBench": {
          "accuracy": 0.44
        }
      }
    }
  }
};
