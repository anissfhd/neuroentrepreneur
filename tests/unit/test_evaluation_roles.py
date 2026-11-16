"""Etape M4 : harnais d'evaluation par role et comparaisons de modeles, hors ligne.

Aucun appel reel : un « vrai » fournisseur est simule par un faux client, et toute demande de
client reel non simulee fait echouer le test. Cles de test fabriquees a l'execution.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from neurocoach.agent.llm import FakeLLM
from neurocoach.agent.prompts import build_messages
from neurocoach.agent.roles import TASK_ROLES
from neurocoach.agent.schemas import IntentResult
from neurocoach.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ev():
    return _load("evaluate_llm")


@pytest.fixture
def simple():
    return _load("evaluate_simple_tasks")


@pytest.fixture
def strategy():
    return _load("evaluate_strategy_r0")


@pytest.fixture
def campaign():
    return _load("run_campaign")


def _key() -> str:
    return "sk-" + "TESTEVALUATION" * 3


class Spy:
    def __init__(self, simulate_real: bool = False) -> None:
        self.real: list[tuple[str, str]] = []
        self.simulate_real = simulate_real

    def __call__(self, settings, *args, **kwargs):
        if settings.llm_provider == "fake":
            return FakeLLM()
        self.real.append((settings.llm_provider, settings.llm_model))
        if not self.simulate_real:
            raise AssertionError("client reel demande")
        return FakeLLM()


def _spy(module, monkeypatch, **kwargs) -> Spy:
    spy = Spy(**kwargs)
    monkeypatch.setattr(module, "build_llm_provider", spy)
    return spy


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    """.env de l'application : gpt-5-mini actif, et un role coaching sur Terra."""
    env = tmp_path / ".env"
    env.write_text(
        "NEUROCOACH_LLM_PROVIDER=openai\nNEUROCOACH_LLM_MODEL=gpt-5-mini\n"
        "NEUROCOACH_LLM_MODEL_COACHING=gpt-5.6-terra\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NEUROCOACH_LLM_PROVIDER")
    return env


def _parser(ev):
    parser = argparse.ArgumentParser()
    ev.add_safety_arguments(parser)
    return parser


# --- selection explicite du role et du modele -------------------------------------------


def test_a_candidate_is_selected_explicitly_with_catalog_prices(ev, monkeypatch, app_env):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    parser = _parser(ev)
    args = parser.parse_args(
        ["--real-api", "--model", "gpt-5.6-luna", "--budget-usd", "0.05", "--ledger", "r.jsonl"]
    )
    settings = ev.select_settings(
        args, parser, Settings.from_env(), harness_role="simple", roles_allowed=("simple",)
    )
    assert (settings.llm_provider, settings.llm_model) == ("openai", "gpt-5.6-luna")
    assert (args.price_input, args.price_output) == (0.2, 1.2)  # lus dans le catalogue
    assert args.role == "simple"
    # Isolation : le role coaching configure pour l'application n'est pas repris.
    assert all(
        getattr(settings, f"llm_model_{r}") == "" for r in ("coaching", "strategy", "simple")
    )


def test_the_evaluation_never_reads_or_writes_the_active_configuration(
    ev, monkeypatch, app_env, tmp_path
):
    before = app_env.read_bytes()
    spy = _spy(ev, monkeypatch)
    out = tmp_path / "out"
    assert (
        ev.main(["--model", "gpt-5.6-terra", "--only", "Statut par titre", "--out-dir", str(out)])
        == 0
    )
    assert app_env.read_bytes() == before
    assert spy.real == []
    report = next(out.glob("evaluation-coaching-faux-gpt-5.6-terra-*.md")).read_text("utf-8")
    assert "modèle candidat : `gpt-5.6-terra (non appelé)`" in report
    assert "ne mesurent pas la qualité d'un modèle" in report
    assert "La configuration active de l'application n'est ni lue ni modifiée" in report
    assert not list(tmp_path.rglob("neurocoach.sqlite"))  # aucun historique d'application


@pytest.mark.parametrize(
    ("script", "argv", "message"),
    [
        ("evaluate_llm", ["--role", "strategy"], "ce harnais évalue le rôle coaching"),
        ("evaluate_simple_tasks", ["--role", "coaching"], "ce harnais évalue le rôle simple"),
    ],
)
def test_a_harness_refuses_a_role_it_does_not_evaluate(script, argv, message, capsys):
    with pytest.raises(SystemExit):
        _load(script).main(argv)
    assert message in capsys.readouterr().err


