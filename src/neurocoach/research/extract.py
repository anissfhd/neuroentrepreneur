"""Extraction litterale des constats (R1) : une phrase d'une source, citee mot pour mot.

Aucune reformulation, aucun modele : le constat EST une phrase de l'extrait, et sa citation
aussi. Les phrases qui ressemblent a une consigne (injection) sont ignorees : la source reste
une donnee conservee et signalee, jamais une instruction. Les regles de preuve du domaine
(``validate_finding``) s'appliquent ensuite comme a tout candidat.
"""

from __future__ import annotations

import re

from neurocoach.domain.research import (
    MAX_QUOTE,
    FindingCandidate,
    Nature,
    ResearchBrief,
    SourceRecord,
    is_suspicious,
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


class ExtractiveFindingExtractor:
    def __init__(self, per_source: int = 1) -> None:
        self.per_source = per_source

    def extract(self, brief: ResearchBrief, sources: list[SourceRecord]) -> list[FindingCandidate]:
        candidates: list[FindingCandidate] = []
        for source in sources:
            if not source.excerpt.strip():
                # Reference seule (texte non conserve, conditions du service) : une piste a
                # verifier, jamais un fait. Le titre est une donnee, pas une consigne.
                title = " ".join(source.title.split())[:200]
                if title and not is_suspicious(title):
                    candidates.append(
                        FindingCandidate(
                            category=source.category,
                            statement=f"Piste à vérifier : « {title} » ({source.domain})",
                            nature=Nature.HYPOTHESIS,
                            source_ids=[source.id],
                        )
                    )
                continue
            kept = 0
            for sentence in _SENTENCE.split(source.excerpt):
                sentence = sentence.strip()
                if len(sentence) < 15 or is_suspicious(sentence) or sentence.endswith("…"):
                    continue
                if len(sentence) > MAX_QUOTE:
                    continue
                candidates.append(
                    FindingCandidate(
                        category=source.category,
                        statement=sentence,
                        nature=Nature.FACT,
                        source_ids=[source.id],
                        quotes=[sentence],
                    )
                )
                kept += 1
                if kept >= self.per_source:
                    break
        return candidates
