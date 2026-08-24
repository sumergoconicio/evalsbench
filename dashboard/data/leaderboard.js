window.LEADERBOARD_DATA = {
  "schema_version": "1.0",
  "models": {
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
