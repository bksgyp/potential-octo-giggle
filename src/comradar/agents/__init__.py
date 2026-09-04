"""The four agent roles: collect, synthesise, ideate, report."""

from .collector import CollectorAgent
from .ideation import IdeationAgent
from .reporter import ReportAgent
from .synthesizer import SynthesisAgent

__all__ = ["CollectorAgent", "SynthesisAgent", "IdeationAgent", "ReportAgent"]
