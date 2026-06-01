from .base import ParsedTxn, Parser
from .registry import PARSERS, get_parser
from .revolut import RevolutParser
from .santander_es import SantanderEsParser
from .scotiabank_cl import ScotiabankClParser

__all__ = [
    "ParsedTxn",
    "Parser",
    "PARSERS",
    "get_parser",
    "RevolutParser",
    "SantanderEsParser",
    "ScotiabankClParser",
]
