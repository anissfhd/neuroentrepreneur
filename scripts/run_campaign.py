"""Campagne d'evaluation en plusieurs executions sous UN plafond total partage.

Usage :
  python scripts/run_campaign.py                    essai a blanc : faux fournisseur IMPOSE
  python scripts/run_campaign.py --plan compare-coaching --models gpt-5-mini,gpt-5.6-terra
                                                    memes scenarios et parametres par modele (M4)
  python scripts/run_campaign.py --plan compare-coaching \
      --configs gpt-5-mini:default:0.90,gpt-5.6-terra:medium:3.00 --pass-ids 1
                                                    couples modele + effort, plafond par couple
  python scripts/run_campaign.py --summary --ledger data/evaluations/registre.jsonl
                                                    couts par campagne, role et modele (sans appel)
  python scripts/run_campaign.py --real-api --total-usd 0.70 --price-input 2 --price-output 12 \
      --ledger data/evaluations/registre-terra.jsonl
                                                    appels reels PAYANTS
  ... --resume                                      reprise apres interruption

Securite :
- sans --real-api, chaque execution recoit NEUROCOACH_LLM_PROVIDER=fake et
  NEUROCOACH_FORBID_REAL_LLM=1, et aucune option reelle : .env ne peut rien declencher ;
- avec --real-api, toutes les executions partagent le meme registre (--ledger) : chaque appel
  y est reserve au pire cas AVANT l'envoi, et le plafond total est verifie par l'execution
  elle-meme, a partir du registre relu, avant chaque appel ;
- une reprise (--resume) relit le registre : les depenses passees, y compris les appels
  interrompus (comptes au pire cas), sont deduites ; les executions terminees sont sautees.
Aucune cle n'est affichee ; .env n'est jamais modifie.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = re.compile(r"sk-[A-Za-z0-9_-]{10,}")
SUMMARY = re.compile(r"conformes|Appels|Consommation|Budget|arrêtée|Essai à blanc|erreur", re.I)

# Campagne de confirmation gpt-5.6-terra (autorisation demandee le 10 novembre 2026).
R0_FAILURES = ",".join(
    [
        "Dialogue de référence",
        "« Oui » écrit au lieu du bouton",
        "Changement d'avis pendant une proposition",
        "Formulation imprévue",
        "Retard et replanification confirmée",
        "Première idée dans un autre domaine",
        "Modification sans précision",
    ]
)


@dataclass(frozen=True)
class Run:
    label: str
    script: str
    planned_usd: float | None  # None : part egale du plafond total (comparaisons)
    max_calls: int
    extra: tuple[str, ...] = ()
    role: str = "coaching"
    model: str | None = None  # None : le modele explicite --model
    effort: str | None = None  # None : l'effort --effort de la campagne
    pass_id: str = "1"
    config_cap: float | None = None  # plafond du couple modele + effort, tous passages
    config_key: str = ""  # prefixe commun aux passages d'un meme couple (registre)


# Verification courte des corrections D-61 (plafond demande : 0,10 $ au plus).
D61_SCENARIOS = ",".join(
    [
        "Formulation imprévue",
        "Demande de changement vague",
        "Retard et replanification",
        "Fatigue et plan trop lourd",
    ]
)
PLANS = {
    "terra-confirmation": (
        Run("coaching-1", "evaluate_llm.py", 0.25, 70),
        Run("coaching-2", "evaluate_llm.py", 0.25, 70),
        Run("coaching-echecs-r0", "evaluate_llm.py", 0.12, 35, ("--only", R0_FAILURES)),
        Run("strategie", "evaluate_strategy_r0.py", 0.10, 6, ("--repetitions", "1"), "strategy"),
    ),
    "d61": (Run("d61-coaching", "evaluate_llm.py", 0.10, 20, ("--only", D61_SCENARIOS)),),
}
PLAN = PLANS["terra-confirmation"]
# M4 : comparaisons equitables. Memes scenarios, memes criteres, memes parametres (effort
# low, delai 60 s, aucune nouvelle tentative, meme plafond de sortie) pour chaque modele.
COMPARISONS = {
    # max_calls None : borne certaine calculee a partir des scenarios (3 appels par message).
    "compare-coaching": ("coaching", "evaluate_llm.py", None, ()),
    "compare-strategy": ("strategy", "evaluate_strategy_r0.py", None, ("--repetitions", "2")),
    "compare-simple": ("simple", "evaluate_simple_tasks.py", None, ("--repetitions", "1")),
}
DEFAULT_MODELS = "gpt-5-mini,gpt-5.6-terra,gpt-5.6-luna"
EFFORTS = ("default", "low", "medium", "high")


def upper_bound_calls(role: str, repetitions: int) -> int:
    """Nombre d'appels qu'une execution ne peut pas depasser (etape 0) : 3 par message de
    coaching (classification, clarification, plan), relances comprises ; 1 par cas sinon."""
    if role == "coaching":
        ev = _evaluator()
        return sum(
            3 * sum(1 for step in steps if step[0] in ("say", "ensure_pending"))
            for _, _, steps in ev.SCENARIOS
        )
    if role == "strategy":
        return 5 * repetitions
    return 11 * repetitions


def parse_configs(
    text: str | None, models: list[str], effort: str
) -> list[tuple[str, str, float | None]]:
    """« modele:effort[:plafond] » separes par des virgules ; sinon chaque modele de --models
    avec l'effort de la campagne."""
    if not text:
        return [(model, effort, None) for model in models]
    configs = []
    for item in text.split(","):
        parts = [p.strip() for p in item.split(":")]
        if len(parts) not in (2, 3) or not all(parts):
            raise SystemExit(
                f"configuration illisible : « {item} » (attendu modele:effort[:plafond])"
            )
        cap = float(parts[2]) if len(parts) == 3 else None
        configs.append((parts[0], parts[1], cap))
    return configs


