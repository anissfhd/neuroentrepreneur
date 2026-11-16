"""Entites du domaine et enumerations (DOMAIN_CONTRACTS section 1).

Les entites sont immuables : toute modification produit une nouvelle instance.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from neurocoach.domain.errors import DomainError, ErrorCode


def new_id(prefix: str) -> str:
    """Identifiant opaque prefixe, par exemple ``tsk_<uuid4 hex>``."""
    return f"{prefix}_{uuid.uuid4().hex}"


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("un horodatage doit porter un fuseau")
    return value.astimezone(UTC).replace(microsecond=0)


def _text(min_length: int, max_length: int) -> Any:
    return Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length)
    ]


UtcDatetime = Annotated[datetime, AfterValidator(_ensure_utc)]
DisplayName = _text(1, 40)
ProjectTitle = _text(3, 120)
TaskTitle = _text(3, 120)
PhaseTitle = _text(3, 80)
Idea = _text(0, 1000)
Outcome = _text(1, 300)
Criterion = _text(3, 300)
ExitCriterion = _text(1, 300)
Description = _text(1, 1000)
BlockedReason = _text(3, 300)
ShortItem = _text(1, 200)
Priority = Annotated[int, Field(ge=1, le=5)]
EstimateMinutes = Annotated[int, Field(ge=5, le=480)]
MinutesPerDay = Annotated[int, Field(ge=5, le=720)]


class ResponseLength(StrEnum):
    COURT = "court"
    STANDARD = "standard"
    DETAILLE = "detaille"


class Cadence(StrEnum):
    FLEXIBLE = "flexible"
    QUOTIDIENNE = "quotidienne"
    HEBDOMADAIRE = "hebdomadaire"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"


class ActionType(StrEnum):
    PLAN_CREATE = "plan.create"
    PLAN_REPLAN = "plan.replan"
    TASK_CREATE = "task.create"
    TASK_UPDATE = "task.update"
    TASK_DELETE = "task.delete"
    PROJECT_DELETE = "project.delete"
    USER_DELETE_DATA = "user.delete_data"
    # D-85 : pause et reprise d'un projet, taches terminees confirmees ensemble.
    PROJECT_PAUSE = "project.pause"
    PROJECT_RESUME = "project.resume"
    TASKS_COMPLETE = "tasks.complete"


class ActionStatus(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class EventType(StrEnum):
    PROJECT_CREATED = "project.created"
    PROJECT_PAUSED = "project.paused"
    PROJECT_RESUMED = "project.resumed"
    DEADLINE_NOTICE = "task.deadline_notice"
    PLAN_APPLIED = "plan.applied"
    PLAN_REPLANNED = "plan.replanned"
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_DELETED = "task.deleted"
    TASK_STATUS_CHANGED = "task.status_changed"
    TASK_STATUS_REVERTED = "task.status_reverted"
    PREFERENCES_UPDATED = "preferences.updated"
    PROJECT_DELETED = "project.deleted"
    PROJECT_RENAMED = "project.renamed"  # D-76 : titre confirme par l'utilisateur
    PROFILE_CREATED = "profile.created"
    PROFILE_UPDATED = "profile.updated"
    PENDING_ACTION_CREATED = "pending_action.created"
    PENDING_ACTION_APPLIED = "pending_action.applied"
    PENDING_ACTION_CANCELLED = "pending_action.cancelled"
    PENDING_ACTION_EXPIRED = "pending_action.expired"
    PENDING_ACTION_SUPERSEDED = "pending_action.superseded"
    PENDING_ACTION_FAILED = "pending_action.failed"
    USER_DATA_EXPORTED = "user.data_exported"
    # Business Researcher (R1, D-68) : journal des missions de recherche.
    RESEARCH_MISSION_PROPOSED = "research.mission_proposed"
    RESEARCH_MISSION_APPROVED = "research.mission_approved"
    RESEARCH_MISSION_CANCELLED = "research.mission_cancelled"
    RESEARCH_MISSION_EXPIRED = "research.mission_expired"
    RESEARCH_MISSION_SUPERSEDED = "research.mission_superseded"
    RESEARCH_MISSION_CLOSED = "research.mission_closed"
    RESEARCH_QUERY_RUN = "research.query_run"
    RESEARCH_QUERY_REFUSED = "research.query_refused"
    RESEARCH_ANALYSIS_CREATED = "research.analysis_created"  # R4 (D-71)
    RESEARCH_SOLUTIONS_CREATED = "research.solutions_created"  # R6 (D-73)


STATUS_LABELS: dict[TaskStatus, str] = {
    TaskStatus.TODO: "à faire",
    TaskStatus.IN_PROGRESS: "en cours",
    TaskStatus.BLOCKED: "bloquée",
    TaskStatus.DONE: "terminée",
}


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def validation_detail(exc: ValidationError) -> str:
    """Premier probleme de validation, sous une forme lisible."""
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first["loc"]) or "valeur"
    return f"{location} : {first['msg']}"


def updated[M: DomainModel](model: M, **changes: Any) -> M:
    """Copie revalidee d'une entite immuable ; toute violation devient VALIDATION_ERROR."""
    try:
        return type(model).model_validate({**model.model_dump(), **changes})
    except ValidationError as exc:
        raise DomainError(ErrorCode.VALIDATION_ERROR, validation_detail(exc)) from exc


