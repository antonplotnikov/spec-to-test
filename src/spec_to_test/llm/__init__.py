"""Optional LLM providers (Claude, OpenAI, OpenAI-compatible servers, Ollama) behind one structured-output call.

`config` reads which providers may be used (keys only ever come from the
environment, Streamlit secrets or a local .env); `providers` sends one request
and turns every failure into an `AIError` code. Nothing here is needed for the
rule-based features, which keep working when no provider is configured.
"""