# --- configurations invalides : arret avant tout appel -----------------------------------


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--model", "gpt-9"], "modèle candidat inconnu du catalogue : gpt-9"),
        (["--model", "gpt-5.6-terra", "--price-input", "0.2"], "différent du catalogue"),
        ([], "--real-api exige --model"),
    ],
)
def test_invalid_candidates_stop_before_any_call(ev, monkeypatch, app_env, capsys, extra, message):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    spy = _spy(ev, monkeypatch, simulate_real=True)
    argv = ["--real-api", "--budget-usd", "0.1", "--ledger", "r.jsonl", *extra]
    with pytest.raises(SystemExit):
        ev.main(argv)
    assert message in capsys.readouterr().err
    assert spy.real == []
    assert not Path("r.jsonl").exists()


def test_a_retired_or_unsupported_effort_candidate_is_refused(ev, monkeypatch, app_env, capsys):
    import neurocoach.llm_catalog as catalog_module

    body = (
        'catalog_version = "x"\n'
        '[[models]]\nid = "gpt-5-mini"\nprovider = "openai"\nstatus = "available"\n'
        "price_input = 0.25\nprice_output = 2.0\nverified_on = 2026-11-10\n"
        'sources = ["https://example.org/a"]\n'
        '[[models]]\nid = "ancien"\nprovider = "openai"\nstatus = "retired"\n'
        "retirement_date = 2026-01-01\nprice_input = 1.0\nprice_output = 1.0\n"
        'verified_on = 2026-11-10\nsources = ["https://example.org/b"]\n'
        '[[models]]\nid = "sans-effort"\nprovider = "openai"\nstatus = "available"\n'
        'efforts = ["none"]\nprice_input = 1.0\nprice_output = 1.0\n'
        'verified_on = 2026-11-10\nsources = ["https://example.org/c"]\n'
    )
    path = Path("catalogue.toml")
    path.write_text(body, encoding="utf-8")
    custom = catalog_module.load_catalog(path)
    monkeypatch.setattr(ev, "default_catalog", lambda: custom)
    monkeypatch.setattr(catalog_module, "default_catalog", lambda: custom)
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    monkeypatch.setenv("NEUROCOACH_LLM_EFFORT", "low")
    spy = _spy(ev, monkeypatch, simulate_real=True)
    for model, message in (("ancien", "est retiré"), ("sans-effort", "n'est pas accepté")):
        with pytest.raises(SystemExit):
            ev.main(["--real-api", "--model", model, "--budget-usd", "0.1", "--ledger", "r.jsonl"])
        assert message in capsys.readouterr().err
    assert spy.real == []


# --- budgets, verrou et tracabilite des couts ---------------------------------------------


@pytest.mark.parametrize("name", ["evaluate_llm", "evaluate_strategy_r0", "evaluate_simple_tasks"])
def test_the_kill_switch_wins_for_every_harness(name, monkeypatch, app_env, capsys):
    module = _load(name)
    spy = _spy(module, monkeypatch, simulate_real=True)
    argv = ["--real-api", "--model", "gpt-5.6-luna", "--budget-usd", "0.1", "--ledger", "r.jsonl"]
    with pytest.raises(SystemExit):  # NEUROCOACH_FORBID_REAL_LLM=1 pose par conftest
        module.main(argv)
    assert "NEUROCOACH_FORBID_REAL_LLM=1" in capsys.readouterr().err
    assert spy.real == []


def test_costs_are_traced_by_campaign_role_and_model(simple, monkeypatch, app_env, tmp_path):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    monkeypatch.setenv("OPENAI_API_KEY", _key())
    spy = _spy(simple, monkeypatch, simulate_real=True)
    ledger = tmp_path / "registre.jsonl"
    out = tmp_path / "out"
    argv = [
        "--real-api",
        "--model",
        "gpt-5.6-luna",
        "--budget-usd",
        "0.02",
        "--ledger",
        str(ledger),
    ]
    simple.main([*argv, "--campaign", "comparaison-test", "--out-dir", str(out)])
    assert spy.real == [("openai", "gpt-5.6-luna")]
    reserves = [json.loads(line) for line in ledger.read_text().splitlines() if '"reserve"' in line]
    assert reserves and {(r["campaign"], r["role"], r["model"]) for r in reserves} == {
        ("comparaison-test", "simple", "gpt-5.6-luna")
    }
    rows = _load("evaluate_llm").Ledger(ledger, 0.02).summary()
    assert len(rows) == 1 and rows[0]["model"] == "gpt-5.6-luna" and rows[0]["usd"] <= 0.02
    # Aucun secret dans le compte rendu ni dans le registre.
    for text in (next(out.glob("simple-gpt-5.6-luna-*.md")).read_text("utf-8"), ledger.read_text()):
        assert _key() not in text and "sk-" not in text


