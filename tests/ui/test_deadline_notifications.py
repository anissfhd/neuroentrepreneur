from datetime import UTC, datetime, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

from neurocoach.bootstrap import build_application
from neurocoach.config import Settings
from neurocoach.demo import DEMO_ALICE_ID, seed_demo
from neurocoach.domain.models import TaskStatus, updated
from neurocoach.infra.clock import FixedClock


def test_deadline_reminders_pause_and_resume_persist(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("NEUROCOACH_DATA_DIR", str(data))
    monkeypatch.setenv("NEUROCOACH_LLM_PROVIDER", "fake")
    clock = FixedClock(datetime.now(UTC))
    app = build_application(Settings(data_dir=data), clock=clock)
    seed_demo(app)
    user = DEMO_ALICE_ID
    project = app.coach.list_projects(user)[0]
    tasks = app.coach.get_snapshot(user, project.id).ordered_tasks()
    today = clock.now().date()
    with app.coach._write() as repo:
        for task in tasks:
            repo.update_task(updated(task, due_date=today + timedelta(days=1)))
    assert app.coach.check_deadlines(user) == 0
    app.coach.update_preferences(user, deadlines_enabled=True, display_timezone="UTC")
    expected = sum(task.status is not TaskStatus.DONE for task in tasks)
    assert app.coach.check_deadlines(user) == expected
    assert app.coach.check_deadlines(user) == 0
    assert not app.coach.get_project(user, project.id).paused_at
    clock.advance(timedelta(days=2))
    assert app.coach.check_deadlines(user) == expected
    assert app.coach.check_deadlines(user) == 0
    restarted = build_application(Settings(data_dir=data), clock=clock)
    assert restarted.coach.get_project(user, project.id).paused_at
    assert len(restarted.coach.deadline_notices(user, project.id)) == 2 * expected
    at = AppTest.from_file(Path(__file__).resolve().parents[2] / "ui/app.py", default_timeout=30)
    at.query_params.update({"u": user, "p": "projet", "id": project.id})
    at.run()
    assert not at.exception
    assert sum("Le projet est en pause" in entry.value for entry in at.text) == expected
    assert len([button for button in at.button if (button.key or "").startswith("notice_")]) == (
        2 * expected
    )
    at.query_params.update({"u": user, "p": "taches"})
    with app.coach._write() as repo:
        repo.update_task(updated(tasks[-1], due_date=today))
    at.run()
    assert any(button.key == f"today_{tasks[-1].id}" for button in at.button)
    with app.coach._write() as repo:
        repo.update_task(updated(tasks[-1], due_date=today + timedelta(days=1)))
    action = restarted.actions.request_resume(user, project.id)
    restarted.actions.confirm(user, action.id)
    assert not restarted.coach.get_project(user, project.id).paused_at
    assert restarted.coach.check_deadlines(user) == 0
