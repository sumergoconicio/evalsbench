# 📊 Benchmark Results: BFCL

* **Model**: `smolagent`
* **Endpoint**: `http://localhost:2468/v1`
* **Samples Evaluated**: 100
* **Execution Time**: 11.3 seconds (~0.2 min)
* **Log Directory**: `/home/sumergoconicio/Documents/Code/EvalsBench/logs/20260910_smolagent_bfcl`
* **Timestamp**: 2026-09-10 21:26:19

## 🎯 Evaluated Metrics

| Metric Name | Score |
| :--- | :--- |
| `│` | **404.000** |
| `Python` | **3.000** |


## 📝 Raw Inspect Output
```text
Monitor from another shell: inspect ctl task list   (inspect ctl --help)
╭──────────────────────────────────────────────────────────────────────────────╮
│bfcl (100 samples): openai/smolagent                                          │
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
│ in run                                                                       │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_ai/solver/_… │
│ in __call__                                                                  │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_evals/bfcl/… │
│ in solve                                                                     │
│                                                                              │
│   191 │                                                                      │
│   192 │   async def solve(state: TaskState, generate: Generate) -> TaskState │
│   193 │   │   if state.metadata.get("scorer") == "multi_turn":               │
│ ❱ 194 │   │   │   return await multi_turn_solve(state, generate)             │
│   195 │   │   return await single_turn_solve(state, generate)                │
│   196 │                                                                      │
│   197 │   return solve                                                       │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_evals/bfcl/… │
│ in multi_turn_solve                                                          │
│                                                                              │
│   172 │   │   # Inspect AI handles the tool-calling loop: model generates, t │
│   173 │   │   # executed automatically, results are injected as ChatMessageT │
│   174 │   │   # and the loop repeats until the model produces a text-only re │
│ ❱ 175 │   │   state = await generate(state, tool_calls="loop")               │
│   176 │   │                                                                  │
│   177 │   │   model_execution_results.append(turn_results)                   │
│   178 │   │   model_execution_calls.append(turn_calls)                       │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_ai/_eval/ta… │
│ in generate                                                                  │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_ai/_eval/ta… │
│ in task_generate                                                             │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_ai/model/_m… │
│ in generate                                                                  │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_ai/model/_m… │
│ in _generate                                                                 │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/tenacity/asyncio/__… │
│ in async_wrapped                                                             │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/tenacity/asyncio/__… │
│ in __call__                                                                  │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/tenacity/asyncio/__… │
│ in iter                                                                      │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/tenacity/_utils.py:… │
│ in inner                                                                     │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/tenacity/__init__.p… │
│ in <lambda>                                                                  │
│                                                                              │
│ /usr/lib/python3.12/concurrent/futures/_base.py:449 in result                │
│                                                                              │
│   446 │   │   │   │   if self._state in [CANCELLED, CANCELLED_AND_NOTIFIED]: │
│   447 │   │   │   │   │   raise CancelledError()                             │
│   448 │   │   │   │   elif self._state == FINISHED:                          │
│ ❱ 449 │   │   │   │   │   return self.__get_result()                         │
│   450 │   │   │   │                                                          │
│   451 │   │   │   │   self._condition.wait(timeout)                          │
│   452                                                                        │
│                                                                              │
│ /usr/lib/python3.12/concurrent/futures/_base.py:401 in __get_result          │
│                                                                              │
│   398 │   def __get_result(self):                                            │
│   399 │   │   if self._exception:                                            │
│   400 │   │   │   try:                                                       │
│ ❱ 401 │   │   │   │   raise self._exception                                  │
│   402 │   │   │   finally:                                                   │
│   403 │   │   │   │   # Break a reference cycle with the exception in self._ │
│   404 │   │   │   │   self = None                                            │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/tenacity/asyncio/__… │
│ in __call__                                                                  │
│                                                                              │
│ /home/sumergoconicio/.venv/lib/python3.12/site-packages/inspect_ai/model/_m… │
│ in generate                                                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
ModelGenerateError:                                                             
Request:                                                                        
... (524 lines truncated) ...                                                   
      "description": "This tool belongs to the travel system, which allows users
to book flights, manage credit cards, and view budget information. Tool         
description: Purchase insurance Note that the provided function is in Python 3  
syntax.",                                                                       
      "parameters": {                                                           
        "type": "object",                                                       
        "properties": {                                                         
          "access_token": {                                                     
            "type": "string",                                                   
            "description": "The access token obtained from the authenticate"    
          },                                                                    
          "insurance_type": {                                                   
            "type": "string",                                                   
            "description": "The type of insurance to purchase"                  
          },                                                                    
          "booking_id": {                                                       
            "type": "string",                                                   
            "description": "The ID of the booking"                              
          },                                                                    
          "insurance_cost": {                                                   
            "type": "number",                                                   
            "description": "The cost of the insurance"                          
          },                                                                    
          "card_id": {                                                          
            "type": "string",                                                   
            "description": "The ID of the credit card to use for the"           
          }                                                                     
        },                                                                      
        "required": [                                                           
          "access_token",                                                       
          "insurance_type",                                                     
          "booking_id",                                                         
          "insurance_cost",                                                     
          "card_id"                                                             
        ],                                                                      
        "additionalProperties": false                                           
      },                                                                        
      "strict": false                                                           
    },                                                                          
    {                                                                           
      "type": "function",                                                       
      "name": "register_credit_card",                                           
      "description": "This tool belongs to the travel system, which allows users
to book flights, manage credit cards, and view budget information. Tool         
description: Register a credit card Note that the provided function is in Python
3 syntax.",                                                                     
      "parameters": {                                                           
        "type": "object",                                                       
        "properties": {                                                         
          "access_token": {                                                     
            "type": "string",                                                   
            "description": "The access token obtained from the authenticate     
method"                                                                         
          },                                                                    
          "card_number": {                                                      
            "type": "string",                                                   
            "description": "The credit card number"                             
          },                                                                    
          "expiration_date": {                                                  
            "type": "string",                                                   
            "description": "The expiration date of the credit card in the format
MM/YYYY"                                                                        
          },                                                                    
          "cardholder_name": {                                                  
            "type": "string",                                                   
            "description": "The name of the cardholder"                         
          },                                                                    
          "card_verification_number": {                                         
            "type": "integer",                                                  
            "description": "The card verification number"                       
          }                                                                     
        },                                                                      
        "required": [                                                           
          "access_token",                                                       
          "card_number",                                                        
          "expiration_date",                                                    
          "cardholder_name",                                                    
          "card_verification_number"                                            
        ],                                                                      
        "additionalProperties": false                                           
      },                                                                        
      "strict": false                                                           
    },                                                                          
    {                                                                           
      "type": "function",                                                       
      "name": "retrieve_invoice",                                               
      "description": "This tool belongs to the travel system, which allows users
to book flights, manage credit cards, and view budget information. Tool         
description: Retrieve the invoice for a booking. Note that the provided function
is in Python 3 syntax.",                                                        
      "parameters": {                                                           
        "type": "object",                                                       
        "properties": {                                                         
          "access_token": {                                                     
            "type": "string",                                                   
            "description": "The access token obtained from the authenticate"    
          },                                                                    
          "booking_id": {                                                       
            "description": "The ID of the booking",                             
            "anyOf": [                                                          
              {                                                                 
                "type": "string"                                                
              },                                                                
              {                                                                 
                "type": "null"                                                  
              }                                                                 
            ]                                                                   
          },                                                                    
          "insurance_id": {                                                     
            "description": "The ID of the insurance",                           
            "anyOf": [                                                          
              {                                                                 
                "type": "string"                                                
              },                                                                
              {                                                                 
                "type": "null"                                                  
              }                                                                 
            ]                                                                   
          }                                                                     
        },                                                                      
        "required": [                                                           
          "access_token"                                                        
        ],                                                                      
        "additionalProperties": false                                           
      },                                                                        
      "strict": false                                                           
    },                                                                          
    {                                                                           
      "type": "function",                                                       
      "name": "set_budget_limit",                                               
      "description": "This tool belongs to the travel system, which allows users
to book flights, manage credit cards, and view budget information. Tool         
description: Set the budget limit for the user Note that the provided function  
is in Python 3 syntax.",                                                        
      "parameters": {                                                           
        "type": "object",                                                       
        "properties": {                                                         
          "access_token": {                                                     
            "type": "string",                                                   
            "description": "The access token obtained from the authentication   
process or initial configuration."                                              
          },                                                                    
          "budget_limit": {                                                     
            "type": "number",                                                   
            "description": "The budget limit to set in USD"                     
          }                                                                     
        },                                                                      
        "required": [                                                           
          "access_token",                                                       
          "budget_limit"                                                        
        ],                                                                      
        "additionalProperties": false                                           
      },                                                                        
      "strict": false                                                           
    },                                                                          
    {                                                                           
      "type": "function",                                                       
      "name": "travel_get_login_status",                                        
      "description": "This tool belongs to the travel system, which allows users
to book flights, manage credit cards, and view budget information. Tool         
description: Get the status of the login Note that the provided function is in  
Python 3 syntax.",                                                              
      "parameters": {                                                           
        "type": "object",                                                       
        "properties": {},                                                       
        "required": [],                                                         
        "additionalProperties": false                                           
      },                                                                        
      "strict": false                                                           
    },                                                                          
    {                                                                           
      "type": "function",                                                       
      "name": "verify_traveler_information",                                    
      "description": "This tool belongs to the travel system, which allows users
to book flights, manage credit cards, and view budget information. Tool         
description: Verify the traveler information Note that the provided function is 
in Python 3 syntax.",                                                           
      "parameters": {                                                           
        "type": "object",                                                       
        "properties": {                                                         
          "first_name": {                                                       
            "type": "string",                                                   
            "description": "The first name of the traveler"                     
          },                                                                    
          "last_name": {                                                        
            "type": "string",                                                   
            "description": "The last name of the traveler"                      
          },                                                                    
          "date_of_birth": {                                                    
            "type": "string",                                                   
            "description": "The date of birth of the traveler in the format     
YYYY-MM-DD"                                                                     
          },                                                                    
          "passport_number": {                                                  
            "type": "string",                                                   
            "description": "The passport number of the traveler"                
          }                                                                     
        },                                                                      
        "required": [                                                           
          "first_name",                                                         
          "last_name",                                                          
          "date_of_birth",                                                      
          "passport_number"                                                     
        ],                                                                      
        "additionalProperties": false                                           
      },                                                                        
      "strict": false                                                           
    }                                                                           
  ],                                                                            
  "tool_choice": null,                                                          
  "extra_headers": {                                                            
    "x-irid": "bjAiYmePEqFHPr2NbTSxMn"                                          
  },                                                                            
  "model": "smolagent",                                                         
  "include": [                                                                  
    "reasoning.encrypted_content"                                               
  ],                                                                            
  "store": false,                                                               
  "reasoning": {                                                                
    "summary": "auto"                                                           
  }                                                                             
}                                                                               
                                                                                
BadRequestError('Error code: 400 - {\'error\': {\'code\': 400, \'message\':     
"item[\'content\'] is empty", \'type\': \'invalid_request_error\'}}')           
                                                                                
Task interrupted (no samples completed before interruption)                     
                                                                                
Log:                                                                            
logs/20260910_smolagent_bfcl/2026-09-10T19-26-10-00-00_bfcl_eJZd9TjdRamVwbL47ZNB
Vh.eval                                                                         
                                                                                
```