def test_the_ledger_summary_separates_models_and_roles(ev, tmp_path):
    ledger = ev.Ledger(tmp_path / "r.jsonl", 1.0)
    calls = [
        ("gpt-5-mini", "coaching", 0.01),
        ("gpt-5.6-terra", "coaching", 0.04),
        ("gpt-5.6-terra", "strategy", 0.02),
        ("gpt-5-mini", "coaching", 0.01),
    ]
    for model, role, cost in calls:
        key = ledger.reserve(0.05, "r", model=model, role=role, campaign="c")
        ledger.settle(key, cost, measured=True)
    ledger.reserve(0.05, "r", model="gpt-5.6-luna", role="simple", campaign="c")  # interrompu
    summary = {(r["role"], r["model"]): (r["calls"], round(r["usd"], 4)) for r in ledger.summary()}
    assert summary == {
        ("coaching", "gpt-5-mini"): (2, 0.02),
        ("coaching", "gpt-5.6-terra"): (1, 0.04),
        ("strategy", "gpt-5.6-terra"): (1, 0.02),
        ("simple", "gpt-5.6-luna"): (1, 0.05),  # pire cas
    }


def test_historic_ledgers_without_labels_are_still_summarised(ev, tmp_path):
    path = tmp_path / "ancien.jsonl"
    path.write_text(
        '{"event": "reserve", "id": "a", "run": "x", "worst_usd": 0.05}\n'
        '{"event": "settle", "id": "a", "cost_usd": 0.01, "measured": true}\n',
        encoding="utf-8",
    )
    assert ev.Ledger(path, 1.0).summary() == [
        {"campaign": "", "role": "", "model": "", "effort": "", "calls": 1, "usd": 0.01}
    ]


# --- comparaisons equitables (orchestrateur) -----------------------------------------------


@pytest.mark.parametrize(
    ("plan", "role", "script"),
    [
        ("compare-coaching", "coaching", "evaluate_llm.py"),
        ("compare-strategy", "strategy", "evaluate_strategy_r0.py"),
        ("compare-simple", "simple", "evaluate_simple_tasks.py"),
    ],
)
def test_comparisons_use_the_same_scenarios_and_parameters_for_each_model(
    campaign, monkeypatch, tmp_path, plan, role, script
):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    ledger = tmp_path / "r.jsonl"
    args = campaign.parse(
        ["--real-api", "--plan", plan, "--total-usd", "0.6", "--ledger", str(ledger)]
    )
    runs = campaign.plan_runs(args, _load("evaluate_llm").Ledger(ledger, 0.6))
    assert [run.model for run, _, _ in runs] == ["gpt-5-mini", "gpt-5.6-terra", "gpt-5.6-luna"]
    assert {cap for _, cap, _ in runs} == {0.2}  # meme part pour chaque modele
    commands = [campaign.child_command(args, run, cap) for run, cap, _ in runs]
    stripped = []
    for command, (run, _, _) in zip(commands, runs, strict=True):
        assert command[1].endswith(script)
        assert command[command.index("--role") + 1] == role
        assert command[command.index("--model") + 1] == run.model
        assert command[command.index("--campaign") + 1] == "r"
        env = campaign.child_env(args, run)
        assert command[command.index("--effort") + 1] == "low"  # explicite (etape 0)
        assert env["NEUROCOACH_LLM_MAX_RETRIES"] == "0"
        assert env["NEUROCOACH_LLM_PROVIDER"] == "openai"
        rest = [a for a in command if a not in (run.model, run.label)]
        drop = {"--price-input", "--price-output"}
        stripped.append([a for i, a in enumerate(rest) if i == 0 or rest[i - 1] not in drop])
    assert stripped[0] == stripped[1] == stripped[2]  # seuls modele et tarifs different


def test_catalog_prices_differ_per_model_in_the_worst_case(campaign, monkeypatch, tmp_path):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    args = campaign.parse(
        [
            "--real-api",
            "--plan",
            "compare-simple",
            "--total-usd",
            "0.3",
            "--ledger",
            str(tmp_path / "r"),
        ]
    )
    assert campaign.worst_call_usd(args, "gpt-5-mini") == pytest.approx(
        (6000 * 0.25 + 4000 * 2) / 1e6
    )
    assert campaign.worst_call_usd(args, "gpt-5.6-terra") == pytest.approx(
        (6000 * 2 + 4000 * 12) / 1e6
    )


