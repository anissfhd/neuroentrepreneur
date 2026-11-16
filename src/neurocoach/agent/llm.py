"""Fournisseur LLM interchangeable (ARCHITECTURE section 7).

- ``FakeLLM`` : deterministe, hors ligne, scriptable ; utilise par tous les tests et la CI.
- ``LangChainProvider`` : modele de chat reel choisi par configuration (extras facultatifs).

Toute panne devient ``LLM_UNAVAILABLE`` et toute sortie invalide ``LLM_OUTPUT_INVALID`` :
aucune ecriture ne depend jamais d'une reponse du LLM non validee.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from neurocoach.agent.prompts import Message
from neurocoach.agent.schemas import (
    CoachBrief,
    CoachTurn,
    IntentResult,
    ProjectBrief,
    ResearchSpec,
)
from neurocoach.agent.streaming import StopStreaming
from neurocoach.config import ConfigurationError, Settings, read_provider_key
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.plans import PlanDraft
from neurocoach.domain.proposals import ChangeProposal

M = TypeVar("M", bound=BaseModel)


class LLMProvider(Protocol):
    def generate_structured(self, task: str, messages: list[Message], schema: type[M]) -> M: ...

    def generate_text(self, task: str, messages: list[Message]) -> str: ...


# --- Fournisseur reel -----------------------------------------------------------------


def _to_langchain(messages: list[Message]) -> list[tuple[str, str]]:
    roles = {"system": "system", "user": "human", "assistant": "ai"}
    return [(roles[message["role"]], message["content"]) for message in messages]


def _map_error(exc: Exception) -> DomainError:
    from langchain_core.exceptions import OutputParserException

    if isinstance(exc, ValidationError | OutputParserException | json.JSONDecodeError):
        return DomainError(ErrorCode.LLM_OUTPUT_INVALID)
    if type(exc).__name__ == "LengthFinishReasonError":
        # Reponse tronquee par le plafond de sortie (recette du 10/11/2026) : le service a
        # repondu, la sortie est inutilisable. Ce n'est pas une indisponibilite.
        return DomainError(ErrorCode.LLM_OUTPUT_INVALID)
    return DomainError(ErrorCode.LLM_UNAVAILABLE)


# Taches longues (analyse de recherche, R4 a R6) : meme modele, delai d'attente plus long.
LONG_TASKS = frozenset({"research_analysis", "research_comparison", "research_solutions"})
# D-78 : latence. Mesure reelle du 11/11/2026 : 25 a 28 s par message (classification 6 a 10 s
# puis clarification 16 a 21 s, effort de raisonnement par defaut, sans diffusion). Les taches
# de conversation passent a l'effort « low » (deja observe avec gpt-5-mini, campagnes du
# 10/11/2026) quand aucun effort n'est configure ; les plans et analyses gardent l'effort par
# defaut. Un effort configure (.env, role) l'emporte toujours.
FAST_TASK_EFFORT = {
    "classify_intent": "low",
    "clarify": "low",
    "coach_reply": "low",
    # D-79 : reponse, fiche et decision du tour en un seul appel. Le raisonnement precede le
    # premier fragment visible : un effort plus eleve retarderait d'autant la reponse.
    "coach_turn": "low",
    "coach_assessment": "low",
    "coach_response": "low",
    "coach_offer": "low",
    "verify_offer": "low",
    "research_spec": "low",  # D-80 : perimetre de recherche (sujet, zone, requetes)
    "research_conclusion": "low",  # D-82 : conclusion courte apres l'analyse
}
# Mesure reelle du 11/11/2026 (D-78) : a l'effort par defaut, la proposition de plan a depasse
# deux fois le delai de 30 s (60,6 s, aucune proposition). Effort « low » et delai des analyses.
# D-86 (campagne reelle V1) : l'adaptation d'un plan de 11 taches a depasse deux fois le delai
# de 30 s (60,6 s, aucune proposition) : meme traitement que la proposition de plan.
SLOW_TASK_EFFORT = {"draft_plan": "low", "draft_change": "low"}

# Diffusion de la reponse du coach : rappel recevant le texte deja produit (interface).
STREAM: ContextVar[Callable[[str], None] | None] = ContextVar("coach_stream", default=None)
# Mesures du tour : une entree par appel (tache, duree, temps jusqu'au premier fragment).
METRICS: ContextVar[list[dict[str, Any]] | None] = ContextVar("llm_metrics", default=None)


def record_call(task: str, started: float, first: float | None = None) -> None:
    calls = METRICS.get()
    if calls is not None:
        calls.append(
            {
                "task": task,
                "seconds": round(time.monotonic() - started, 3),
                "first_token": None if first is None else round(first - started, 3),
            }
        )


def _text_of(content: Any) -> str:
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content or "")


class LangChainProvider:
    def __init__(
        self,
        model: Any,
        *,
        structured_method: str | None = "json_schema",
        long_model: Any = None,
        task_models: Mapping[str, Any] | None = None,
        stream_json: bool = False,
    ) -> None:
        # « json_schema » : l'appel d'outil force n'est pas pris en charge par certains modeles
        # Claude recents (avertissement de langchain-anthropic constate en phase 3, D-41).
        self.model = model
        self.long_model = long_model  # meme configuration, delai des analyses
        self.structured_method = structured_method
        self.task_models = dict(task_models or {})  # D-78 : effort de raisonnement par tache
        # D-79 : sortie structuree diffusee (OpenAI, Chat Completions) ; sinon, appel simple.
        self.stream_json = stream_json

    def _model_for(self, task: str) -> Any:
        if task in self.task_models:
            return self.task_models[task]
        return self.long_model if task in LONG_TASKS and self.long_model is not None else self.model

    def generate_structured(self, task: str, messages: list[Message], schema: type[M]) -> M:
        started = time.monotonic()
        try:
            options = {"method": self.structured_method} if self.structured_method else {}
            runnable = self._model_for(task).with_structured_output(schema, **options)
            result = runnable.invoke(_to_langchain(messages))
        except Exception as exc:
            raise _map_error(exc) from exc
        finally:
            record_call(task, started)
        if isinstance(result, schema):
            return result
        try:
            return schema.model_validate(result)
        except ValidationError as exc:
            raise DomainError(ErrorCode.LLM_OUTPUT_INVALID) from exc

    def generate_text(self, task: str, messages: list[Message]) -> str:
        started = time.monotonic()
        try:
            response = self._model_for(task).invoke(_to_langchain(messages))
        except Exception as exc:
            raise _map_error(exc) from exc
        finally:
            record_call(task, started)
        text = _text_of(response.content).strip()
        if not text:
            raise DomainError(ErrorCode.LLM_OUTPUT_INVALID)
        return text

    def stream_text(
        self, task: str, messages: list[Message], on_delta: Callable[[str], None]
    ) -> str:
        """D-78 : meme appel que ``generate_text``, diffuse fragment par fragment ; le rappel
        recoit le texte deja produit. Une erreur reste une erreur (aucun texte de secours)."""
        started, first, parts = time.monotonic(), None, []
        try:
            for chunk in self._model_for(task).stream(_to_langchain(messages)):
                piece = _text_of(chunk.content)
                if not piece:
                    continue
                if first is None:
                    first = time.monotonic()
                parts.append(piece)
                on_delta("".join(parts))
        except Exception as exc:
            raise _map_error(exc) from exc
        finally:
            record_call(task, started, first)
        text = "".join(parts).strip()
        if not text:
            raise DomainError(ErrorCode.LLM_OUTPUT_INVALID)
        return text

    def stream_structured(
        self,
        task: str,
        messages: list[Message],
        schema: type[M],
        on_partial: Callable[[str], None],
    ) -> M | None:
        """D-79 : sortie structuree diffusee ; ``on_partial`` recoit le JSON deja produit.

        Le rappel peut lever ``StopStreaming`` : la generation est interrompue (connexion
        fermee) et la methode renvoie ``None``. Une erreur du service reste une erreur ; une
        erreur du rappel remonte telle quelle (elle n'est pas une panne du modele).
        """
        if not self.stream_json:
            result = self.generate_structured(task, messages, schema)
            try:
                on_partial(result.model_dump_json())
            except StopStreaming:
                return None
            return result
        started, first, parts, stopped = time.monotonic(), None, [], False
        iterator = None
        try:
            try:
                runnable = self._model_for(task).bind(response_format=schema)
                iterator = iter(runnable.stream(_to_langchain(messages)))
            except Exception as exc:
                raise _map_error(exc) from exc
            while True:
                try:
                    chunk = next(iterator)
                except StopIteration:
                    break
                except Exception as exc:
                    raise _map_error(exc) from exc
                piece = _text_of(chunk.content)
                if not piece:
                    continue
                if first is None:
                    first = time.monotonic()
                parts.append(piece)
                try:
                    on_partial("".join(parts))
                except StopStreaming:
                    stopped = True
                    break
        finally:
            if iterator is not None and hasattr(iterator, "close"):
                iterator.close()  # interrompt la generation si elle n'est pas finie
            record_call(task, started, first)
        if stopped:
            return None
        try:
            return schema.model_validate_json("".join(parts))
        except ValidationError as exc:
            raise DomainError(ErrorCode.LLM_OUTPUT_INVALID) from exc


def build_llm_provider(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    *,
    dotenv_path: Path | None = None,
) -> LLMProvider:
    """Choix par configuration ; la CI et les tests utilisent toujours ``fake``."""
    if settings.llm_provider == "fake":
        return FakeLLM()
    if "1" in (
        os.environ.get("NEUROCOACH_FORBID_REAL_LLM"),
        (environ or {}).get("NEUROCOACH_FORBID_REAL_LLM"),
    ):
        # Essais a blanc et tests : aucun fournisseur reel, quelle que soit la configuration.
        # M2 : le verrou du processus l'emporte aussi quand un environnement explicite est
        # fourni (avant, celui-ci le masquait).
        raise ConfigurationError(
            "Appels réels interdits dans ce processus (NEUROCOACH_FORBID_REAL_LLM=1)."
        )
    if not settings.llm_model:
        raise ConfigurationError("NEUROCOACH_LLM_MODEL est requis pour un fournisseur réel.")
    common: dict[str, Any] = {
        "model": settings.llm_model,
        "timeout": settings.llm_timeout_seconds,
        "max_tokens": settings.llm_max_output_tokens,
        "max_retries": settings.llm_max_retries,
    }
    key = read_provider_key(settings.llm_provider, environ, dotenv_path=dotenv_path)
    if key is not None:
        common["api_key"] = key  # SecretStr : masque dans toute representation
    if settings.llm_effort:
        # Claude recents et modeles de raisonnement OpenAI (gpt-5, o-series) ; un modele qui ne
        # raisonne pas refuserait ce parametre : il n'est envoye que s'il est configure.
        common["reasoning_effort"] = settings.llm_effort
    long_common = {
        **common,
        "timeout": max(settings.llm_timeout_seconds, settings.llm_timeout_seconds_analysis),
        "max_tokens": max(settings.llm_max_output_tokens, settings.llm_max_output_tokens_analysis),
    }
    try:
        if settings.llm_provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return LangChainProvider(
                ChatAnthropic(**common), long_model=ChatAnthropic(**long_common)
            )
        from langchain_openai import ChatOpenAI

        task_models = {}
        if not settings.llm_effort:
            # D-78 : conversation rapide ; un effort configure n'est jamais remplace.
            task_models = {
                task: ChatOpenAI(**{**common, "reasoning_effort": effort})
                for task, effort in FAST_TASK_EFFORT.items()
            }
            task_models.update(
                {
                    task: ChatOpenAI(**{**long_common, "reasoning_effort": effort})
                    for task, effort in SLOW_TASK_EFFORT.items()
                }
            )
        return LangChainProvider(
            ChatOpenAI(**common),
            long_model=ChatOpenAI(**long_common),
            task_models=task_models,
            stream_json=True,
        )
    except ImportError as exc:
        raise ConfigurationError(
            f'Extra manquant : pip install -e ".[{settings.llm_provider}]"'
        ) from exc
    except Exception as exc:
        # Ex. : ChatOpenAI exige la cle des la construction (constate en phase 3).
        raise ConfigurationError(
            f"Fournisseur {settings.llm_provider} non configuré : vérifiez la clé API dans .env "
            f"({type(exc).__name__})."
        ) from exc


# --- Routage par role (etape M2, docs/MULTI_MODEL_DESIGN.md) ----------------------------


class RoleProvider:
    """Aiguille chaque appel vers le fournisseur du role de sa tache (table fixe, roles.py).

    Aucun repli : l'erreur d'un role remonte telle quelle, aucun autre modele n'est appele.
    Les fournisseurs sont fixes a la construction (configuration du processus) : aucune
    entree utilisateur ni sortie du modele ne peut les changer.
    """

    def __init__(self, providers: Mapping[str, LLMProvider], assignments: Mapping[str, Any]):
        from neurocoach.llm_catalog import ROLES

        missing = set(ROLES) - set(providers)
        if missing:
            raise ConfigurationError(f"Rôles sans fournisseur : {sorted(missing)}")
        self._providers = dict(providers)
        self.assignments = dict(assignments)

    def provider_for(self, task: str) -> LLMProvider:
        from neurocoach.agent.roles import role_for

        return self._providers[role_for(task)]

    def generate_structured(self, task: str, messages: list[Message], schema: type[M]) -> M:
        return self.provider_for(task).generate_structured(task, messages, schema)

    def generate_text(self, task: str, messages: list[Message]) -> str:
        return self.provider_for(task).generate_text(task, messages)

    def stream_text(
        self, task: str, messages: list[Message], on_delta: Callable[[str], None]
    ) -> str:
        provider = self.provider_for(task)
        stream = getattr(provider, "stream_text", None)
        if stream is None:
            return provider.generate_text(task, messages)
        return stream(task, messages, on_delta)

    def stream_structured(
        self,
        task: str,
        messages: list[Message],
        schema: type[M],
        on_partial: Callable[[str], None],
    ) -> M | None:
        provider = self.provider_for(task)
        stream = getattr(provider, "stream_structured", None)
        if stream is not None:
            return stream(task, messages, schema, on_partial)
        result = provider.generate_structured(task, messages, schema)
        try:
            on_partial(result.model_dump_json())
        except StopStreaming:
            return None
        return result


def build_role_providers(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    *,
    dotenv_path: Path | None = None,
    today: date,
) -> LLMProvider:
    """Fournisseur de l'application.

    Sans variable de role : exactement ``build_llm_provider(settings)``, comme avant M2.
    Sinon : la configuration des roles est validee AVANT toute construction (une erreur
    n'entraine aucun appel ni aucun client), puis chaque role recoit son fournisseur. Le verrou
    ``NEUROCOACH_FORBID_REAL_LLM`` s'applique a chaque role (``build_llm_provider``).
    """
    from neurocoach.llm_catalog import ROLE_LABELS, raise_on_errors, resolve_roles, validate_roles

    roles = resolve_roles(settings)
    if all(len(assignment.inherited) == 3 for assignment in roles.values()):
        return build_llm_provider(settings, environ, dotenv_path=dotenv_path)
    raise_on_errors(validate_roles(settings, today=today))
    built: dict[tuple[str, str, str | None], LLMProvider] = {}
    providers: dict[str, LLMProvider] = {}
    for role, assignment in roles.items():
        key = (assignment.provider, assignment.model, assignment.effort)
        if key not in built:
            role_settings = settings.model_copy(
                update={
                    "llm_provider": assignment.provider,
                    "llm_model": assignment.model,
                    "llm_effort": assignment.effort,
                }
            )
            try:
                built[key] = build_llm_provider(role_settings, environ, dotenv_path=dotenv_path)
            except ConfigurationError as exc:
                raise ConfigurationError(f"Rôle {ROLE_LABELS[role]} : {exc}") from exc
        providers[role] = built[key]
    return RoleProvider(providers, roles)


def summarize_usage(metadata: Mapping[str, Any]) -> dict[str, int]:
    """Totaux de jetons releves par LangChain (``get_usage_metadata_callback``), tous modeles."""
    totals = {"input": 0, "cached_input": 0, "output": 0, "reasoning": 0}
    for usage in metadata.values():
        totals["input"] += usage.get("input_tokens", 0)
        totals["output"] += usage.get("output_tokens", 0)
        totals["cached_input"] += (usage.get("input_token_details") or {}).get("cache_read", 0)
        totals["reasoning"] += (usage.get("output_token_details") or {}).get("reasoning", 0)
    return totals


def format_usage(totals: Mapping[str, int]) -> str:
    return (
        f"jetons d'entrée : {totals['input']} (dont {totals['cached_input']} en cache) ; "
        f"jetons de sortie : {totals['output']} (dont {totals['reasoning']} de raisonnement)"
    )


# --- Faux fournisseur deterministe ------------------------------------------------------

_DATA = re.compile(r"<donnees_projet>\n(.*?)\n</donnees_projet>", re.DOTALL)
_TEXT = re.compile(r"<message_utilisateur>\n(.*?)\n</message_utilisateur>", re.DOTALL)
_REF = re.compile(r"\b[Tt]([1-9][0-9]{0,3})\b")

OUT_OF_SCOPE = re.compile(
    r"m[ée]decin|diagnosti|m[ée]dicament|th[ée]rapie|maladie|avocat|juridique|proc[èe]s|"
    r"imp[ôo]ts?|fiscal|placement|investi|bourse|crypto"
)
PREFERENCES = re.compile(
    r"pr[ée]f[ée]rence|r[ée]ponses? (plus )?(courtes?|d[ée]taill)|une seule phrase"
)
REPLAN = re.compile(
    r"pas avanc|en retard|pas eu le temps|replan|simplifi|trop (gros|long|dur)|d[ée]bord"
)
STATUS_QUERY = re.compile(
    r"o[ùu] en suis|\bprogr[eè]s\b|avancement|prochaine|quoi faire|reprendre o"
)
PLAN_REQUEST = re.compile(r"\bplan\b|par o[ùu] commencer|organis|[ée]tapes|commencer\s*\?")
HELP = re.compile(r"^(bonjour|salut|aide|help)\b|comment (ça|ca) marche")
OUTCOME = re.compile(
    r"\b(tester|valider|v[ée]rifier|objectif|obtenir|trouver|d'ici|r[ée]aliser|atteindre|"
    r"d[ée]crocher)\b"
)
CONSTRAINT = re.compile(r"\b(budget|sans|pas de|seulement|uniquement|maximum)\b")
_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
INJECTION = re.compile(r"ignore[sz]? (tes|les|vos) (r[èe]gles|instructions|consignes)|toi-m[êe]me")
SKIP = re.compile(r"^\s*(je\s+)?(passe|passer)\b|^\s*je ne sais pas\.?\s*$|^\s*aucune id[ée]e")
# D-79 : regles simples du faux modele (le vrai modele comprend sans motifs).
BUDGET = re.compile(r"(\d[\d\s.,]*)\s*(?:€|euros?)")
NO_BUDGET = re.compile(r"\b(pas de|sans|aucun) budget\b")
DECLINE_BUDGET = re.compile(
    r"(pr[ée]f[èe]re ne pas|ne (veux|souhaite) pas|pas envie de)\b.{0,40}\bbudget"
    r"|\bbudget\b.{0,40}(je passe|pas pr[ée]cis|ne sais pas)"
)
DECLINE_TIME = re.compile(
    r"(pr[ée]f[èe]re ne pas|ne (veux|souhaite) pas)\b.{0,40}\b(temps|disponibilit)"
)
EXPERIENCE = re.compile(
    r"d[ée]butant|aucune exp[ée]rience|jamais fait|exp[ée]riment[ée]|je travaille|"
    r"depuis \w+ ans|de m[ée]tier|de profession"
)
RESEARCH_OK = re.compile(
    r"^\s*(oui|ok|d'accord)\b.{0,60}\brecherche|\b(lancez|faites|pr[ée]parez)\b.{0,20}"
    r"\b(la|cette|une) (nouvelle |autre )?(recherche|v[ée]rification)"
)
RESEARCH_NO = re.compile(r"\b(pas de|sans|aucune) recherche\b|non merci.{0,30}recherche")
NO_PLAN = re.compile(
    r"\b(aucun|pas de|sans) plan\b|ne (construisez|faites|pr[ée]parez) (aucun|pas)"
)
# D-81 : une idee est une activite precise, pas une envie generale ni un profil.
IDEA_VERB = re.compile(
    r"\b(vendre|fabriquer|ouvrir|lancer|proposer|monter|cr[ée]er|offrir|d[ée]velopper|"
    r"donner des cours|faire du|faire de la)\b"
)
NOT_AN_IDEA = re.compile(
    r"aucune id[ée]e|pas (encore )?d'id[ée]e|ne sais pas (du tout )?(quoi|quel|dans quoi|lequel)|"
    r"cr[ée]er (mon|ma|une|un) (propre )?(business|entreprise|bo[iî]te|projet|activit[ée])\b"
)
INTERESTS = re.compile(r"\b(j'aime|j'adore|passionn\w*|m'int[ée]resse\w*|je suis fan)\b")
SKILLS = re.compile(
    r"\b(je sais|(bon|bonne|dou[ée]e?) en|comp[ée]tences?|je ma[iî]trise|j'ai appris)\b"
)
PAST_ATTEMPT = re.compile(
    r"\bj'ai d[ée]j[àa] (essay|tent|lanc|cr[ée]|ouvert|mont)|n'a pas march|[ée]chou|abandonn"
)
MOTIVATION = re.compile(
    r"\b(je veux (gagner|[êe]tre|devenir|avoir)|mon objectif|libert[ée]|revenu|ind[ée]pendan)"
)
ADVICE_NOW = re.compile(
    r"\b(tout de suite|directement|sans (questions?|diagnostic)|conseil imm[ée]diat|"
    r"dites-moi (juste|simplement))\b"
)
IDEAS_ASKED = re.compile(r"\b(quelles? id[ée]es|des id[ée]es|me recommandez)\b")
NOTE_REQUEST = re.compile(r"\b(retenez|conservez|gardez en t[êe]te|notez que|corrigez)\b")
NO_ATTEMPT = re.compile(r"\b(jamais (rien )?(essay|tent|cr[ée])|premi[èe]re fois|aucun projet)")
PAUSE_REQUEST = re.compile(r"\b(faire|prendre|mettre\w*)\b.{0,25}\bpause\b")
RESUME_REQUEST = re.compile(r"\b(reprendre|je reprends|on reprend|de retour|je reviens)\b")
TIME_CHANGE = re.compile(r"\b(plus que|moins de temps|seulement)\b.{0,30}\b(heures?|h|minutes?)\b")
BLOCKED_TOO = re.compile(r"\b(mais|par contre)\b.{0,60}\b(personne|bloqu|aucun|d[ée]courag)")
REAL_CHANGE = re.compile(r"\b(finalement|en fait|plut[ôo]t|je change|au lieu de)\b")


def _unpack(messages: list[Message]) -> tuple[dict[str, Any], str]:
    content = messages[-1]["content"] if messages else ""
    data_match = _DATA.search(content)
    text_match = _TEXT.search(content)
    facts = json.loads(data_match.group(1)) if data_match else {}
    text = text_match.group(1) if text_match else ""
    return facts, text.replace("&lt;", "<").replace("&gt;", ">")


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


class FakeLLM:
    """Regles deterministes en francais ; reponses scriptables pour les tests."""

    def __init__(self) -> None:
        self.scripted: dict[str, deque[Any]] = defaultdict(deque)
        self.calls: list[tuple[str, list[Message]]] = []
        self._peeked_classify = False

    def script(self, task: str, *responses: Any) -> FakeLLM:
        """Reponses a renvoyer dans l'ordre ; une exception est levee telle quelle."""
        self.scripted[task].extend(responses)
        return self

    def _scripted(self, task: str) -> Any:
        if not self.scripted[task]:
            return None
        item = self.scripted[task].popleft()
        if isinstance(item, BaseException):
            raise item
        return item

    def generate_structured(self, task: str, messages: list[Message], schema: type[M]) -> M:
        self.calls.append((task, messages))
        record_call(task, time.monotonic())
        if task == "coach_turn":
            facts, text = _unpack(messages)
            item = self._coach_turn(facts, text)
        elif task == "coach_assessment":
            facts, text = _unpack(messages)
            legacy = self._coach_turn(facts, text)
            data = legacy.model_dump() if hasattr(legacy, "model_dump") else legacy
            if isinstance(data, dict):
                data = dict(data)
                self.scripted["coach_response"].clear()
                self.scripted["coach_response"].append(
                    {key: data.pop(key, "") for key in ("reply", "question")}
                )
                data["research_requested"] = data.get("next_step") == "preparer_recherche"
                if data.get("plan_requested"):
                    data["intent"] = "demande_plan"
                    data["plan_request_quote"] = text
            item = data
        else:
            item = self._scripted(task)
        if item is None:
            facts, text = _unpack(messages)
            item = self._rule(task, facts, text)
        if isinstance(item, schema):
            return item
        try:
            return schema.model_validate(item)
        except ValidationError as exc:
            raise DomainError(ErrorCode.LLM_OUTPUT_INVALID) from exc

    def stream_structured(
        self,
        task: str,
        messages: list[Message],
        schema: type[M],
        on_partial: Callable[[str], None],
    ) -> M | None:
        """Diffusion simulee d'une sortie structuree : le JSON de ``generate_structured``,
        par fragments de 16 caracteres, dans l'ordre des champs du schema."""
        self._peeked_classify = False
        result = self.generate_structured(task, messages, schema)
        payload = result.model_dump_json()
        try:
            for end in range(16, len(payload) + 16, 16):
                on_partial(payload[:end])
        except StopStreaming:
            return None  # l'intention scriptee reste disponible pour la classification
        if self._peeked_classify and self.scripted["classify_intent"]:
            self.scripted["classify_intent"].popleft()
        return result

    def _coach_turn(self, facts: dict[str, Any], text: str) -> Any:
        """D-79 : reponse, fiche et decision en un seul objet.

        Commodite de test : sans script « coach_turn », l'objet est compose a partir des
        scripts des anciennes taches (fiche « clarify », texte « coach_reply », intention
        « classify_intent », consultee sans etre consommee si le tour est rerouté), ou des
        regles du faux modele."""
        scripted = self._scripted("coach_turn")
        if scripted is not None:
            return scripted
        queue = self.scripted["classify_intent"]
        peeked = queue[0] if queue and isinstance(queue[0], IntentResult) else None
        self._peeked_classify = peeked is not None
        intent = peeked.intent if peeked is not None else self._classify(facts, text).intent
        brief = self._scripted("clarify")
        if brief is None:
            brief = self._clarify(facts, text)
        elif not isinstance(brief, ProjectBrief):
            brief = ProjectBrief.model_validate(brief)
        reply = self._scripted("coach_reply")
        if reply is None:
            reply = self._reply_text(facts, text)
        step = "conseiller"
        if brief.wants_plan_now:
            step = "preparer_plan"
        elif brief.research_request:
            step = "preparer_recherche"  # une recherche demandee passe avant un plan propose
        # D-84 : comme la consigne, le plan est propose par une question ; « oui » le prepare.
        offer_plan = brief.ready_for_plan and step == "conseiller"
        lower = text.lower()
        # Consigne : un plan deja propose est repropose si le projet change reellement.
        already = (facts.get("preparation_du_plan") or {}).get("deja_proposee")
        if offer_plan and already and REAL_CHANGE.search(lower):
            step, offer_plan = "preparer_plan", False
        # D-81 : etape et question, comme un modele qui suit la consigne (regles simples).
        discovery = facts.get("decouverte") or {}
        has_idea = bool(brief.idea_summary or discovery.get("idee_retenue"))
        if has_idea or brief.wants_plan_now:
            stage = "idee_precise"
        elif ADVICE_NOW.search(lower):
            stage = "conseil_immediat"
        elif discovery.get("assez_pour_des_pistes") or brief.ideas_requested:
            stage = "pistes"
        else:
            stage = "decouverte"
        question = ""
        asked = " ".join(discovery.get("questions_deja_posees", []))
        remaining = [
            item for item in discovery.get("a_decouvrir", [])
            if not self._said(item, brief) and item not in asked
        ]  # fmt: skip
        if stage == "decouverte" and remaining:
            question = f"[Question simulée] Parlez-moi de {remaining[0]} ?"
        elif offer_plan and "plan" not in asked:
            question = "[Question simulée] Voulez-vous que je vous prépare un plan détaillé ?"
        change = bool((facts.get("preparation_du_plan") or {}).get("modification_demandee"))
        return CoachTurn(
            intent=intent,
            stage=stage,
            plan_change=change and not text.strip().endswith("?") and not brief.research_request,
            reply=str(reply),
            question=question,
            fiche=CoachBrief(
                idea_summary=brief.idea_summary,
                target_outcome=brief.target_outcome,
                available_minutes_per_day=brief.available_minutes_per_day,
                horizon_days=brief.horizon_days,
                budget=brief.budget,
                experience=brief.experience,
                constraints=brief.constraints,
                facts=brief.facts,
                assumptions=brief.assumptions[:3],
                declined=brief.skipped,
                project_title=brief.project_title,
                interests=brief.interests,
                skills=brief.skills,
                past_attempts=brief.past_attempts,
                motivation=brief.motivation,
                market=brief.market,
                notes=brief.notes,
            ),
            next_step=step,
            plan_requested=brief.wants_plan_now,
            real_change=bool(REAL_CHANGE.search(lower)),
            research_declined=brief.research_declined,
            plan_declined=brief.plan_declined,
            ideas_requested=brief.ideas_requested,
        )

    @staticmethod
    def _said(item: str, brief: ProjectBrief) -> bool:
        """Element du diagnostic donne dans CE message (le code ne le sait qu'au tour
        suivant) : le faux modele, comme le vrai, ne le redemande pas."""
        said = {
            "ses centres d'intérêt": brief.interests,
            "ses motivations": brief.motivation,
            "ce qu'elle sait faire (compétences)": brief.skills,
            "son expérience personnelle ou professionnelle": brief.experience,
            "ses essais passés de projet et ce qu'elle en a appris": brief.past_attempts,
            "ses objectifs": brief.target_outcome,
            "son temps disponible": brief.available_minutes_per_day,
            "son budget": brief.budget,
            "son pays ou sa zone, et sa clientèle": brief.market,
            "ses contraintes et préférences de travail": brief.constraints,
            "ses objectifs et motivations": brief.target_outcome or brief.motivation,
            "sa situation actuelle et son expérience": brief.experience,
        }
        return bool(said.get(item))

    def stream_text(
        self, task: str, messages: list[Message], on_delta: Callable[[str], None]
    ) -> str:
        """Diffusion simulee : le meme texte que ``generate_text``, mot apres mot."""
        text = self.generate_text(task, messages)
        words = text.split(" ")
        for index in range(1, len(words) + 1):
            on_delta(" ".join(words[:index]))
        return text

    def generate_text(self, task: str, messages: list[Message]) -> str:
        self.calls.append((task, messages))
        record_call(task, time.monotonic(), time.monotonic())
        item = self._scripted(task)
        if isinstance(item, BaseException):
            raise item
        if item is not None:
            return str(item)
        facts, text = _unpack(messages)
        return self._reply_text(facts, text)

    @staticmethod
    def _reply_text(facts: dict[str, Any], text: str) -> str:
        if INJECTION.search(text.lower()):
            # Comme le vrai modele lors de la premiere campagne : refus explicite.
            return (
                "Je ne peux pas ignorer mes règles ni confirmer à votre place : seul le bouton "
                "« Confirmer » enregistre une proposition."
            )
        if facts.get("analyse") and facts.get("demande") is not None:
            # D-82 : conclusion simulee, tiree des elements valides de l'analyse.
            ideas = facts["analyse"].get("idees") or [{}]
            level = ideas[0].get("niveau_de_preuve", "inconnu")
            known = next((e["texte"] for e in ideas[0].get("elements", [])), "rien de sourcé")
            return (
                f"[Conclusion simulée] Niveau de preuve : {level}. Ce que l'on sait : {known} "
                "Que souhaitez-vous faire ensuite ?"
            )
        if facts.get("project", {}).get("status") == "active":
            return "Merci, c'est noté. Voulez-vous voir vos prochaines actions ?"
        if facts.get("sujet"):
            # Faux modele : reprend le sujet recu, ce qui permet de verifier le contexte.
            return f"[Réponse simulée] Projet compris : {str(facts['sujet'])[:160]}"
        if text.strip():
            return f"[Réponse simulée] Message compris : {text.strip()[:160]}"
        return (
            "Je peux vous aider à clarifier votre idée, à construire un plan court "
            "et à suivre vos tâches. Que souhaitez-vous faire ?"
        )

    # --- regles -----------------------------------------------------------------------
    def _rule(self, task: str, facts: dict[str, Any], text: str) -> Any:
        rules = {
            "classify_intent": self._classify,
            "clarify": self._clarify,
            "draft_plan": self._plan,
            "draft_change": self._change,
            "research_analysis": self._analysis,
            "research_comparison": self._comparison,
            "research_solutions": self._solutions,
            "research_spec": self._research_spec,
        }
        if task not in rules:
            raise DomainError(ErrorCode.LLM_OUTPUT_INVALID)
        return rules[task](facts, text)

    @staticmethod
    def _research_spec(facts: dict[str, Any], text: str) -> ResearchSpec:
        """D-80 : sujet compris (fiche), zone dite dans la conversation, requetes par gabarit
        (le vrai modele les redige ; ici, de quoi verifier le traitement par le code)."""
        from neurocoach.domain.research import _TEMPLATES, ResearchCategory, detect_markets

        brief = facts.get("brief") or {}
        subject = str(brief.get("idea_summary") or facts.get("sujet") or text)[:200]
        said = [text, *(m["content"] for m in facts.get("history", []) if m["role"] == "user")]
        markets = (facts.get("recherche_demandee") or {}).get("marche_connu") or detect_markets(
            said
        )
        words = " ".join(re.findall(r"[\wÀ-ÿ'-]+", subject)[:6])
        queries = [
            {"category": c.value, "text": _TEMPLATES[c].format(offer=words, market="").strip()}
            for c in ResearchCategory
            if c is not ResearchCategory.SOLUTIONS
        ]
        return ResearchSpec(
            subject=subject, market=markets[0] if markets else None, queries=queries
        )

    @staticmethod
    def _analysis(facts: dict[str, Any], text: str) -> Any:
        """R4 : analyse deterministe tiree des extraits fournis (citations mot pour mot)."""
        from neurocoach.domain.analysis import IdeaAnalysisDraft

        sections: dict[str, list[dict[str, Any]]] = defaultdict(list)
        competitors: list[dict[str, Any]] = []
        target = {"prix": "prices", "avis": "needs", "problemes": "risks",
                  "marche": "opportunities", "solutions": "weaknesses",
                  "concurrence": "strengths", "temoignages": "needs"}  # fmt: skip
        for source in facts.get("sources", []):
            excerpt = source.get("extrait") or ""
            haystack = f"{source.get('titre')} {excerpt}"
            names = re.findall(r"Exemple(?: [A-ZÉ][\w'-]+){1,2}", haystack)
            title = str(source.get("titre") or "")
            if source.get("categorie") == "concurrence" and "," in title:
                names.append(title.split(",")[0].strip())  # « Nom, description »
            for name in names[:2]:
                if name not in [c["name"] for c in competitors]:
                    competitors.append({"name": name, "positioning": "acteur cité par la source",
                                        "sources": [source["id"]]})  # fmt: skip
            if excerpt.startswith("(référence seule"):
                continue
            sentence = _sentences(excerpt)[0][:300] if _sentences(excerpt) else ""
            section = target.get(source.get("categorie", ""), "strengths")
            if len(sentence) >= 3 and len(sections[section]) < 3:
                sections[section].append(
                    {"text": sentence, "kind": "fait", "sources": [source["id"]], "quote": sentence}
                )
        sections["strengths"].append({"text": "Une idée simple à tester à petite échelle.",
                                      "kind": "avis"})  # fmt: skip
        unknowns = [] if sections.get("prices") else ["Prix pratiqués non trouvés."]
        profile = facts.get("profil") or {}
        fit = [
            {
                "criterion": key,
                "rating": "mitige" if profile.get(key) else "inconnu",
                "reason": f"D'après vos mots : « {profile[key][0][:80]} »" if profile.get(key)
                else "",
            }
            for key in ("budget", "temps", "competences", "objectifs")
        ]  # fmt: skip
        idea = str(facts.get("idee", "cette idée"))[:150]
        pain_points = [
            {
                "theme": theme["theme"][:60],
                "statement": f"{theme['theme']} : {theme['citations'][0]['phrase']}"[:300],
                "scope": "tendance",  # volontairement surestime : le code doit corriger
                "sources": [c["source"] for c in theme["citations"][:3]],
                "quote": theme["citations"][0]["phrase"][:300],
            }
            for theme in facts.get("voix_clients", [])
            if theme.get("citations") and theme.get("sentiment") != "positif"
        ][:6]
        excluded = [t.lower() for t in facts.get("sens_a_ecarter", []) if t]
        off_topic = [
            s["id"]
            for s in facts.get("sources", [])
            if any(t in f"{s.get('titre')} {s.get('extrait')}".lower() for t in excluded)
        ][:30]
        return IdeaAnalysisDraft.model_validate(
            {
                "off_topic": off_topic,
                "evidence": "partiel",
                "pain_points": pain_points,
                "summary": f"{idea} : {len(facts.get('sources', []))} source(s) exploitée(s).",
                **{key: value[:5] for key, value in sections.items()},
                "competitors": competitors[:6],
                "unknowns": unknowns,
                "fit": fit,
            }
        )

    @staticmethod
    def _solutions(facts: dict[str, Any], text: str) -> Any:
        """R6 : options tirees des titres des sources (« Nom : description ») ; une approche
        sur mesure et une methode, sans chiffre ; cout cite seulement s'il figure dans
        l'extrait ; confiance haute pour verifier le plafond du code."""
        from neurocoach.domain.solutions import SolutionsDraft

        options = []
        for source in facts.get("sources", []):
            title = str(source.get("titre") or "").removeprefix("[SIMULÉ]").strip()
            name = title.split(":")[0].split(",")[0].split(" - ")[0].strip()
            if not name or len(name) > 80 or len(options) >= 3:
                continue
            excerpt = source.get("extrait") or ""
            price = re.search(r"[^.]*\d+(?:[.,]\d+)?\s*(?:€|\$|euros?)[^.]*\.?", excerpt)
            kind = "open_source" if "github" in source.get("domaine", "") else "saas"
            options.append({
                "name": name, "kind": kind,
                "how": f"Solution citée par {source.get('domaine')}.",
                "pros": ["Déjà disponible, sans développement."],
                "cons": ["Demande un temps de prise en main."],
                "cost": {"text": price.group(0).strip()[:200], "kind": "fait",
                         "sources": [source["id"]], "quote": price.group(0).strip()[:300]}
                if price else {"text": "", "kind": "inconnu"},
                "fit": "À tester sur un petit volume avant de s'engager.",
                "sources": [source["id"]],
            })  # fmt: skip
        options.append({
            "name": "Développement sur mesure", "kind": "sur_mesure",
            "how": "Construire un outil adapté au projet.",
            "pros": ["Adapté exactement au besoin."],
            "cons": ["Plus long et plus coûteux à mettre en place."],
            "fit": "Seulement si aucun outil existant ne convient.",
        })  # fmt: skip
        first = options[0]["name"] if len(options) > 1 else None
        problem = (facts.get("probleme") or {}).get("label", "ce problème")
        return SolutionsDraft.model_validate({
            "options": options,
            "ready_vs_custom": "Un outil existant se teste en quelques jours ; le sur mesure "
                               "ne se justifie qu'en cas d'échec de l'existant.",
            "recommended": first,
            "reasoning": f"Pour « {str(problem)[:80]} », commencer par l'option existante la "
                         "mieux documentée, puis mesurer.",
            "confidence": "elevee",
            "actions": [
                {"title": f"Tester {first}"[:120] if first else "Comparer deux solutions",
                 "done_when": "Un essai réalisé et noté.", "estimate_minutes": 30},
                {"title": "Mesurer l'effet sur le problème",
                 "done_when": "Un indicateur avant/après relevé.", "estimate_minutes": 20},
            ],
            "unknowns": ["Retours d'utilisateurs de ces solutions à vérifier."],
        })  # fmt: skip

    @staticmethod
    def _comparison(facts: dict[str, Any], text: str) -> Any:
        """R4 : classement par nombre de faits sources ; confiance volontairement haute pour
        verifier que le code la plafonne."""
        from neurocoach.domain.analysis import ComparisonDraft

        ideas = sorted(facts.get("idees", []), key=lambda i: -int(i.get("faits_sources", 0)))
        top = ideas[0] if ideas and ideas[0].get("faits_sources") else None
        return ComparisonDraft.model_validate(
            {
                "ranking": [
                    {"idea": i["numero"], "rank": r,
                     "rationale": f"{i.get('faits_sources', 0)} fait(s) sourcé(s)."}
                    for r, i in enumerate(ideas, 1)
                ],
                "trade_offs": ["Rapidité de démarrage contre niveau de concurrence observé."],
                "recommended_idea": top["numero"] if top else None,
                "reasoning": (
                    f"L'idée « {top['idee'][:80]} » est la mieux documentée par les sources."
                    if top else "Les sources ne permettent pas de trancher."
                ) + (
                    " Elle reste à confronter à votre budget et à votre temps disponible."
                    if any((facts.get("profil") or {}).values()) else ""
                ),
                "confidence": "elevee",
                "conditions": ["Si les premiers clients contactés ne montrent aucun intérêt."],
                "next_checks": [
                    f"Interroger cinq clients potentiels sur « {top['idee'][:60]} »."
                    if top else "Compléter la recherche sur les prix pratiqués."
                ],
            }
        )  # fmt: skip

    @staticmethod
    def _classify(facts: dict[str, Any], text: str) -> IntentResult:
        lower = text.lower()
        refs = _REF.findall(text)
        ref = f"T{refs[0]}" if refs else None
        if OUT_OF_SCOPE.search(lower):
            return IntentResult(intent="hors_perimetre")
        if INJECTION.search(lower):
            return IntentResult(intent="autre")
        if PREFERENCES.search(lower):
            return IntentResult(intent="preferences")
        if PAUSE_REQUEST.search(lower):
            # Raison : le message precedent de la personne, comme un modele qui lit history.
            said = facts.get("messages_precedents") or []
            note = said[-1][:300] if said else None
            return IntentResult(intent="pause_projet", pause_note=note)
        # D-87 : seconde demande du meme message, comme la consigne (regles simples).
        then = "replanifier" if TIME_CHANGE.search(lower) else None
        if BLOCKED_TOO.search(lower):
            then = "aide"
        if RESUME_REQUEST.search(lower):
            return IntentResult(intent="reprendre_projet", then_intent=then)
        if ref:
            if re.search(r"supprim|retir|enl[eè]ve", lower):
                return IntentResult(intent="supprimer_tache", task_ref=ref)
            if re.search(
                r"renomm|repouss|report|d[ée]cal|modifi|chang|priorit|[ée]ch[ée]ance|dur[ée]e",
                lower,
            ):
                return IntentResult(intent="modifier_tache", task_ref=ref)
            if re.search(r"bloqu", lower):
                reason = text.split("bloqu", 1)[1].split(" ", 1)[-1].strip(" .:") or "Non précisée"
                return IntentResult(
                    intent="changer_statut",
                    task_ref=ref,
                    target_status="blocked",
                    blocked_reason=reason[:300],
                )
            if re.search(r"rouvr|r[ée]ouvr", lower):
                return IntentResult(intent="changer_statut", task_ref=ref, target_status="todo")
            if re.search(r"termin|fini|\bfait\b|accompli", lower):
                return IntentResult(
                    intent="changer_statut", task_ref=ref, target_status="done", then_intent=then
                )
            if re.search(r"commenc|d[ée]marr|en cours|attaque", lower):
                return IntentResult(
                    intent="changer_statut", task_ref=ref, target_status="in_progress"
                )
        if REPLAN.search(lower):
            return IntentResult(intent="replanifier")
        if re.search(r"d[ée]cal|repouss|report", lower):
            return IntentResult(intent="modifier_tache")
        if re.search(r"\bajout", lower):
            return IntentResult(intent="ajouter_tache")
        if re.search(r"j'ai (termin|fini|boucl)|c'est (termin|fini)", lower):
            return IntentResult(intent="changer_statut", target_status="done", then_intent=then)
        if STATUS_QUERY.search(lower):
            return IntentResult(intent="etat_projet")
        if PLAN_REQUEST.search(lower):
            return IntentResult(intent="demande_plan")
        if HELP.search(lower.strip()) and len(lower) < 60:
            return IntentResult(intent="aide")
        return IntentResult(intent="information_projet", user_text_summary=text[:300])

    @staticmethod
    def _clarify(facts: dict[str, Any], text: str) -> ProjectBrief:
        lower = text.lower()
        values: dict[str, Any] = {}
        missing = facts.get("brief", {}).get("missing", [])
        if SKIP.search(lower) and missing:
            values["skipped"] = [missing[0]]
        minutes = re.search(r"(\d{1,3})\s*(?:min\b|minutes)", lower)
        hours = re.search(r"(\d{1,2})\s*h(?:eures?)?\s*(?:par|/)\s*jour", lower)
        if minutes:
            values["available_minutes_per_day"] = max(5, min(720, int(minutes.group(1))))
        elif hours:
            values["available_minutes_per_day"] = min(720, int(hours.group(1)) * 60)
        elif "demi-heure" in lower or "demi heure" in lower:
            values["available_minutes_per_day"] = 30
        weeks = re.search(r"(\d{1,2})\s*semaines?", lower)
        if weeks:
            values["horizon_days"] = min(365, int(weeks.group(1)) * 7)
        facts_found, constraints = [], []
        for sentence in _sentences(text):
            low = sentence.lower()
            if sentence.endswith("?"):
                continue  # une question n'est ni un fait ni un objectif
            if "target_outcome" not in values and OUTCOME.search(low):
                values["target_outcome"] = sentence.rstrip(".")[:300]
            elif CONSTRAINT.search(low):
                constraints.append(sentence[:200])
            elif re.search(r"\b(je veux|j'ai|je suis|je vends|je fabrique)\b", low):
                facts_found.append(sentence[:200])
        values["facts"] = facts_found[:5]
        values["constraints"] = constraints[:10]
        budget = BUDGET.search(lower)
        if NO_BUDGET.search(lower):
            values["budget"] = "aucun budget"
        elif budget and not DECLINE_BUDGET.search(lower):
            values["budget"] = f"{budget.group(1).strip()} €"[:200]
        declined = [*values.get("skipped", [])]
        if DECLINE_BUDGET.search(lower):
            declined.append("budget")
        if DECLINE_TIME.search(lower):
            declined.append("temps_disponible")
        if declined:
            values["skipped"] = list(dict.fromkeys(declined))
        from neurocoach.domain.research import detect_markets

        markets = detect_markets([text])
        if markets or "francophone" in lower:
            zone = ", ".join(markets) or "pays francophones"
            values["market"] = zone + (" ; clientèle francophone" if "francophone" in lower else "")
        if NO_ATTEMPT.search(lower):
            values["past_attempts"] = "aucun projet tenté"
        if NOTE_REQUEST.search(lower):
            values["notes"] = [s[:200] for s in _sentences(text) if NOTE_REQUEST.search(s.lower())][
                :3
            ]
        values["ideas_requested"] = bool(IDEAS_ASKED.search(lower))
        experience = EXPERIENCE.search(lower)
        if experience:
            sentence = next((s for s in _sentences(text) if EXPERIENCE.search(s.lower())), None)
            values["experience"] = (sentence or experience.group(0))[:200]
        values["research_request"] = bool(RESEARCH_OK.search(lower))
        values["research_declined"] = bool(RESEARCH_NO.search(lower))
        # D-78 : decisions du tour, comme le vrai modele (regles simples du faux modele).
        for rx, key in ((INTERESTS, "interests"), (SKILLS, "skills"),
                        (PAST_ATTEMPT, "past_attempts"), (MOTIVATION, "motivation")):  # fmt: skip
            found = next((s for s in _sentences(text) if rx.search(s.lower())), None)
            if found:
                values[key] = found[:300]
        if len(lower.split()) >= 5 and IDEA_VERB.search(lower) and not NOT_AN_IDEA.search(lower):
            values["idea_summary"] = text[:300]
            from neurocoach.domain.profiles import FALLBACK_TITLE, suggest_title

            title = suggest_title(text)
            if title != FALLBACK_TITLE:
                values["project_title"] = title[:60]
        previous = facts.get("brief", {})
        known = facts.get("connu", {})
        skipped = set(previous.get("skipped", [])) | set(values.get("skipped", []))
        minutes = (
            values.get("available_minutes_per_day")
            or previous.get("available_minutes_per_day")
            or known.get("minutes_par_seance")
        )
        budget_known = (
            values.get("budget") or previous.get("budget") or known.get("budget_eur") is not None
        )
        # Accord court a la derniere proposition du coach, ou plan demande explicitement.
        agreement = re.match(r"^\s*(oui|ok|d'accord|ça me va|ca me va|parfait)\b", lower)
        values["plan_declined"] = bool(NO_PLAN.search(lower))
        values["wants_plan_now"] = (
            bool((re.search(r"\bplan\b", lower) and not RESEARCH_OK.search(lower)) or agreement)
            and not values["plan_declined"]
        )
        # Comme un modele qui suit la consigne D-79 : plan de sa propre initiative seulement
        # quand disponibilite et budget sont connus (ou refuses).
        values["ready_for_plan"] = bool(
            (minutes or "temps_disponible" in skipped)
            and (budget_known or "budget" in skipped)
            and (values.get("idea_summary") or previous.get("idea_summary") or facts.get("sujet"))
        )
        return ProjectBrief(**values)

    @staticmethod
    def _plan(facts: dict[str, Any], text: str) -> PlanDraft:
        brief = facts.get("brief", {})
        minutes = brief.get("available_minutes_per_day")
        deadlines = facts.get("preferences", {}).get("deadlines_enabled", False)

        def estimate(value: int) -> int:
            return max(5, min(value, minutes)) if minutes else value

        def due(days: int) -> int | None:
            return days if deadlines else None

        objective = (brief.get("target_outcome") or "Valider l'idée auprès de clients")[:200]
        return PlanDraft.model_validate(
            {
                "objective": objective if len(objective) >= 3 else "Valider l'idée",
                "assumptions": [a for a in brief.get("assumptions", [])][:5],
                "phases": [
                    {
                        "title": "Valider l'intérêt",
                        "exit_criterion": "Trois retours de clients potentiels recueillis",
                        "tasks": [
                            {
                                "key": "client",
                                "title": "Décrire le client visé",
                                "acceptance_criteria": "Une phrase décrit le client idéal",
                                "estimate_minutes": estimate(20),
                                "priority": 4,
                                "due_in_days": due(2),
                            },
                            {
                                "key": "questions",
                                "title": "Préparer cinq questions",
                                "acceptance_criteria": "Cinq questions ouvertes sont rédigées",
                                "estimate_minutes": estimate(20),
                                "depends_on": ["client"],
                                "due_in_days": due(4),
                            },
                            {
                                "key": "entretiens",
                                "title": "Interroger trois personnes",
                                "acceptance_criteria": "Trois échanges sont notés",
                                "estimate_minutes": estimate(30),
                                "depends_on": ["questions"],
                                "due_in_days": due(7),
                            },
                        ],
                    }
                ],
            }
        )

    @staticmethod
    def _change(facts: dict[str, Any], text: str) -> ChangeProposal:
        lower = text.lower()
        refs = [f"T{number}" for number in _REF.findall(text)]
        ordinal = re.search(r"\b(premi[eè]re|deuxi[eè]me|troisi[eè]me)\b", lower)
        if not refs and ordinal:
            refs = [f"T{'pdt'.index(ordinal.group(1)[0]) + 1}"]
        quoted = re.search(r"[«\"]\s*(.+?)\s*[»\"]", text)
        intent = facts.get("intent")
        changes: list[dict[str, Any]] = []
        if intent == "replanifier" or (not refs and REPLAN.search(lower)):
            target = (facts.get("next_actions") or [None])[0] or next(
                (t["ref"] for t in facts.get("tasks", []) if t["status"] != "done"), None
            )
            task = next((t for t in facts.get("tasks", []) if t["ref"] == target), None)
            if task is None:
                raise DomainError(ErrorCode.LLM_OUTPUT_INVALID)
            short = f"Version courte : {task['title']}"[:120]
            return ChangeProposal(
                changes=[
                    {
                        "op": "update",
                        "task_ref": task["ref"],
                        "fields": {"title": short, "estimate_minutes": 15},
                    }
                ],
                rationale="Une étape plus petite pour repartir en douceur, à votre rythme.",
            )
        if re.search(r"supprim|retir|enl[eè]ve", lower):
            changes = [{"op": "delete", "task_ref": ref} for ref in refs]
        elif intent == "ajouter_tache" or re.search(r"\bajout", lower):
            title = quoted.group(1) if quoted else "Nouvelle tâche"
            changes = [
                {
                    "op": "add",
                    "fields": {
                        "title": title[:120],
                        "acceptance_criteria": "La tâche est réalisée et notée",
                    },
                }
            ]
        elif refs:
            fields: dict[str, Any] = {}
            if quoted:
                fields["title"] = quoted.group(1)[:120]
            day = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", text)
            if day:
                year = int(day.group(3) or str(facts.get("today", "2026-01-01"))[:4])
                fields["due_date"] = date(year, int(day.group(2)), int(day.group(1))).isoformat()
            weekday = re.search(r"\b(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b", lower)
            if weekday and not day:
                today = date.fromisoformat(str(facts.get("today", "2026-01-01")))
                target = _WEEKDAYS.index(weekday.group(1))
                fields["due_date"] = (
                    today + timedelta(days=(target - today.weekday() - 1) % 7 + 1)
                ).isoformat()
            # « moins important » avant « important », qu'il contient.
            if re.search(r"moins important|plus tard", lower):
                fields["priority"] = 1
            elif re.search(r"urgent|prioritaire|important", lower):
                fields["priority"] = 5
            minutes = re.search(r"(\d{1,3})\s*(?:min\b|minutes)", lower)
            if minutes:
                fields["estimate_minutes"] = int(minutes.group(1))
            # Sans champ reconnu : modification vide, comme gpt-5.6-terra en R0 (« Modifie T2 »).
            changes = [{"op": "update", "task_ref": refs[0], "fields": fields}]
        if not changes:
            raise DomainError(ErrorCode.LLM_OUTPUT_INVALID)
        return ChangeProposal(changes=changes, rationale="Modification demandée.")
