from __future__ import annotations

from .base import Parser
from .revolut import RevolutParser
from .santander_es import SantanderEsParser
from .scotiabank_cl import ScotiabankClParser

PARSERS: dict[str, type[Parser]] = {
    RevolutParser.name: RevolutParser,
    SantanderEsParser.name: SantanderEsParser,
    ScotiabankClParser.name: ScotiabankClParser,
}


def get_parser(name: str, **kwargs) -> Parser:
    cls = PARSERS.get(name)
    if cls is None:
        raise KeyError(f"Unknown parser: {name}. Known: {list(PARSERS)}")
    return cls(**kwargs)