def build[M: DomainModel](model_type: type[M], **values: Any) -> M:
    """Construit une entite ; toute violation devient VALIDATION_ERROR."""
    try:
        return model_type.model_validate(values)
    except ValidationError as exc:
        raise DomainError(ErrorCode.VALIDATION_ERROR, validation_detail(exc)) from exc


class User(DomainModel):
    id: str
    display_name: DisplayName
    created_at: UtcDatetime
    # D-76 : profil local (prenom, nom, nom d'utilisateur unique). Pas une authentification.
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None


class Preferences(DomainModel):
    user_id: str
    response_length: ResponseLength = ResponseLength.STANDARD
    max_visible_tasks: Literal[1, 2, 3] = 3
    one_question_at_a_time: bool = True
    deadlines_enabled: bool = False
    cadence: Cadence = Cadence.FLEXIBLE
    display_timezone: str = "Europe/Paris"
    updated_at: UtcDatetime

    @field_validator("display_timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"fuseau horaire inconnu : {value}") from exc
        return value


class Project(DomainModel):
    id: str
    user_id: str
    title: ProjectTitle
    idea: Idea = ""
    target_outcome: Outcome | None = None
    constraints: list[ShortItem] = Field(default_factory=list, max_length=10)
    facts: list[ShortItem] = Field(default_factory=list, max_length=10)
    assumptions: list[ShortItem] = Field(default_factory=list, max_length=10)
    available_minutes_per_day: MinutesPerDay | None = None
    horizon_date: date | None = None
    status: ProjectStatus = ProjectStatus.DRAFT
    next_task_number: int = Field(default=1, ge=1)
    version: int = Field(default=1, ge=1)
    created_at: UtcDatetime
    updated_at: UtcDatetime
    # D-76 : projet commence par la conversation, titre provisoire jusqu'a sa confirmation.
    title_pending: bool = False
    # D-85 : pause reelle (le statut, le plan et les taches sont conserves).
    paused_at: UtcDatetime | None = None
    pause_note: str | None = Field(default=None, max_length=300)


class Phase(DomainModel):
    id: str
    project_id: str
    title: PhaseTitle
    exit_criterion: ExitCriterion | None = None
    position: int = Field(ge=0)


class Task(DomainModel):
    id: str
    project_id: str
    phase_id: str
    number: int = Field(ge=1)
    title: TaskTitle
    description: Description | None = None
    acceptance_criteria: Criterion
    status: TaskStatus = TaskStatus.TODO
    blocked_reason: BlockedReason | None = None
    priority: Priority = 3
    estimate_minutes: EstimateMinutes | None = None
    due_date: date | None = None
    position: int = Field(ge=0)
    completed_at: UtcDatetime | None = None
    version: int = Field(default=1, ge=1)
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @property
    def ref(self) -> str:
        return f"T{self.number}"

    @model_validator(mode="after")
    def _status_invariants(self) -> Task:
        # I-05 : completed_at <=> done ; blocked_reason <=> blocked.
        if (self.status is TaskStatus.DONE) != (self.completed_at is not None):
            raise ValueError(
                "completed_at doit etre renseigne si et seulement si la tache est done"
            )
        if (self.status is TaskStatus.BLOCKED) != (self.blocked_reason is not None):
            raise ValueError("blocked_reason doit etre renseigne si et seulement si bloquee")
        return self


class PendingAction(DomainModel):
    id: str
    user_id: str
    project_id: str | None
    action_type: ActionType
    payload: dict[str, Any]
    preview: list[dict[str, Any]]
    expected_versions: dict[str, Any]
    status: ActionStatus = ActionStatus.PENDING
    idempotency_key: str
    created_at: UtcDatetime
    expires_at: UtcDatetime
    decided_at: UtcDatetime | None = None
    result: dict[str, Any] | None = None


class ActivityEvent(DomainModel):
    id: str
    user_id: str
    project_id: str | None = None
    task_id: str | None = None
    pending_action_id: str | None = None
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    reverts_event_id: str | None = None
    created_at: UtcDatetime


class ConversationThread(DomainModel):
    id: str
    user_id: str
    project_id: str
    created_at: UtcDatetime
