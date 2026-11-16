"""Etape 0 de la comparaison v2 : scenarios, mesures, orchestrateur, relecture a l'aveugle.

Entierement hors ligne : faux fournisseur, aucune cle, aucun appel.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from neurocoach.agent.llm import FakeLLM
from neurocoach.bootstrap import build_coach_runtime
from neurocoach.config import Settings
from neurocoach.domain.errors import DomainError, ErrorCode

ROOT = Path(__file__).resolve().parents[2]
HISTORIC = [
    "Dialogue de référence",
    "Formulation imprévue",
    "Changement d'avis pendant une proposition",
    "« Oui » écrit au lieu du bouton",
    "Statut implicite",
    "Statut par titre",
    "Référence inexistante",
    "Retard et replanification",
    "Retard et replanification confirmée",
    "Modification ambiguë",
    "Première idée dans un autre domaine",
    "Modification sans précision",
    "Demande de changement vague",
    "Fatigue et plan trop lourd",
    "Modification ambiguë avec échéances",
    "Hors périmètre",
    "Injection",
    "Préférences demandées dans le chat",
    "Demande vague sur un projet actif",
    "Demande vague avec tâche bloquée",
]


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
def runtime(tmp_path, ev):
    rt = build_coach_runtime(Settings(data_dir=tmp_path / "data"), llm=FakeLLM())
    rt.app.coach.ensure_user(ev.USER, "Évaluation")
    yield rt
    rt.checkpointer.conn.close()


# --- scenarios et categories ----------------------------------------------------------------


def test_the_20_historic_scenarios_are_preserved_in_order(ev):
    names = [name for name, _, _ in ev.SCENARIOS]
    assert names[:20] == HISTORIC
    assert len(names) == 36 and len(set(names)) == 36
    assert [n[:3] for n in names[20:]] == [f"N{i:02d}" for i in range(1, 17)]
    assert all("," not in n for n in names)  # --only les separe par des virgules


def test_every_scenario_has_a_category_and_limits_point_to_real_scenarios(ev):
    names = {name for name, _, _ in ev.SCENARIOS}
    assert set(ev.SCENARIO_KINDS) == names
    kinds = [ev.SCENARIO_KINDS[n] for n in names]
    assert kinds.count(ev.KIND_QUALITY) == 24
    assert kinds.count(ev.KIND_SAFETY) == 11
    assert kinds.count(ev.KIND_LIMIT) == 1
    assert set(ev.ARCHITECTURE_LIMITS) <= names


def test_new_scenarios_contain_no_health_data_and_use_vous(ev):
    from neurocoach.agent.guards import uses_tutoiement

    for name, _, steps in ev.SCENARIOS[20:]:
        for step in steps:
            if step[0] == "say":
                assert not ev.MEDICAL.search(step[1]), name
                assert not uses_tutoiement(step[1].replace("s'il te plaît", "")), name


def test_all_36_scenarios_pass_with_the_fake_provider(ev, runtime):
    results = [ev.run_scenario(runtime, *scenario) for scenario in ev.SCENARIOS]
    assert all(r.completed for r in results)
    assert [r.name for r in results if not r.passed] == []


def test_the_memory_scenario_checks_the_whole_conversation(ev, runtime):
    scenario = next(s for s in ev.SCENARIOS if s[0].startswith("N06"))
    result = ev.run_scenario(runtime, *scenario)
    says = [t for t in result.turns if t.step.startswith("say ")]
    assert len(says) >= 8  # tous les messages sont joues et controles
    memory = result.turns[-1]
    assert memory.step == "contrôle de la mémoire"
    assert memory.checks == {"contrainte « paraffine » du début conservée": True}


def test_the_memory_check_fails_when_the_constraint_is_lost(ev, runtime):
    project = runtime.app.coach.create_project(ev.USER, "Sans contrainte", "")
    turn = ev.memory_check(runtime.app, project.id, "paraffine")
    assert turn.checks == {"contrainte « paraffine » du début conservée": False}


def test_new_setups_start_as_announced(ev, runtime):
    for setup in ("plan_stand", "plan_termine"):
        project = runtime.app.coach.create_project(ev.USER, f"Départ {setup}", "")
        ev.prepare(runtime.app, project.id, setup)
        ev.check_start(runtime.app, runtime.agent, project.id, "essai", setup)


@pytest.mark.parametrize(
    ("reply", "origin"),
    [
        ("T1 est maintenant terminée. Vous pouvez annuler ce changement.", "code"),
        ("Quelle tâche avez-vous terminée ?", "code"),
        ("0 tâche terminée sur 3 (0 %).", "code"),
        ("Je propose ce plan :\n\n- Nouvelle tâche T1", "mixte"),
        ("Une période chargée, cela arrive : le plan s'adapte. Une première étape…", "code"),
        ("Commencez par demander l'avis d'une seule personne de confiance.", "modèle"),
        (None, "—"),
    ],
)
def test_reply_origin_separates_code_templates_from_model_text(ev, reply, origin):
    assert ev.reply_origin(reply) == origin


def test_a_code_dominated_scenario_is_marked_as_code(ev, runtime):
    scenario = next(s for s in ev.SCENARIOS if s[0] == "Statut implicite")
    result = ev.run_scenario(runtime, *scenario)
    assert {t.origin for t in result.turns} == {"code"}


# --- mesures et interruptions ---------------------------------------------------------------


def test_turn_metrics_count_calls_latency_and_truncations(ev, tmp_path):
    recorder = ev.RecordingProvider(FakeLLM())
    rt = build_coach_runtime(Settings(data_dir=tmp_path / "d"), llm=recorder)
    rt.app.coach.ensure_user(ev.USER, "Évaluation")
    try:
        scenario = next(s for s in ev.SCENARIOS if s[0] == "Dialogue de référence")
        result = ev.run_scenario(rt, *scenario)
        assert result.calls == len(recorder.calls) and result.calls > 0
        first = result.turns[0]
        # D-79 : un seul appel (reponse, fiche et decision du coach).
        assert first.calls == 1 and len(first.llm_seconds) == 1 and first.turn_seconds >= 0
        recorder.inner.script("coach_turn", DomainError(ErrorCode.LLM_OUTPUT_INVALID))
        project = rt.app.coach.create_project(ev.USER, "Troncature", "")
        turns = ev._play(rt.app, rt.agent, project.id, "x", ("say", "Bonjour"), recorder)
        assert turns[0].errors and turns[0].errors[0].startswith("LLM_OUTPUT_INVALID")
    finally:
        rt.checkpointer.conn.close()


def test_a_budget_stop_marks_the_scenario_interrupted_never_completed(ev, tmp_path):
    budget = ev.Budget(0.002, 0.25, 2.0, 4000, 100)  # moins d'un pire cas : aucun appel
    recorder = ev.RecordingProvider(FakeLLM(), budget)
    rt = build_coach_runtime(Settings(data_dir=tmp_path / "d"), llm=recorder)
    rt.app.coach.ensure_user(ev.USER, "Évaluation")
    try:
        scenario = next(s for s in ev.SCENARIOS if s[0] == "Dialogue de référence")
        with pytest.raises(ev.BudgetStop) as stop:
            ev.run_scenario(rt, *scenario)
        partial = stop.value.partial
        assert not partial.completed and not partial.passed and partial.interrupted
    finally:
        rt.checkpointer.conn.close()


def test_the_json_export_lists_interrupted_and_not_started_scenarios(ev, monkeypatch, tmp_path):
    original = ev.run_scenario
    count = {"n": 0}

    def stop_on_second(runtime, name, setup, steps):
        count["n"] += 1
        if count["n"] == 2:
            partial = ev.ScenarioResult(name, [], ev.SETUPS[setup], interrupted="budget")
            error = ev.BudgetStop("budget : arrêt simulé")
            error.partial = partial
            raise error
        return original(runtime, name, setup, steps)

    monkeypatch.setattr(ev, "run_scenario", stop_on_second)
    ev.main(["--only", "Statut par titre,Injection,Hors périmètre", "--out-dir", str(tmp_path)])
    data = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    states = {s["scenario"]: s["completed"] for s in data["scenarios"]}
    assert list(states.values()).count(False) == 1  # le second est interrompu
    assert len(data["not_started"]) == 1  # le troisieme n'a pas commence
    text = json.dumps(data)
    assert "sk-" not in text and data["config"]["provider"] == "fake"


def test_effort_is_explicit_and_recorded(ev, tmp_path):
    for effort, expected in (("default", None), ("medium", "medium"), ("low", "low")):
        out = tmp_path / effort
        argv = ["--only", "Injection", "--effort", effort, "--pass-id", "3"]
        assert ev.main([*argv, "--out-dir", str(out)]) == 0
        data = json.loads(next(out.glob("*.json")).read_text(encoding="utf-8"))
        assert data["config"]["pass"] == "3"
        assert data["config"]["effort"] == (
            "par défaut du modèle" if expected is None else expected
        )
        assert next((tmp_path / effort).glob("*.md")).name.startswith(
            f"evaluation-coaching-faux-{effort}-p3"
        )


def test_ledger_labels_include_effort_and_pass(ev, tmp_path):
    ledger = ev.Ledger(tmp_path / "r.jsonl", 1.0)
    for pass_id in ("1", "2"):
        label = f"coaching-gpt-5.6-terra-medium-p{pass_id}"
        labels = {"model": "gpt-5.6-terra", "role": "coaching", "campaign": "c"}
        key = ledger.reserve(0.05, label, **labels, effort="medium", pass_id=pass_id)
        ledger.settle(key, 0.01, measured=True)
    other = ledger.reserve(0.05, "coaching-gpt-5.6-terra-low-p1", effort="low", campaign="c")
    ledger.settle(other, 0.02, measured=True)
    assert ledger.committed_for(
        run="coaching-gpt-5.6-terra-medium-p", campaign="c"
    ) == pytest.approx(0.02)
    assert ledger.committed_for(effort="low") == pytest.approx(0.02)
    assert {r["effort"] for r in ledger.summary()} == {"medium", "low"}


# --- orchestrateur --------------------------------------------------------------------------


@pytest.fixture
def campaign():
    return _load("run_campaign")


def test_configs_passes_and_bounds_are_explicit(campaign):
    args = campaign.parse(
        ["--plan", "compare-coaching", "--configs", "gpt-5-mini:default:0.9,gpt-5.6-terra:medium:3",
         "--pass-ids", "1,2"]
    )  # fmt: skip
    runs = campaign.build_plan(args)
    assert [r.label for r in runs] == [
        "coaching-gpt-5-mini-default-p1",
        "coaching-gpt-5.6-terra-medium-p1",
        "coaching-gpt-5-mini-default-p2",
        "coaching-gpt-5.6-terra-medium-p2",
    ]
    assert {r.max_calls for r in runs} == {campaign.upper_bound_calls("coaching", 1)}
    command = campaign.child_command(args, runs[1], None)
    assert command[command.index("--effort") + 1] == "medium"
    assert command[command.index("--pass-id") + 1] == "1"
    assert "--real-api" not in command


def test_repetitions_and_max_calls_can_be_overridden(campaign):
    args = campaign.parse(["--plan", "compare-simple", "--repetitions", "2", "--max-calls", "40"])
    run = campaign.build_plan(args)[0]
    assert run.extra == ("--repetitions", "2") and run.max_calls == 40
    default = campaign.build_plan(campaign.parse(["--plan", "compare-strategy"]))[0]
    assert default.max_calls == 10  # 5 scenarios x 2 essais : borne certaine


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--pass-ids", "1,1"], "identifiants de passage distincts"),
        (["--configs", "gpt-5-mini"], "configuration illisible"),
        (["--max-calls", "0"], "strictement positif"),
    ],
)
def test_invalid_orchestrator_options_are_refused(campaign, argv, message, capsys):
    with pytest.raises(SystemExit) as error:
        campaign.parse(["--plan", "compare-coaching", *argv])
    captured = capsys.readouterr()
    assert message in captured.err + captured.out + str(error.value)


@pytest.mark.parametrize(
    ("configs", "message"),
    [
        ("gpt-5-mini:default:0.9,gpt-5.6-terra:high:9", "supérieure au plafond global"),
        ("gpt-5.6-terra:xhigh", "non pris en charge"),
        ("gpt-9:low", "absent du catalogue"),
    ],
)
def test_real_campaign_configurations_are_validated_before_any_call(
    campaign, monkeypatch, tmp_path, configs, message, capsys
):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    argv = ["--real-api", "--plan", "compare-coaching", "--configs", configs, "--total-usd", "5"]
    with pytest.raises(SystemExit):
        campaign.parse([*argv, "--ledger", str(tmp_path / "r.jsonl")])
    assert message in capsys.readouterr().err
    assert not (tmp_path / "r.jsonl").exists()


def test_the_kill_switch_still_refuses_a_real_campaign(campaign, tmp_path):
    with pytest.raises(SystemExit):  # NEUROCOACH_FORBID_REAL_LLM=1 pose par conftest
        campaign.parse(["--real-api", "--plan", "compare-coaching", "--total-usd", "1",
                        "--ledger", str(tmp_path / "r.jsonl")])  # fmt: skip


def test_a_configuration_cap_covers_all_its_passes(campaign, ev, monkeypatch, tmp_path):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    ledger_path = tmp_path / "r.jsonl"
    args = campaign.parse(
        ["--real-api", "--plan", "compare-coaching", "--configs", "gpt-5.6-terra:medium:3",
         "--pass-ids", "1,2", "--total-usd", "5", "--ledger", str(ledger_path)]
    )  # fmt: skip
    ledger = ev.Ledger(ledger_path, 5)
    key = ledger.reserve(0.1, "coaching-gpt-5.6-terra-medium-p1", campaign=args.campaign)
    ledger.settle(key, 2.4, measured=True)
    run = campaign.build_plan(args)[1]
    cap, remaining = campaign.run_cap(args, ledger, run, 3.0)
    assert cap == pytest.approx(0.6)  # 3,00 $ pour le couple, 2,40 $ deja engages
    assert remaining == pytest.approx(2.6)


def test_legacy_plans_keep_their_labels(campaign):
    runs = campaign.build_plan(campaign.parse(["--plan", "terra-confirmation"]))
    assert [r.label for r in runs] == [
        "coaching-1",
        "coaching-2",
        "coaching-echecs-r0",
        "strategie",
    ]


# --- relecture a l'aveugle ---------------------------------------------------------------


@pytest.fixture
def blind():
    return _load("blind_review")


def _exports(ev, tmp_path, incomplete_for: str | None = None) -> list[Path]:
    files = []
    for model, effort in (("gpt-5-mini", "par défaut du modèle"), ("gpt-5.6-terra", "medium")):
        scenarios = []
        for name in ("N01 Peur du jugement", "N03 Dispersion entre plusieurs idées", "Injection"):
            done = not (incomplete_for == model and name.startswith("N03"))
            scenarios.append(
                {
                    "scenario": name,
                    "kind": ev.SCENARIO_KINDS[name],
                    "completed": done,
                    "turns": [
                        {"step": "say Bonjour", "reply": f"Réponse de {model} pour {name}",
                         "origin": "modèle", "checks": {}, "calls": 2,
                         "llm_seconds": [1.2], "turn_seconds": 2.5}
                    ],
                }
            )  # fmt: skip
        data = {"harness": "coaching", "config": {"campaign": "c", "role": "coaching",
                "model": model, "effort": effort, "pass": "1"}, "scenarios": scenarios}  # fmt: skip
        path = tmp_path / f"{model}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        files.append(path)
    return files


def test_prepare_masks_models_efforts_and_costs(blind, ev, tmp_path):
    out, sealed = tmp_path / "revue", tmp_path / "scelle"
    info = blind.prepare(_exports(ev, tmp_path), out, sealed, seed=1)
    assert info["configurations"] == 2 and info["eligible"] == 3
    for path in out.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for secret in ("gpt-5", "terra", "medium", "par défaut du modèle", "1.2", "2.5"):
                assert secret not in text, (path.name, secret)
    mapping = json.loads((sealed / "correspondance.json").read_text(encoding="utf-8"))
    assert {v["configuration"] for v in mapping.values()} == {
        "gpt-5-mini · effort par défaut du modèle",
        "gpt-5.6-terra · effort medium",
    }
    pairs = list(csv.DictReader((out / "paires.csv").open(encoding="utf-8"), delimiter=";"))
    assert {row["scenario"] for row in pairs} == {
        "N01 Peur du jugement",
        "N03 Dispersion entre plusieurs idées",
    }


def test_scenarios_not_finished_by_every_configuration_are_excluded(blind, ev, tmp_path):
    info = blind.prepare(
        _exports(ev, tmp_path, "gpt-5.6-terra"), tmp_path / "r", tmp_path / "s", seed=1
    )
    assert info["eligible"] == 2 and info["excluded"] == 1
    assert "N03" in (tmp_path / "r" / "exclus.md").read_text(encoding="utf-8")


def _fill(review: Path, winner: str | None, nature: str = "fond", winner_score: str = "3") -> None:
    rows = list(csv.DictReader((review / "grille.csv").open(encoding="utf-8"), delimiter=";"))
    for row in rows:
        for criterion in (
            "comprehension",
            "raisonnement",
            "proactivite",
            "accompagnement",
            "fidelite",
        ):
            row[criterion] = winner_score if row["configuration"] == winner else "2"
        row["securite"] = "0"
    with (review / "grille.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    pairs = list(csv.DictReader((review / "paires.csv").open(encoding="utf-8"), delimiter=";"))
    for row in pairs:
        row["preference"] = "=" if winner is None else ("A" if row["A"] == winner else "B")
        row["nature"] = nature
    with (review / "paires.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(pairs[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(pairs)


def test_reveal_refuses_incomplete_notes_and_altered_mapping(blind, ev, tmp_path):
    out, sealed = tmp_path / "revue", tmp_path / "scelle"
    blind.prepare(_exports(ev, tmp_path), out, sealed, seed=1)
    with pytest.raises(SystemExit, match="Notes incomplètes"):
        blind.reveal(out, sealed)
    _fill(out, "A")
    (sealed / "correspondance.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="modifiée"):
        blind.reveal(out, sealed)


def test_two_scenarios_never_make_a_significant_difference(blind, ev, tmp_path):
    """Meme si A gagne partout : 2 scenarios ne suffisent pas (p = 0,5)."""
    out, sealed = tmp_path / "revue", tmp_path / "scelle"
    blind.prepare(_exports(ev, tmp_path), out, sealed, seed=1)
    _fill(out, "A")
    text = "\n".join(blind.reveal(out, sealed))
    assert "aucune différence significative démontrée" in text
    assert (out / "notes-figees.txt").is_file()


def test_statistics_use_scenarios_as_units_and_correct_thresholds(blind):
    # La regle provisoire « 24/36 » n'etait pas significative (bilateral exact).
    assert blind.binomial_two_sided(24, 36) == pytest.approx(0.0652, abs=1e-4)
    assert blind.minimal_wins(36) == 25 and blind.minimal_wins(20) == 15
    assert blind.minimal_wins(10, 0.05 / 28) is None  # 10 scenarios : impossible avec Holm
    adjusted = blind.holm({"a": 0.01, "b": 0.02, "c": 0.04})
    assert adjusted == {"a": 0.03, "b": 0.04, "c": 0.04}
    rows = [
        {"scenario": "S1", "A": "A", "B": "B", "preference": "A", "nature": "fond"},
        {"scenario": "S1", "A": "A", "B": "B", "preference": "A", "nature": "fond"},  # 2e passage
        {"scenario": "S1", "A": "A", "B": "B", "preference": "B", "nature": "forme"},  # ignore
    ]
    balance = blind.scenario_preferences(rows)
    assert dict(balance[("A", "B")]) == {
        "S1": 2
    }  # un seul scenario, quel que soit le nombre de tours


def test_a_clear_and_consistent_difference_is_detected(blind, tmp_path):
    """22 scenarios, la meme configuration gagne au fond partout : significatif."""
    review = tmp_path / "revue"
    review.mkdir()
    names = [f"S{i:02d}" for i in range(22)]
    with (review / "grille.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(
            ["scenario", "passage", "configuration", *blind.CRITERIA, "securite", "commentaire"]
        )
        for name in names:
            writer.writerow([name, "1", "A", 3, 3, 3, 3, 3, 0, ""])
            writer.writerow([name, "1", "B", 2, 2, 2, 2, 3, 0, ""])
    with (review / "paires.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["scenario", "passage", "A", "B", "preference", "nature", "commentaire"])
        for name in names:
            writer.writerow([name, "1", "A", "B", "A", "fond", ""])
    mapping = {"A": {"configuration": "x"}, "B": {"configuration": "y"}}
    text = "\n".join(blind.analyse(review, mapping))
    assert "différence significative en faveur de A** (comprehension)" in text
    # Les memes preferences, mais de forme : rien de significatif.
    rows = (review / "paires.csv").read_text(encoding="utf-8").replace(";fond;", ";forme;")
    (review / "paires.csv").write_text(rows, encoding="utf-8")
    assert "aucune différence significative démontrée" in "\n".join(blind.analyse(review, mapping))


def test_the_sealed_folder_must_be_separate(blind, ev, tmp_path):
    with pytest.raises(SystemExit):
        inputs = [str(p) for p in _exports(ev, tmp_path)]
        out = str(tmp_path / "r")
        blind.main(["prepare", "--inputs", *inputs, "--out", out, "--sealed", out + "/s"])


# --- estimation du budget -------------------------------------------------------------------


def test_the_budget_estimate_distinguishes_guaranteed_from_probable(capsys):
    estimate = _load("estimate_campaign")
    lines = estimate.estimate(1, 1, 1)
    text = "\n".join(lines)
    assert "au maximum (certain)" in text
    rows = [line for line in lines if line.startswith("| gpt-")]
    assert len(rows) == 8
    assert all(
        "probable (hypothèses)" in row or "garantie" in row or "à risque" in row for row in rows
    )
    terra_high = next(row for row in rows if "terra · high" in row)
    assert "garantie" not in terra_high  # le plafond propose ne garantit pas la completion
