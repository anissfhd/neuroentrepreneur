"""Aucun appel reel sans demande explicite, plafond verifie avant chaque appel, registre partage.

Suite a l'incident du 10 novembre 2026 : un essai a blanc a utilise le fournisseur de .env
(openai) sans plafond. Tout est verifie ici SANS reseau : un fournisseur « reel » est simule
par un faux client, et toute construction d'un vrai client fait echouer le test.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from neurocoach.agent.llm import FakeLLM, build_llm_provider
from neurocoach.config import ConfigurationError, Settings
from neurocoach.domain.errors import DomainError, ErrorCode

ROOT = Path(__file__).resolve().parents[2]
PRICES = ["--price-input", "2", "--price-output", "12"]  # tarifs de gpt-5.6-terra
WORST_OUT = 4000 * 12 / 1e6  # 0,048 $ : sortie maximale d'un appel


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
def strategy():
    return _load("evaluate_strategy_r0")


@pytest.fixture
def dotenv_openai(tmp_path, monkeypatch):
    """Un .env configure sur OpenAI, comme celui du porteur du projet (sans cle)."""
    (tmp_path / ".env").write_text(
        "NEUROCOACH_LLM_PROVIDER=openai\nNEUROCOACH_LLM_MODEL=gpt-5-mini\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NEUROCOACH_LLM_PROVIDER")  # le .env doit pouvoir s'appliquer
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    assert Settings.from_env().llm_provider == "openai"
    return tmp_path


class Spy:
    """Remplace build_llm_provider : compte les clients reels demandes, n'en construit aucun."""

    def __init__(self, simulate_real: bool = False, inner=None) -> None:
        self.real_requests = 0
        self.simulate_real = simulate_real
        self.inner = inner

    def __call__(self, settings, *args, **kwargs):
        if settings.llm_provider == "fake":
            return FakeLLM()
        self.real_requests += 1
        if not self.simulate_real:
            raise AssertionError("un vrai client a ete demande")
        return self.inner or FakeLLM()  # « vrai » fournisseur simule : aucun reseau


def _spy(module, monkeypatch, **kwargs) -> Spy:
    spy = Spy(**kwargs)
    monkeypatch.setattr(module, "build_llm_provider", spy)
    return spy


class Inner:
    def __init__(self, error: BaseException | None = None) -> None:
        self.calls = 0
        self.error = error

    def generate_text(self, task, messages):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return "ok"


MESSAGES = [{"role": "user", "content": "x" * 200}]


def _budget(ev, limit, ledger=None, cap=None, label="essai"):
    return ev.Budget(
        limit,
        2.0,
        12.0,
        4000,
        100,
        ledger=ev.Ledger(ledger, cap or limit) if ledger else None,
        run_label=label,
    )


# --- 1. lancement sans option reelle ---------------------------------------------------------


def test_without_real_option_the_fake_provider_is_imposed(ev, monkeypatch, tmp_path):
    spy = _spy(ev, monkeypatch)
    out = tmp_path / "out"
    assert ev.main(["--only", "Statut par titre", "--out-dir", str(out)]) == 0
    assert spy.real_requests == 0
    assert "Fournisseur : `fake`" in next(out.glob("evaluation-*.md")).read_text(encoding="utf-8")


# --- 2. .env configure sur OpenAI ------------------------------------------------------------


def test_dotenv_on_openai_never_triggers_a_real_call_in_a_dry_run(ev, dotenv_openai, monkeypatch):
    spy = _spy(ev, monkeypatch)
    out = dotenv_openai / "out"
    assert ev.main(["--only", "Statut par titre", "--out-dir", str(out)]) == 0
    assert spy.real_requests == 0


def test_dotenv_on_openai_strategy_dry_run_is_fake_too(strategy, dotenv_openai, monkeypatch):
    spy = _spy(strategy, monkeypatch)
    assert strategy.main(["--repetitions", "1", "--out-dir", str(dotenv_openai / "out")]) == 0
    assert spy.real_requests == 0


def test_the_obsolete_allow_fake_option_is_still_a_dry_run(ev, dotenv_openai, monkeypatch):
    spy = _spy(ev, monkeypatch)
    out = dotenv_openai / "out"
    assert ev.main(["--allow-fake", "--only", "Statut par titre", "--out-dir", str(out)]) == 0
    assert spy.real_requests == 0


def test_a_dry_run_forbids_real_clients_for_the_whole_process(ev, dotenv_openai, monkeypatch):
    ev.main(["--only", "Statut par titre", "--out-dir", str(dotenv_openai / "out")])
    with pytest.raises(ConfigurationError, match="interdits"):
        build_llm_provider(Settings(llm_provider="openai", llm_model="gpt-5-mini"))


