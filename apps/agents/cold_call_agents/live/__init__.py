"""Paid provider clients (Tavily, People Data Labs, IBM watsonx.ai, Gemini).

Enable in the backend with RESEARCH_PROVIDERS=live (wiring is the API lane's job).
Every client is tested offline against recorded sample responses. Set the API keys in the
worker environment to turn each one on; a missing key falls back to the free sources.
See apps/agents/README.md.
"""

from .dates import parse_date
from .factory import build_live_providers
from .models import CompanyProfile, PersonProfile
from .usage import LLMError, TokenUsage

__all__ = ["build_live_providers", "parse_date", "PersonProfile", "CompanyProfile", "LLMError", "TokenUsage"]
