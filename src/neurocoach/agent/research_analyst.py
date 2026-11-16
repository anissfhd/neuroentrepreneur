"""Analyste de recherche (R4, D-71) : le modele de strategie derriere le port du service.

Aucun second systeme LLM : le meme fournisseur de l'application, aiguille par la table des
roles vers le role ``strategy`` (taches ``research_analysis`` et ``research_comparison``).
Le modele propose ; ``ResearchService`` valide chaque affirmation contre les sources.
"""

from __future__ import annotations

from typing import Any

from neurocoach.agent.llm import LLMProvider
from neurocoach.agent.prompts import build_messages
from neurocoach.domain.analysis import ComparisonDraft, IdeaAnalysisDraft
from neurocoach.domain.solutions import SolutionsDraft

ANALYZE_INSTRUCTION = "Analyse cette idée à partir des sources et du profil fournis."
COMPARE_INSTRUCTION = "Compare ces idées pour cette personne et recommande avec prudence."
SOLVE_INSTRUCTION = "Propose des solutions concrètes et sourcées à ce problème, pour ce projet."


class LLMResearchAnalyst:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    def analyze_idea(self, payload: dict[str, Any]) -> IdeaAnalysisDraft:
        messages = build_messages("research_analysis", text=ANALYZE_INSTRUCTION, facts=payload)
        return self.llm.generate_structured("research_analysis", messages, IdeaAnalysisDraft)

    def compare(self, payload: dict[str, Any]) -> ComparisonDraft:
        messages = build_messages("research_comparison", text=COMPARE_INSTRUCTION, facts=payload)
        return self.llm.generate_structured("research_comparison", messages, ComparisonDraft)

    def propose_solutions(self, payload: dict[str, Any]) -> SolutionsDraft:
        """R6 (D-73) : solutions a un probleme, role strategy."""
        messages = build_messages("research_solutions", text=SOLVE_INSTRUCTION, facts=payload)
        return self.llm.generate_structured("research_solutions", messages, SolutionsDraft)