def build_plan(args: argparse.Namespace) -> tuple[Run, ...]:
    if args.plan in PLANS:
        return tuple(
            Run(
                run.label,
                run.script,
                run.planned_usd,
                args.max_calls or run.max_calls,
                run.extra,
                run.role,
                run.model,
                run.effort,
                pass_id,
                None,
                run.label,
            )
            for pass_id in args.pass_ids
            for run in PLANS[args.plan]
        )
    role, script, max_calls, extra = COMPARISONS[args.plan]
    if args.repetitions is not None and "--repetitions" in extra:
        extra = ("--repetitions", str(args.repetitions))
    repetitions = int(extra[1]) if "--repetitions" in extra else 1
    calls = args.max_calls or max_calls or upper_bound_calls(role, repetitions)
    runs = []
    for pass_id in args.pass_ids:  # passage 1 de tous les couples, puis passage 2...
        for model, effort, cap in args.configs:
            key = f"{role}-{model}-{effort}"
            label = f"{key}-p{pass_id}"
            runs.append(
                Run(label, script, None, calls, extra, role, model, effort, pass_id, cap, key)
            )
    return tuple(runs)


def run_model(args: argparse.Namespace, run: Run) -> str | None:
    return run.model or args.model


def _evaluator():
    spec = importlib.util.spec_from_file_location(
        "evaluate_llm", ROOT / "scripts" / "evaluate_llm.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("evaluate_llm", module)
    spec.loader.exec_module(module)
    return module


def prices(args: argparse.Namespace, model: str | None) -> tuple[float, float]:
    """Tarifs du modele : ceux du catalogue (M4), sauf tarifs explicites (verifies par
    l'execution, qui refuse un ecart avec le catalogue)."""
    if args.price_input is not None and args.price_output is not None:
        return args.price_input, args.price_output
    spec = _evaluator().default_catalog().get(model or "")
    if spec is None or spec.price_input is None or spec.price_output is None:
        raise SystemExit(f"Tarifs inconnus pour {model or '(aucun modèle)'} : campagne arrêtée.")
    return spec.price_input, spec.price_output


def worst_call_usd(args: argparse.Namespace, model: str | None = None) -> float:
    """Pire cas d'un appel : 6 000 jetons d'entree (large) et le plafond de sortie entier."""
    price_input, price_output = prices(args, model or args.model)
    return (6000 * price_input + args.max_output_tokens * price_output) / 1e6


def child_env(args: argparse.Namespace, run: Run | None = None) -> dict[str, str]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if not args.real_api:
        env.update(NEUROCOACH_LLM_PROVIDER="fake", NEUROCOACH_FORBID_REAL_LLM="1")
        return env
    env.pop("NEUROCOACH_FORBID_REAL_LLM", None)
    model = run_model(args, run) if run else args.model
    spec = _evaluator().default_catalog().get(model or "")
    env.update(
        NEUROCOACH_LLM_PROVIDER=spec.provider if spec else args.provider,
        # Etape 0 : l'effort est passe explicitement (--effort) a chaque execution.
        NEUROCOACH_LLM_TIMEOUT_SECONDS="60",
        NEUROCOACH_LLM_MAX_RETRIES="0",  # aucune nouvelle tentative facturee en silence
        # Plafond de sortie du client (et donc du pire cas reserve) pour cette campagne seulement.
        NEUROCOACH_LLM_MAX_OUTPUT_TOKENS=str(args.max_output_tokens),
    )
    return env


def child_command(args: argparse.Namespace, run: Run, cap: float | None) -> list[str]:
    cmd = [sys.executable, str(ROOT / "scripts" / run.script), *run.extra]
    cmd += ["--max-calls", str(run.max_calls), "--role", run.role, "--campaign", args.campaign]
    cmd += ["--effort", run.effort or args.effort, "--pass-id", run.pass_id]
    model = run_model(args, run)
    if model:
        cmd += ["--model", model]
    if args.out_dir:
        cmd += ["--out-dir", str(args.out_dir)]
    if args.real_api:
        price_input, price_output = prices(args, model)
        cmd += [
            "--real-api",
            "--budget-usd", f"{cap:.4f}",
            "--price-input", str(price_input),
            "--price-output", str(price_output),
            "--ledger", str(args.ledger),
            "--campaign-cap-usd", str(args.total_usd),
            "--run-label", run.label,
        ]  # fmt: skip
    return cmd


def plan_runs(args: argparse.Namespace, ledger) -> list[tuple[Run, float | None, str | None]]:
    """Plafond de chaque execution = min(prevu, reste du plafond total d'apres le registre)."""
    plan = build_plan(args)
    if not args.real_api:
        return [(run, None, None) for run in plan]
    done = {name for name, status in ledger.runs().items() if status == "done"}
    share = round(args.total_usd / max(1, len(args.configs)), 4)  # part par couple, sans plafond
    planned = []
    for run in plan:
        if args.resume and run.label in done:
            planned.append((run, None, "déjà terminée (registre)"))
            continue
        if run.planned_usd is not None:
            planned.append((run, run.planned_usd, None))
        else:  # plafond du couple, partage entre ses passages (le reste reel est relu)
            planned.append((run, run.config_cap if run.config_cap is not None else share, None))
    return planned


def run_cap(args: argparse.Namespace, ledger, run: Run, planned: float) -> tuple[float, float]:
    """Plafond de l'execution : ni plus que ce qu'il reste au couple, ni plus que le reste
    global. Renvoie (plafond, reste global)."""
    remaining = round(args.total_usd - ledger.committed_usd(), 4)
    cap = min(planned, remaining)
    if run.config_key and run.planned_usd is None:
        spent = ledger.committed_for(run=run.config_key + "-p", campaign=args.campaign)
        cap = min(cap, planned - spent)
    return round(cap, 4), remaining


def validate_plan(args: argparse.Namespace) -> list[str]:
    """Avant tout appel : chaque modele du plan existe, a des tarifs, et un fournisseur reel."""
    catalog = _evaluator().default_catalog()
    errors = []
    for run in build_plan(args):
        model = run_model(args, run)
        effort = run.effort or args.effort
        spec = catalog.get(model or "")
        if spec is None:
            errors.append(f"{run.label} : modèle {model or '(aucun)'} absent du catalogue")
        elif spec.price_input is None or spec.price_output is None:
            errors.append(f"{run.label} : tarifs de {spec.id} inconnus")
        elif effort not in EFFORTS:
            errors.append(
                f"{run.label} : effort « {effort} » non pris en charge ({', '.join(EFFORTS)})"
            )
        elif (
            effort != "default"
            and spec.confirmed("efforts")
            and spec.efforts
            and effort not in spec.efforts
        ):
            errors.append(f"{run.label} : effort « {effort} » refusé par {spec.id}")
    caps = [cap for _, _, cap in args.configs if cap is not None]
    if caps and args.total_usd is not None and sum(caps) > args.total_usd + 1e-9:
        errors.append(
            f"somme des plafonds par couple ({sum(caps):.2f} $) supérieure au plafond global "
            f"({args.total_usd:.2f} $) : un couple pourrait ne pas terminer"
        )
    return errors


def summary_lines(ledger) -> list[str]:
    rows = ledger.summary()
    if not rows:
        return ["Registre vide : aucun appel."]
    lines = [
        f"{row['campaign'] or '—'} · {row['role'] or '—'} · {row['model'] or '—'} · "
        f"{row.get('effort') or '—'} : "
        f"{row['calls']} appel(s), {row['usd']:.4f} $"
        for row in rows
    ]
    lines.append(f"Total engagé : {ledger.committed_usd():.4f} $")
    return lines


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--real-api", action="store_true", help="appels reels PAYANTS")
    parser.add_argument("--total-usd", type=float, help="plafond total strict de la campagne")
    parser.add_argument("--price-input", type=float, help="dollars par million de jetons")
    parser.add_argument("--price-output", type=float, help="dollars par million de jetons")
    parser.add_argument("--ledger", type=Path, help="registre partage (JSON Lines)")
    parser.add_argument("--provider", default="openai", choices=["openai", "anthropic"])
    parser.add_argument("--model", help="modele candidat explicite (plans hors comparaison)")
    parser.add_argument(
        "--models", default=DEFAULT_MODELS, help="modeles compares, separes par des virgules"
    )
    parser.add_argument("--campaign", help="nom de la campagne (defaut : nom du registre)")
    parser.add_argument("--summary", action="store_true", help="couts du registre, sans appel")
    parser.add_argument("--resume", action="store_true", help="reprise : registre existant")
    parser.add_argument(
        "--plan", default="terra-confirmation", choices=sorted([*PLANS, *COMPARISONS])
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=4000,
        help="plafond de sortie par appel (64 a 16 000) ; le pire cas reserve en depend",
    )
    parser.add_argument("--out-dir", type=Path, help="dossier des comptes rendus")
    # Etape 0 (comparaison v2) : controle explicite de chaque dimension.
    parser.add_argument(
        "--configs", help="couples modele:effort[:plafond $], separes par des virgules"
    )
    parser.add_argument(
        "--effort", default="low", choices=EFFORTS, help="effort par defaut des executions"
    )
    parser.add_argument("--pass-ids", default="1", help="passages independants, ex. 1,2,3")
    parser.add_argument("--max-calls", type=int, help="nombre maximal d'appels par execution")
    parser.add_argument("--repetitions", type=int, help="essais (strategie, taches simples)")
    args = parser.parse_args(argv)
    args.models = [m.strip() for m in args.models.split(",") if m.strip()]
    args.pass_ids = [p.strip() for p in args.pass_ids.split(",") if p.strip()]
    if not args.pass_ids or len(set(args.pass_ids)) != len(args.pass_ids):
        parser.error("--pass-ids : identifiants de passage distincts attendus")
    if args.max_calls is not None and args.max_calls < 1:
        parser.error("--max-calls doit etre strictement positif")
    args.configs = parse_configs(args.configs, args.models, args.effort)
    args.campaign = args.campaign or (args.ledger.stem if args.ledger else "essai-a-blanc")
    if args.summary:
        if args.ledger is None:
            parser.error("--summary exige --ledger")
        return args
    if args.real_api:
        required = {"--total-usd": args.total_usd, "--ledger": args.ledger}
        if args.plan in PLANS:
            required["--model"] = args.model  # M4 : un test reel exige un modele precis
        missing = [name for name, value in required.items() if value is None]
        if missing:
            parser.error(f"--real-api exige {', '.join(missing)}")
        if args.total_usd <= 0:
            parser.error("--total-usd doit etre strictement positif")
        if not 64 <= args.max_output_tokens <= 16000:
            parser.error("--max-output-tokens doit etre compris entre 64 et 16 000")
        if os.environ.get("NEUROCOACH_FORBID_REAL_LLM") == "1":
            parser.error("appels reels interdits dans ce processus (NEUROCOACH_FORBID_REAL_LLM=1)")
        used = args.ledger.is_file() and args.ledger.stat().st_size > 0
        if used and not args.resume:
            parser.error("registre deja utilise : ajoutez --resume pour reprendre la campagne")
        if args.resume and not used:
            parser.error("--resume : registre introuvable ou vide")
        errors = validate_plan(args)
        if errors:
            parser.error("configuration invalide, aucun appel : " + " ; ".join(errors))
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse(sys.argv[1:] if argv is None else argv)
    ev = _evaluator()
    if args.summary:
        for line in summary_lines(ev.Ledger(args.ledger, args.total_usd or 1.0)):
            print(line)
        return 0
    ledger = ev.Ledger(args.ledger, args.total_usd) if args.real_api else None
    mode = "RÉEL (payant)" if args.real_api else "essai à blanc (faux fournisseur imposé)"
    print(f"Campagne : {mode}", flush=True)
    if ledger is not None:
        print(
            f"Registre : {ledger.committed_usd():.4f} $ déjà engagés sur {args.total_usd:.2f} $ "
            f"({ledger.unsettled()} appel(s) interrompu(s), comptés au pire cas)",
            flush=True,
        )
    status = 0
    incomplete: list[str] = []
    for run, planned, skipped in plan_runs(args, ledger):
        if skipped:
            print(f"== {run.label} : {skipped}", flush=True)
            continue
        cap = None
        if ledger is not None:
            cap, remaining = run_cap(args, ledger, run, planned)
            if cap < worst_call_usd(args, run_model(args, run)):
                print(f"== {run.label} : NON LANCÉE, plafond restant {cap:.4f} $", flush=True)
                incomplete.append(run.label)
                continue
            print(f"== {run.label} : plafond {cap:.4f} $ (reste {remaining:.4f} $)", flush=True)
        else:
            print(f"== {run.label}", flush=True)
        proc = subprocess.run(
            child_command(args, run, cap),
            cwd=ROOT,
            env=child_env(args, run),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        output = KEY.sub("[clé masquée]", proc.stdout + proc.stderr)
        for line in output.splitlines():
            if SUMMARY.search(line):
                print("   " + line, flush=True)
        if "Campagne arrêtée" in output or "Scénarios interrompus" in output:
            incomplete.append(run.label)
        if proc.returncode not in (0, 1):  # 1 : scenarios a examiner ou arret budgetaire
            print(f"   ARRÊT : code de sortie {proc.returncode}", flush=True)
            status = proc.returncode
            break
        if "AuthenticationError" in output:
            print("   ARRÊT : erreur d'authentification", flush=True)
            status = 3
            break
    if incomplete:
        # Equite : une comparaison n'est valable que sur des scenarios termines par tous.
        print(
            "== INCOMPLET : " + ", ".join(incomplete) + ". Comparaison NON équitable tant que "
            "ces exécutions ne sont pas complétées (--only, réserve) ou écartées pour tous.",
            flush=True,
        )
    if ledger is not None:
        for line in summary_lines(ledger):
            print(f"   {line}")
        total = ledger.committed_usd()
        print(f"== TOTAL ENGAGÉ (registre) : {total:.4f} $ sur {args.total_usd:.2f} $")
    return status


if __name__ == "__main__":
    sys.exit(main())
