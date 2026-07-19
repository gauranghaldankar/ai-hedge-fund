"""Helper functions for LLM"""

import json
from pydantic import BaseModel
from src.llm.models import get_model, get_model_info
from src.utils.progress import progress
from src.utils import rate_limiter
from src.graph.state import AgentState

# When the primary provider is Google, fall back through this chain on rate limits.
# Only free/local providers are used — never paid fallbacks.
_GOOGLE_FALLBACKS = [
    ("google/gemma-4-31b-it:free", "OpenRouter"),  # free tier on OpenRouter
    ("qwen3.5:9b", "Ollama"),                       # local, zero cost
]


def _is_rate_limited(exc: Exception) -> bool:
    """Return True if the exception looks like a provider rate-limit / quota error."""
    msg = str(exc).lower()
    return any(k in msg for k in (
        "429", "rate limit", "rate_limit", "quota", "resource_exhausted",
        "resource has been exhausted", "too many requests",
    ))


def _is_auth_error(exc: Exception) -> bool:
    """Return True for errors that retrying cannot fix (auth failures, missing models)."""
    msg = str(exc).lower()
    return any(k in msg for k in (
        "api key not valid", "api_key_invalid", "invalid api key",
        "missing authentication", "401", "unauthorized",
        "authentication", "invalid crumb",
        "unavailable for free", "model is unavailable",  # OpenRouter 404 for gone free models
    ))


def call_llm(
    prompt: any,
    pydantic_model: type[BaseModel],
    agent_name: str | None = None,
    state: AgentState | None = None,
    max_retries: int = 3,
    default_factory=None,
) -> BaseModel:
    """
    Makes an LLM call with retry logic and a provider fallback chain.

    Primary provider: Google Gemini (rate-limited to 15 RPM / 1500 per day).
    On rate-limit or daily-quota exhaustion, falls back automatically to:
      1. OpenRouter (free models only)
      2. Local Ollama

    Args:
        prompt: The prompt to send to the LLM
        pydantic_model: The Pydantic model class to structure the output
        agent_name: Optional name of the agent for progress updates and model config extraction
        state: Optional state object to extract agent-specific model configuration
        max_retries: Maximum number of retries per provider (default: 3)
        default_factory: Optional factory function to create default response on failure

    Returns:
        An instance of the specified Pydantic model
    """
    # Extract model configuration if state is provided and agent_name is available
    if state and agent_name:
        model_name, model_provider = get_agent_model_config(state, agent_name)
    else:
        # Default to Google Gemini free tier
        model_name = "gemini-2.0-flash"
        model_provider = "Google"

    # Extract API keys from state if available
    api_keys = None
    if state:
        request = state.get("metadata", {}).get("request")
        if request and hasattr(request, "api_keys"):
            api_keys = request.api_keys

    # Build the provider chain: primary + automatic fallbacks for Google
    chain = [(model_name, model_provider)]
    if model_provider == "Google":
        chain.extend(_GOOGLE_FALLBACKS)

    for mn, mp in chain:
        # Pre-flight rate-limit check for Google — blocks for RPM, skips on daily exhaustion
        if mp == "Google":
            if not rate_limiter.acquire():
                used = rate_limiter.daily_used()
                print(f"[LLM] Google daily quota exhausted ({used}/{rate_limiter.DAILY_LIMIT}), switching to next provider")
                continue

        model_info = get_model_info(mn, mp)
        try:
            llm = get_model(mn, mp, api_keys)
        except ValueError as e:
            # Missing key in get_model() raises ValueError — skip immediately, no retry
            print(f"[LLM] Cannot initialize {mp}/{mn} (missing key?): {e} — trying next provider")
            continue
        except Exception as e:
            print(f"[LLM] Cannot initialize {mp}/{mn}: {e} — trying next provider")
            continue

        # Ollama thinking models (qwen3, deepseek-r1, etc.) emit <think>...</think>
        # blocks before their JSON, which breaks structured output. Always use manual
        # extraction for Ollama so extract_json_from_response can strip the tags.
        is_ollama = (mp == "Ollama")
        use_json_mode = not is_ollama and not (model_info and not model_info.has_json_mode())
        if use_json_mode:
            llm = llm.with_structured_output(pydantic_model, method="json_mode")

        for attempt in range(max_retries):
            try:
                if agent_name:
                    progress.update_status(agent_name, None, f"Thinking via {mp}...")
                result = llm.invoke(prompt)

                if not use_json_mode:
                    parsed_result = extract_json_from_response(result.content)
                    if parsed_result:
                        return pydantic_model(**parsed_result)
                else:
                    return result

            except Exception as e:
                if _is_auth_error(e):
                    # Bad/missing key — retrying won't help; move to next provider immediately.
                    print(f"[LLM] Auth error on {mp}/{mn} — check your API key in .env. Switching to next provider.")
                    break

                if _is_rate_limited(e):
                    print(f"[LLM] Rate limited by {mp}/{mn} — switching to next provider")
                    break  # exit retry loop, try next provider in chain

                if agent_name:
                    progress.update_status(agent_name, None, f"Error - retry {attempt + 1}/{max_retries}")

                if attempt == max_retries - 1:
                    print(f"[LLM] {mp}/{mn} failed after {max_retries} attempts: {e} — trying next provider")
                    break

    # All providers in the chain were exhausted
    print("[LLM] All providers exhausted — returning default response")
    if default_factory:
        return default_factory()
    return create_default_response(pydantic_model)