def test_the_application_kill_switch_blocks_every_real_provider(monkeypatch):
    monkeypatch.setenv("NEUROCOACH_FORBID_REAL_LLM", "1")
    for provider in ("openai", "anthropic"):
        with pytest.raises(ConfigurationError, match="interdits"):
            build_llm_provider(Settings(llm_provider=provider, llm_model="modele"))


# --- 3. lancement reel sans budget -----------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["--real-api"],
        ["--real-api", *PRICES, "--ledger", "registre.jsonl"],  # sans plafond
        ["--real-api", "--budget-usd", "0.2", "--ledger", "registre.jsonl"],  # sans tarifs
        ["--real-api", "--budget-usd", "0.2", *PRICES],  # sans registre
        ["--real-api", "--budget-usd", "0", *PRICES, "--ledger", "registre.jsonl"],
    ],
)
def test_a_real_run_without_full_budget_is_refused(ev, strategy, dotenv_openai, monkeypatch, argv):
    for module in (ev, strategy):
        spy = _spy(module, monkeypatch)
        with pytest.raises(SystemExit):
            module.main(argv)
        assert spy.real_requests == 0
    assert not (dotenv_openai / "registre.jsonl").exists()


def test_real_api_without_an_explicit_model_is_refused(ev, monkeypatch):
    """M4 : le fournisseur vient du catalogue du candidat ; sans --model, rien n'est lance."""
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    with pytest.raises(SystemExit):
        ev.main(["--real-api", "--budget-usd", "0.2", *PRICES, "--ledger", "r.jsonl"])


def test_real_api_is_refused_where_real_calls_are_forbidden(ev, dotenv_openai, monkeypatch):
    monkeypatch.setenv("NEUROCOACH_FORBID_REAL_LLM", "1")
    spy = _spy(ev, monkeypatch, simulate_real=True)
    with pytest.raises(SystemExit):
        ev.main(["--real-api", "--budget-usd", "0.2", *PRICES, "--ledger", "r.jsonl"])
    assert spy.real_requests == 0


# --- 4. budget insuffisant avant un appel ----------------------------------------------------


def test_insufficient_run_budget_stops_before_the_call(ev):
    inner = Inner()
    recorder = ev.RecordingProvider(inner, _budget(ev, WORST_OUT / 2))
    with pytest.raises(ev.BudgetStop):
        recorder.generate_text("t", MESSAGES)
    assert inner.calls == 0


def test_insufficient_campaign_budget_stops_before_the_call(ev, tmp_path):
    ledger = tmp_path / "registre.jsonl"
    earlier = ev.Ledger(ledger, 0.10)
    earlier.settle(earlier.reserve(0.06, "execution-1"), 0.06, measured=True)
    inner = Inner()
    # Le plafond de l'execution suffirait (0,50 $) ; celui de la campagne (0,10 $) non.
    recorder = ev.RecordingProvider(inner, _budget(ev, 0.50, ledger, cap=0.10))
    with pytest.raises(ev.BudgetStop, match="plafond de campagne"):
        recorder.generate_text("t", MESSAGES)
    assert inner.calls == 0
    assert ev.Ledger(ledger, 0.10).committed_usd() == pytest.approx(0.06)


# --- 5. arret apres epuisement du budget -----------------------------------------------------


def test_a_simulated_real_run_stops_when_the_budget_is_exhausted(ev, dotenv_openai, monkeypatch):
    """Le faux client ne releve aucun jeton : chaque appel est compte au pire cas (≈0,05 $)."""
    spy = _spy(ev, monkeypatch, simulate_real=True)
    ledger = dotenv_openai / "registre.jsonl"
    out = dotenv_openai / "out"
    argv = ["--real-api", "--model", "gpt-5.6-terra", "--budget-usd", "0.12", *PRICES]
    code = ev.main([*argv, "--ledger", str(ledger), "--run-label", "essai", "--out-dir", str(out)])
    assert code == 1
    assert spy.real_requests == 1
    report = next(out.glob("evaluation-*.md")).read_text(encoding="utf-8")
    assert "Campagne : arrêtée" in report
    registry = ev.Ledger(ledger, 0.12)
    assert 0 < registry.committed_usd() <= 0.12
    assert registry.unsettled() == 0
    assert registry.runs() == {"essai": "stopped"}


def test_a_simulated_real_strategy_run_stops_too(strategy, dotenv_openai, monkeypatch):
    _spy(strategy, monkeypatch, simulate_real=True)
    ledger = dotenv_openai / "registre.jsonl"
    argv = ["--real-api", "--model", "gpt-5.6-terra", "--budget-usd", "0.07", *PRICES]
    strategy.main([*argv, "--ledger", str(ledger), "--out-dir", str(dotenv_openai / "out")])
    registry = _load("evaluate_llm").Ledger(ledger, 0.07)
    assert registry.committed_usd() <= 0.07
    assert len([1 for line in ledger.read_text().splitlines() if '"reserve"' in line]) == 1


