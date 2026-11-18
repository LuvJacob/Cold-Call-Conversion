"""Free public data sources that need no API keys (Wikidata/Wikipedia, SEC EDGAR, company homepage).

Enable in the backend with RESEARCH_PROVIDERS=free. See apps/agents/README.md.
"""

from .provider import FreeSources, TemplateLLM, build_free_providers

__all__ = ["FreeSources", "TemplateLLM", "build_free_providers"]
