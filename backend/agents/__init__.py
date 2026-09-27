"""
backend/agents/ — self-correcting deep agent loop + its real tool bindings.

- schemas.py         Pydantic response models the loop validates LLM output
                      against; mirror the real endpoint shapes verbatim.
- tools.py            Async wrappers that call this backend's own HTTP API
                      (never a second, duplicate DB/business-logic path).
- deep_agent_loop.py  SelfCorrectingAgent: LLM call -> Pydantic validation ->
                      bounded retry with the validation error fed back to
                      the model, using services/llm_client.py.
"""