# --- 6. interruption ou erreur reseau --------------------------------------------------------


def test_a_network_error_is_charged_at_worst_case_without_retry(ev, tmp_path):
    ledger = tmp_path / "registre.jsonl"
    timeout = DomainError(ErrorCode.LLM_UNAVAILABLE)
    timeout.__cause__ = TimeoutError()
    inner = Inner(error=timeout)
    budget = _budget(ev, 0.50, ledger)
    recorder = ev.RecordingProvider(inner, budget)
    with pytest.raises(DomainError):
        recorder.generate_text("t", MESSAGES)
    assert inner.calls == 1  # aucune nouvelle tentative
    assert budget.worst_case_charges == 1
    registry = ev.Ledger(ledger, 0.50)
    assert registry.unsettled() == 0
    assert registry.committed_usd() == pytest.approx(budget.spent_usd) and budget.spent_usd > 0


def test_an_unexpected_client_error_is_charged_at_worst_case(ev, tmp_path):
    budget = _budget(ev, 0.50, tmp_path / "registre.jsonl")
    recorder = ev.RecordingProvider(Inner(error=ConnectionResetError()), budget)
    with pytest.raises(ConnectionResetError):
        recorder.generate_text("t", MESSAGES)
    assert budget.worst_case_charges == 1


def test_an_interruption_mid_call_stays_at_worst_case_after_resume(ev, tmp_path):
    ledger = tmp_path / "registre.jsonl"
    # Plafond de 0,09 $ : un appel au pire cas (≈0,048 $) tient, deux non.
    budget = _budget(ev, 0.50, ledger, cap=0.09)
    recorder = ev.RecordingProvider(Inner(error=KeyboardInterrupt()), budget)
    with pytest.raises(KeyboardInterrupt):
        recorder.generate_text("t", MESSAGES)
    resumed = ev.Ledger(ledger, 0.09)
    assert resumed.unsettled() == 1
    worst = resumed.committed_usd()
    assert worst >= WORST_OUT
    # Reprise : l'appel interrompu est deduit du plafond total.
    inner = Inner()
    again = ev.RecordingProvider(inner, _budget(ev, 0.50, ledger, cap=0.09))
    with pytest.raises(ev.BudgetStop):
        again.generate_text("t", MESSAGES)
    assert inner.calls == 0


def test_a_truncated_last_line_is_ignored_but_corruption_is_refused(ev, tmp_path):
    ledger = tmp_path / "registre.jsonl"
    registry = ev.Ledger(ledger, 1.0)
    key = registry.reserve(0.05, "r")
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write('{"event": "settle", "id": "' + key[:6])  # arret brutal pendant l'ecriture
    assert registry.committed_usd() == pytest.approx(0.05)  # reste au pire cas
    ledger.write_text("pas du json\n" + json.dumps({"event": "run"}) + "\n", encoding="utf-8")
    with pytest.raises(ev.LedgerError):
        registry.committed_usd()


# --- budget partage par toutes les executions ------------------------------------------------


def test_the_ledger_is_shared_by_successive_runs(ev, tmp_path):
    ledger = tmp_path / "registre.jsonl"
    first = _budget(ev, 0.40, ledger, cap=0.12, label="execution-1")
    ev.RecordingProvider(Inner(), first).generate_text("t", MESSAGES)  # pire cas : ≈0,05 $
    second = _budget(ev, 0.40, ledger, cap=0.12, label="execution-2")
    recorder = ev.RecordingProvider(Inner(), second)
    recorder.generate_text("t", MESSAGES)
    with pytest.raises(ev.BudgetStop):
        recorder.generate_text("t", MESSAGES)
    assert ev.Ledger(ledger, 0.12).committed_usd() <= 0.12


# --- orchestrateur ---------------------------------------------------------------------------


@pytest.fixture
def campaign():
    return _load("run_campaign")


def test_campaign_dry_run_commands_are_fake(campaign):
    args = campaign.parse([])
    env = campaign.child_env(args)
    assert env["NEUROCOACH_LLM_PROVIDER"] == "fake"
    assert env["NEUROCOACH_FORBID_REAL_LLM"] == "1"
    for run, cap, _ in campaign.plan_runs(args, None):
        command = campaign.child_command(args, run, cap)
        assert "--real-api" not in command and "--budget-usd" not in command


