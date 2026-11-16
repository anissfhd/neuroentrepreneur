"""Acces SQL aux donnees de recherche (R1, migration 0003), toujours filtre par utilisateur.

Comme pour le reste de la base, une mission d'un autre utilisateur est indiscernable d'une
mission inexistante (``NOT_FOUND``). Aucune methode n'ecrit dans projects, phases ou tasks.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from neurocoach.domain.analysis import ResearchAnalysis
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.research import (
    Finding,
    MissionStatus,
    QueryRecord,
    ResearchMission,
    SourceRecord,
)
from neurocoach.domain.solutions import SolutionPlan
from neurocoach.infra.repositories import (
    from_db_date,
    from_db_datetime,
    to_db_date,
    to_db_datetime,
)

RESEARCH_TABLES = (
    "research_missions",
    "research_queries",
    "research_sources",
    "research_findings",
    "research_analyses",
    "research_solutions",
)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class ResearchRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --- missions --------------------------------------------------------------------------
    @staticmethod
    def _mission(row: sqlite3.Row) -> ResearchMission:
        return ResearchMission.model_validate(
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "status": row["status"],
                "scope": json.loads(row["scope_json"]),
                "briefs": json.loads(row["brief_json"]),
                "planned": json.loads(row["planned_json"]),
                "preview": json.loads(row["preview_json"]),
                "scope_hash": row["scope_hash"],
                "parent_mission_id": row["parent_mission_id"],
                "spent_usd": row["spent_usd"],
                "queries_used": row["queries_used"],
                "created_at": from_db_datetime(row["created_at"]),
                "expires_at": from_db_datetime(row["expires_at"]),
                "approved_at": from_db_datetime(row["approved_at"]),
                "valid_until": from_db_datetime(row["valid_until"]),
                "decided_at": from_db_datetime(row["decided_at"]),
                "finished_at": from_db_datetime(row["finished_at"]),
            }
        )

    def insert_mission(self, mission: ResearchMission) -> None:
        self.conn.execute(
            "INSERT INTO research_missions (id, user_id, status, scope_json, brief_json, "
            "planned_json, preview_json, scope_hash, simulated, parent_mission_id, spent_usd, "
            "queries_used, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                mission.id,
                mission.user_id,
                mission.status.value,
                _dumps(mission.scope.model_dump(mode="json")),
                _dumps({k: b.model_dump(mode="json") for k, b in mission.briefs.items()}),
                _dumps([q.model_dump(mode="json") for q in mission.planned]),
                _dumps(mission.preview),
                mission.scope_hash,
                int(mission.simulated),
                mission.parent_mission_id,
                mission.spent_usd,
                mission.queries_used,
                to_db_datetime(mission.created_at),
                to_db_datetime(mission.expires_at),
            ),
        )
        self.conn.executemany(
            "INSERT INTO research_mission_projects (mission_id, project_id) VALUES (?, ?)",
            [(mission.id, project_id) for project_id in mission.scope.project_ids],
        )

    def get_mission(self, user_id: str, mission_id: str) -> ResearchMission:
        row = self.conn.execute(
            "SELECT * FROM research_missions WHERE id = ? AND user_id = ?", (mission_id, user_id)
        ).fetchone()
        if row is None:
            raise DomainError(ErrorCode.NOT_FOUND, "Mission de recherche introuvable.")
        return self._mission(row)

    def list_missions(self, user_id: str, project_id: str | None = None) -> list[ResearchMission]:
        if project_id is None:
            rows = self.conn.execute(
                "SELECT * FROM research_missions WHERE user_id = ? ORDER BY created_at, rowid",
                (user_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT m.* FROM research_missions m JOIN research_mission_projects p "
                "ON p.mission_id = m.id WHERE m.user_id = ? AND p.project_id = ? "
                "ORDER BY m.created_at, m.rowid",
                (user_id, project_id),
            ).fetchall()
        return [self._mission(row) for row in rows]

    def transition(
        self,
        user_id: str,
        mission_id: str,
        *,
        source: MissionStatus,
        target: MissionStatus,
        now: datetime,
        not_after: datetime | None = None,
        valid_until: datetime | None = None,
        scope_hash: str | None = None,
    ) -> bool:
        """Transition conditionnelle (usage unique) : vraie si et seulement si CETTE requete
        a fait passer la mission de ``source`` a ``target``."""
        sets = ["status = ?", "decided_at = COALESCE(decided_at, ?)"]
        params: list[Any] = [target.value, to_db_datetime(now)]
        if target is MissionStatus.APPROVED:
            sets += ["approved_at = ?", "valid_until = ?"]
            params += [to_db_datetime(now), to_db_datetime(valid_until)]
        if target in (MissionStatus.COMPLETED, MissionStatus.PARTIAL):
            sets.append("finished_at = ?")
            params.append(to_db_datetime(now))
        where = ["id = ?", "user_id = ?", "status = ?"]
        params += [mission_id, user_id, source.value]
        if not_after is not None:
            where.append("expires_at > ?")
            params.append(to_db_datetime(not_after))
        if scope_hash is not None:
            where.append("scope_hash = ?")
            params.append(scope_hash)
        cursor = self.conn.execute(
            f"UPDATE research_missions SET {', '.join(sets)} WHERE {' AND '.join(where)}",
            params,
        )
        return cursor.rowcount == 1

    def reserve(self, user_id: str, mission_id: str, cost: float, now: datetime) -> bool:
        """Reserve une recherche AVANT l'appel : budget et nombre de requetes verifies et
        decomptes en une seule instruction (deux clics simultanes ne depassent pas)."""
        cursor = self.conn.execute(
            "UPDATE research_missions SET spent_usd = round(spent_usd + ?, 6), "
            "queries_used = queries_used + 1 WHERE id = ? AND user_id = ? AND status = ? "
            "AND valid_until > ? AND spent_usd + ? <= json_extract(scope_json, "
            "'$.max_budget_usd') + 1e-9 AND queries_used < json_extract(scope_json, "
            "'$.max_queries')",
            (cost, mission_id, user_id, MissionStatus.APPROVED.value, to_db_datetime(now), cost),
        )
        return cursor.rowcount == 1

    # --- requetes, sources, constats -------------------------------------------------------
    def insert_query(self, query: QueryRecord) -> None:
        self.conn.execute(
            "INSERT INTO research_queries (id, mission_id, user_id, project_id, category, "
            "provider, market, text, status, estimated_cost_usd, result_count, error, "
            "simulated, created_at, actual_cost_usd, error_kind, subject, blocked_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                query.id,
                query.mission_id,
                query.user_id,
                query.project_id,
                query.category.value,
                query.provider,
                query.market,
                query.text,
                query.status,
                query.estimated_cost_usd,
                query.result_count,
                query.error,
                int(query.simulated),
                to_db_datetime(query.created_at),
                query.actual_cost_usd,
                query.error_kind,
                query.subject,
                query.blocked_count,
            ),
        )

    def list_queries(self, user_id: str, mission_id: str) -> list[QueryRecord]:
        rows = self.conn.execute(
            "SELECT * FROM research_queries WHERE user_id = ? AND mission_id = ? "
            "ORDER BY created_at, rowid",
            (user_id, mission_id),
        ).fetchall()
        return [
            QueryRecord.model_validate(
                {
                    **{
                        k: row[k]
                        for k in row.keys()  # noqa: SIM118 - sqlite3.Row n'est pas un dict
                        if k not in ("simulated", "created_at")
                    },
                    "simulated": bool(row["simulated"]),
                    "created_at": from_db_datetime(row["created_at"]),
                }
            )
            for row in rows
        ]

    def insert_source(self, user_id: str, mission_id: str, source: SourceRecord) -> None:
        self.conn.execute(
            "INSERT INTO research_sources (id, mission_id, query_id, user_id, category, "
            "provider, url, domain, title, excerpt, published_date, retrieved_at, market, "
            "content_hash, suspicious, simulated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source.id,
                mission_id,
                source.query_id,
                user_id,
                source.category.value,
                source.provider,
                source.url,
                source.domain,
                source.title,
                source.excerpt,
                to_db_date(source.published_date),
                to_db_datetime(source.retrieved_at),
                source.market,
                source.content_hash,
                int(source.suspicious),
                int(source.simulated),
            ),
        )

    def list_sources(self, user_id: str, mission_id: str) -> list[SourceRecord]:
        rows = self.conn.execute(
            "SELECT * FROM research_sources WHERE user_id = ? AND mission_id = ? "
            "ORDER BY retrieved_at, rowid",
            (user_id, mission_id),
        ).fetchall()
        return [
            SourceRecord(
                id=row["id"],
                query_id=row["query_id"],
                category=row["category"],
                provider=row["provider"],
                url=row["url"],
                domain=row["domain"],
                title=row["title"],
                excerpt=row["excerpt"],
                published_date=from_db_date(row["published_date"]),
                retrieved_at=from_db_datetime(row["retrieved_at"]),
                market=row["market"],
                content_hash=row["content_hash"],
                suspicious=bool(row["suspicious"]),
                simulated=bool(row["simulated"]),
            )
            for row in rows
        ]

    def replace_findings(
        self, user_id: str, mission_id: str, findings: list[Finding], now: datetime
    ) -> None:
        self.conn.execute(
            "DELETE FROM research_findings WHERE user_id = ? AND mission_id = ?",
            (user_id, mission_id),
        )
        for finding in findings:
            self.conn.execute(
                "INSERT INTO research_findings (id, mission_id, user_id, category, statement, "
                "nature, proposed_nature, quotes_json, confidence, flags_json, reasons_json, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    finding.id,
                    mission_id,
                    user_id,
                    finding.category.value,
                    finding.statement,
                    finding.nature.value,
                    finding.proposed_nature.value,
                    _dumps(finding.quotes),
                    finding.confidence,
                    _dumps(finding.flags),
                    _dumps(finding.reasons),
                    to_db_datetime(now),
                ),
            )
            self.conn.executemany(
                "INSERT INTO research_finding_sources (finding_id, source_id) VALUES (?, ?)",
                [(finding.id, source_id) for source_id in finding.source_ids],
            )

    def list_findings(self, user_id: str, mission_id: str) -> list[Finding]:
        rows = self.conn.execute(
            "SELECT * FROM research_findings WHERE user_id = ? AND mission_id = ? "
            "ORDER BY created_at, rowid",
            (user_id, mission_id),
        ).fetchall()
        findings = []
        for row in rows:
            source_ids = [
                link[0]
                for link in self.conn.execute(
                    "SELECT source_id FROM research_finding_sources WHERE finding_id = ? "
                    "ORDER BY rowid",
                    (row["id"],),
                ).fetchall()
            ]
            findings.append(
                Finding(
                    id=row["id"],
                    category=row["category"],
                    statement=row["statement"],
                    nature=row["nature"],
                    proposed_nature=row["proposed_nature"],
                    source_ids=source_ids,
                    quotes=json.loads(row["quotes_json"]),
                    confidence=row["confidence"],
                    flags=json.loads(row["flags_json"]),
                    reasons=json.loads(row["reasons_json"]),
                )
            )
        return findings

    def adjust_spent(self, user_id: str, mission_id: str, delta: float) -> None:
        """Remplace le cout estime par le cout reel annonce (jamais negatif)."""
        self.conn.execute(
            "UPDATE research_missions SET spent_usd = max(0, round(spent_usd + ?, 6)) "
            "WHERE id = ? AND user_id = ?",
            (delta, mission_id, user_id),
        )

    # --- analyses (R4) ---------------------------------------------------------------------
    def insert_analysis(self, analysis: ResearchAnalysis, profile_hash: str) -> None:
        self.conn.execute(
            "INSERT INTO research_analyses (id, mission_id, user_id, created_at, sources_hash, "
            "profile_hash, analysis_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                analysis.id,
                analysis.mission_id,
                analysis.user_id,
                to_db_datetime(analysis.created_at),
                analysis.sources_hash,
                profile_hash,
                analysis.model_dump_json(),
            ),
        )

    def latest_analysis(self, user_id: str, mission_id: str) -> tuple[ResearchAnalysis, str] | None:
        row = self.conn.execute(
            "SELECT analysis_json, profile_hash FROM research_analyses WHERE user_id = ? AND "
            "mission_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (user_id, mission_id),
        ).fetchone()
        if row is None:
            return None
        return ResearchAnalysis.model_validate_json(row["analysis_json"]), row["profile_hash"]

    def list_analyses(self, user_id: str, mission_id: str) -> list[ResearchAnalysis]:
        rows = self.conn.execute(
            "SELECT analysis_json FROM research_analyses WHERE user_id = ? AND mission_id = ? "
            "ORDER BY created_at, rowid",
            (user_id, mission_id),
        ).fetchall()
        return [ResearchAnalysis.model_validate_json(r["analysis_json"]) for r in rows]

    # --- solutions (R6) ---------------------------------------------------------------------
    def insert_solutions(self, plan: SolutionPlan) -> None:
        self.conn.execute(
            "INSERT INTO research_solutions (id, mission_id, user_id, created_at, sources_hash, "
            "plan_json) VALUES (?, ?, ?, ?, ?, ?)",
            (plan.id, plan.mission_id, plan.user_id, to_db_datetime(plan.created_at),
             plan.sources_hash, plan.model_dump_json()),
        )  # fmt: skip

    def latest_solutions(self, user_id: str, mission_id: str) -> SolutionPlan | None:
        row = self.conn.execute(
            "SELECT plan_json FROM research_solutions WHERE user_id = ? AND mission_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (user_id, mission_id),
        ).fetchone()
        return SolutionPlan.model_validate_json(row["plan_json"]) if row else None

    def list_solutions(self, user_id: str, mission_id: str) -> list[SolutionPlan]:
        rows = self.conn.execute(
            "SELECT plan_json FROM research_solutions WHERE user_id = ? AND mission_id = ? "
            "ORDER BY created_at, rowid",
            (user_id, mission_id),
        ).fetchall()
        return [SolutionPlan.model_validate_json(r["plan_json"]) for r in rows]

    # --- quotas gratuits des services (compteur systeme, R2) --------------------------------
    def reserve_provider(
        self, provider: str, period: str, cost: float, cap: float | None, now: datetime
    ) -> bool:
        """Reserve le cout d'une requete sur le quota mensuel du service, en une instruction :
        refuse si le plafond local serait depasse ou si le service est suspendu."""
        self.conn.execute(
            "INSERT OR IGNORE INTO research_provider_usage (provider, period, updated_at) "
            "VALUES (?, ?, ?)",
            (provider, period, to_db_datetime(now)),
        )
        cursor = self.conn.execute(
            "UPDATE research_provider_usage SET reserved_usd = round(reserved_usd + ?, 6), "
            "queries = queries + 1, updated_at = ? WHERE provider = ? AND period = ? "
            "AND exhausted = 0 AND (? IS NULL OR reserved_usd + ? <= ? + 1e-9)",
            (cost, to_db_datetime(now), provider, period, cap, cost, cap),
        )
        return cursor.rowcount == 1

    def settle_provider(
        self, provider: str, period: str, delta: float, now: datetime, *, queries: int = 0
    ) -> None:
        self.conn.execute(
            "UPDATE research_provider_usage SET reserved_usd = max(0, round(reserved_usd + ?, 6)),"
            " queries = max(0, queries + ?), updated_at = ? WHERE provider = ? AND period = ?",
            (delta, queries, to_db_datetime(now), provider, period),
        )

    def mark_exhausted(self, provider: str, period: str, now: datetime) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO research_provider_usage (provider, period, updated_at) "
            "VALUES (?, ?, ?)",
            (provider, period, to_db_datetime(now)),
        )
        self.conn.execute(
            "UPDATE research_provider_usage SET exhausted = 1, updated_at = ? "
            "WHERE provider = ? AND period = ?",
            (to_db_datetime(now), provider, period),
        )

    def provider_usage(self, period: str) -> dict[str, dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT provider, reserved_usd, queries, exhausted FROM research_provider_usage "
            "WHERE period = ?",
            (period,),
        ).fetchall()
        return {
            row["provider"]: {
                "reserved_usd": float(row["reserved_usd"]),
                "queries": int(row["queries"]),
                "exhausted": bool(row["exhausted"]),
            }
            for row in rows
        }

    # --- effacement ------------------------------------------------------------------------
    def delete_user_research(self, user_id: str) -> None:
        self.conn.execute("DELETE FROM research_missions WHERE user_id = ?", (user_id,))

    def count_user_research(self, user_id: str) -> dict[str, int]:
        return {
            table: int(
                self.conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (user_id,)
                ).fetchone()[0]
            )
            for table in RESEARCH_TABLES
        }