def create_default_response(model_class: type[BaseModel]) -> BaseModel:
    """Creates a safe default response based on the model's fields."""
    default_values = {}
    for field_name, field in model_class.model_fields.items():
        if field.annotation == str:
            default_values[field_name] = "Error in analysis, using default"
        elif field.annotation == float:
            default_values[field_name] = 0.0
        elif field.annotation == int:
            default_values[field_name] = 0
        elif hasattr(field.annotation, "__origin__") and field.annotation.__origin__ == dict:
            default_values[field_name] = {}
        else:
            # For other types (like Literal), try to use the first allowed value
            if hasattr(field.annotation, "__args__"):
                default_values[field_name] = field.annotation.__args__[0]
            else:
                default_values[field_name] = None

    return model_class(**default_values)


def extract_json_from_response(content) -> dict | None:
    """Extracts JSON from a response, handling markdown-wrapped and raw JSON formats."""
    import re
    try:
        # Reasoning models (e.g. Anthropic extended thinking) return content as a
        # list of blocks (thinking + text). Concatenate the text blocks.
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            content = "\n".join(parts)
        # Strip Ollama/qwen3 thinking blocks (<think>...</think>) so the brace
        # matcher doesn't get confused by JSON-like content inside the reasoning.
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        # 1. Try markdown code block with ```json
        json_start = content.find("```json")
        if json_start != -1:
            json_text = content[json_start + 7:]  # Skip past ```json
            json_end = json_text.find("```")
            if json_end != -1:
                json_text = json_text[:json_end].strip()
                try:
                    return json.loads(json_text)
                except json.JSONDecodeError:
                    pass

        # 2. Try markdown code block without json specifier
        json_start = content.find("```")
        if json_start != -1:
            json_text = content[json_start + 3:]
            json_end = json_text.find("```")
            if json_end != -1:
                json_text = json_text[:json_end].strip()
                try:
                    return json.loads(json_text)
                except json.JSONDecodeError:
                    pass

        # 3. Try to parse the entire content as JSON
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            pass

        # 4. Find the first top-level JSON object by matching braces
        brace_start = content.find("{")
        if brace_start != -1:
            depth = 0
            for i, char in enumerate(content[brace_start:], brace_start):
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(content[brace_start:i + 1])
                        except json.JSONDecodeError:
                            break

    except Exception as e:
        print(f"Error extracting JSON from response: {e}")
    return None


def get_agent_model_config(state, agent_name):
    """
    Get model configuration for a specific agent from the state.
    Falls back to global model configuration if agent-specific config is not available.
    Always returns valid model_name and model_provider values.
    """
    request = state.get("metadata", {}).get("request")
    
    if request and hasattr(request, 'get_agent_model_config'):
        # Get agent-specific model configuration
        model_name, model_provider = request.get_agent_model_config(agent_name)
        # Ensure we have valid values
        if model_name and model_provider:
            return model_name, model_provider.value if hasattr(model_provider, 'value') else str(model_provider)
    
    # Fall back to global configuration (system defaults)
    model_name = state.get("metadata", {}).get("model_name") or "gpt-4.1"
    model_provider = state.get("metadata", {}).get("model_provider") or "OPENAI"
    
    # Convert enum to string if necessary
    if hasattr(model_provider, 'value'):
        model_provider = model_provider.value
    
    return model_name, model_provider