@pytest.mark.parametrize(
    "argv",
    [
        ["--real-api"],
        ["--real-api", *PRICES, "--ledger", "r.jsonl"],
        ["--real-api", "--total-usd", "0.7", "--ledger", "r.jsonl"],
        ["--real-api", "--total-usd", "0.7", *PRICES],
        ["--real-api", "--total-usd", "0", *PRICES, "--ledger", "r.jsonl"],
    ],
)
def test_campaign_real_mode_requires_cap_prices_and_ledger(campaign, monkeypatch, argv):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    with pytest.raises(SystemExit):
        campaign.parse(argv)


def test_campaign_real_commands_share_one_ledger_and_cap(campaign, monkeypatch, tmp_path):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    ledger = tmp_path / "registre.jsonl"
    args = campaign.parse(
        [
            "--real-api",
            "--model",
            "gpt-5.6-terra",
            "--total-usd",
            "0.7",
            *PRICES,
            "--ledger",
            str(ledger),
        ]
    )
    env = campaign.child_env(args)
    assert "NEUROCOACH_FORBID_REAL_LLM" not in env
    assert env["NEUROCOACH_LLM_MAX_RETRIES"] == "0"
    for run, cap, _ in campaign.plan_runs(args, _load("evaluate_llm").Ledger(ledger, 0.7)):
        command = campaign.child_command(args, run, cap)
        assert command[command.index("--ledger") + 1] == str(ledger)
        assert command[command.index("--campaign-cap-usd") + 1] == "0.7"
        assert float(command[command.index("--budget-usd") + 1]) <= 0.7


def test_campaign_resume_skips_done_runs_and_requires_an_existing_ledger(
    campaign, monkeypatch, tmp_path
):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    ledger = tmp_path / "registre.jsonl"
    base = ["--real-api", "--model", "gpt-5.6-terra", "--total-usd", "0.7", *PRICES]
    base += ["--ledger", str(ledger)]
    with pytest.raises(SystemExit):
        campaign.parse([*base, "--resume"])  # rien a reprendre
    registry = _load("evaluate_llm").Ledger(ledger, 0.7)
    registry.settle(registry.reserve(0.2, "coaching-1"), 0.2, measured=True)
    registry.mark_run("coaching-1", "done")
    with pytest.raises(SystemExit):
        campaign.parse(base)  # registre deja utilise sans --resume
    args = campaign.parse([*base, "--resume"])
    skipped = {run.label for run, _, why in campaign.plan_runs(args, registry) if why}
    assert skipped == {"coaching-1"}
    assert registry.committed_usd() == pytest.approx(0.2)  # depense deduite a la reprise


def test_campaign_dry_run_end_to_end_makes_no_real_call(tmp_path):
    """Lance l'orchestrateur et ses executions dans des processus separes, comme en vrai."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("NEUROCOACH_")}
    # Filet supplementaire pour ce test : un client cree par erreur viserait un port local ferme.
    env.update(
        PYTHONIOENCODING="utf-8",
        OPENAI_BASE_URL="http://127.0.0.1:9",
        OPENAI_API_BASE="http://127.0.0.1:9",
        ANTHROPIC_BASE_URL="http://127.0.0.1:9",
    )
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_campaign.py"), "--out-dir", str(tmp_path)],
        cwd=ROOT,  # le vrai .env du depot est lu : il ne doit rien declencher
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "essai à blanc (faux fournisseur imposé)" in proc.stdout
    assert proc.stdout.count("Essai à blanc : faux fournisseur imposé") == 4
    reports = list(tmp_path.glob("*.md"))
    assert len(reports) == 4
    for report in reports:
        text = report.read_text(encoding="utf-8")
        assert "Fournisseur : `fake`" in text or "— faux —" in text
    assert not list(tmp_path.glob("*.jsonl"))


def test_campaign_output_cap_is_passed_to_every_real_run(campaign, monkeypatch, tmp_path):
    """Le plafond de sortie fixe le pire cas reserve par les executions (D-61, 0,10 $)."""
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    ledger = tmp_path / "registre.jsonl"
    base = ["--real-api", "--model", "gpt-5.6-terra", "--total-usd", "0.1", *PRICES]
    base += ["--ledger", str(ledger), "--plan", "d61"]
    args = campaign.parse([*base, "--max-output-tokens", "2000"])
    assert campaign.child_env(args)["NEUROCOACH_LLM_MAX_OUTPUT_TOKENS"] == "2000"
    assert campaign.worst_call_usd(args) == pytest.approx(0.036)
    runs = campaign.plan_runs(args, _load("evaluate_llm").Ledger(ledger, 0.1))
    assert [run.label for run, _, _ in runs] == ["d61-coaching"]
    with pytest.raises(SystemExit):
        campaign.parse([*base, "--max-output-tokens", "10"])