def test_an_invalid_model_stops_the_campaign_before_any_call(
    campaign, monkeypatch, tmp_path, capsys
):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    argv = ["--real-api", "--plan", "compare-coaching", "--models", "gpt-5-mini,gpt-9"]
    with pytest.raises(SystemExit):
        campaign.parse([*argv, "--total-usd", "0.3", "--ledger", str(tmp_path / "r.jsonl")])
    assert "coaching-gpt-9-low-p1 : modèle gpt-9 absent du catalogue" in capsys.readouterr().err


def test_legacy_real_plans_now_require_an_explicit_model(campaign, monkeypatch, tmp_path):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    with pytest.raises(SystemExit):
        campaign.parse(
            ["--real-api", "--plan", "d61", "--total-usd", "0.1", "--ledger", str(tmp_path / "r")]
        )


def test_summary_reads_the_ledger_without_any_call(campaign, ev, tmp_path, capsys):
    ledger = tmp_path / "r.jsonl"
    registry = ev.Ledger(ledger, 1.0)
    registry.settle(
        registry.reserve(0.05, "x", model="gpt-5-mini", role="coaching", campaign="c"),
        0.012,
        measured=True,
    )
    assert campaign.main(["--summary", "--ledger", str(ledger)]) == 0
    out = capsys.readouterr().out
    assert "c · coaching · gpt-5-mini · — : 1 appel(s), 0.0120 $" in out
    assert "Total engagé : 0.0120 $" in out


def test_a_dry_run_comparison_of_three_models_makes_no_real_call(tmp_path):
    """Sous-processus, avec le vrai .env du depot : tout reste factice."""
    import os
    import subprocess

    env = {k: v for k, v in os.environ.items() if not k.startswith("NEUROCOACH_")}
    env.update(PYTHONIOENCODING="utf-8", OPENAI_BASE_URL="http://127.0.0.1:9")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_campaign.py"), "--plan", "compare-simple",
         "--out-dir", str(tmp_path)],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stdout + proc.stderr
    reports = sorted(p.name for p in tmp_path.glob("simple-*.md"))
    assert [name.split("-2026")[0] for name in reports] == [
        "simple-faux-gpt-5-mini-low-p1",
        "simple-faux-gpt-5.6-luna-low-p1",
        "simple-faux-gpt-5.6-terra-low-p1",
    ]
    for report in tmp_path.glob("*.md"):
        assert "ne mesurent pas la qualité d'un modèle" in report.read_text("utf-8")


# --- harnais des taches simples ------------------------------------------------------------


def test_simple_tasks_reference_answers_pass_and_defects_are_caught(simple):
    items = simple.cases()
    assert {item["kind"] for item in items} == {"classification", "extraction", "format"}
    for item in items:
        assert all(simple.grade(item, simple.fake_answer(item)).values()), item["name"]
        assert TASK_ROLES[item["task"]] == "simple"
    vague = next(i for i in items if i["kind"] == "extraction" and i["expected"]["name"] is None)
    invented = simple.Extraction(name="Savons du Centre", price_eur=6.0, city=None)
    assert not simple.grade(vague, invented)["rien d'inventé"]
    listing = next(i for i in items if i["kind"] == "format")
    long = simple.TitleList(titles=["x" * 70, "Tester.", "Ok"])
    checks = simple.grade(listing, long)
    assert not checks["60 caractères au plus"] and not checks["sans point final"]
    wrong = next(i for i in items if i["kind"] == "classification")
    assert not simple.grade(wrong, IntentResult(intent="aide"))["intention attendue"]


def test_simple_classification_reuses_the_application_prompt_unchanged(simple):
    item = next(i for i in simple.cases() if i["kind"] == "classification")
    text = simple.CLASSIFY[0][0]
    assert item["messages"] == build_messages("classify_intent", text=text, facts=simple.FACTS)


def test_simple_sources_are_fictitious(simple):
    for source, _ in simple.EXTRACT:
        assert ".example" in source


# --- compatibilite avec les anciens usages ------------------------------------------------


@pytest.mark.parametrize(
    ("name", "argv"),
    [
        ("evaluate_llm", ["--only", "Statut par titre"]),
        ("evaluate_llm", ["--allow-fake", "--only", "Statut par titre"]),
        ("evaluate_strategy_r0", ["--repetitions", "1"]),
        ("evaluate_simple_tasks", []),
    ],
)
def test_former_dry_run_invocations_still_work(name, argv, monkeypatch, tmp_path):
    module = _load(name)
    _spy(module, monkeypatch)
    assert module.main([*argv, "--out-dir", str(tmp_path)]) == 0
