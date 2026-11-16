"""Captures d'ecran reelles de l'interface pour docs/screenshots/ (phase 5).

Lance l'interface sur une base de demonstration neuve (donnees fictives, faux fournisseur
LLM), la pilote avec un navigateur Chromium sans fenetre (Edge ou Chrome) par le protocole
DevTools, puis enregistre exactement ce que le navigateur affiche. Aucune image n'est
retouchee ni generee autrement.

Usage : python scripts/capture_screenshots.py [--browser CHEMIN] [--out docs/screenshots]
Prerequis : extras `agent` et `ui` installes (websockets est fourni par streamlit).
"""

from __future__ import annotations

import argparse
import base64
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from websockets.sync.client import ClientConnection, connect

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "screenshots"  # sous data/, donc ignore par Git
APP_PORT = 8599
CDP_PORT = 9339
WIDTH, HEIGHT = 1400, 960
BROWSERS = (
    Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("/usr/bin/chromium"),
    Path("/usr/bin/google-chrome"),
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
)


class DevTools:
    """Client minimal du protocole DevTools (une page, commandes synchrones)."""

    def __init__(self, ws: ClientConnection) -> None:
        self.ws = ws
        self.ids = itertools.count(1)

    def send(self, method: str, **params: Any) -> dict[str, Any]:
        message_id = next(self.ids)
        self.ws.send(json.dumps({"id": message_id, "method": method, "params": params}))
        while True:
            reply = json.loads(self.ws.recv(timeout=60))
            if reply.get("id") == message_id:
                if "error" in reply:
                    raise RuntimeError(f"{method} : {reply['error']}")
                return reply.get("result", {})

    def js(self, expression: str) -> Any:
        result = self.send(
            "Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True
        )
        if "exceptionDetails" in result:
            raise RuntimeError(f"JavaScript : {result['exceptionDetails']}")
        return result["result"].get("value")


def wait_until(check: Callable[[], Any], what: str, timeout: float = 30) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.25)
    raise TimeoutError(f"Delai depasse : {what}")


def http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


class Page:
    def __init__(self, tools: DevTools, out: Path) -> None:
        self.tools = tools
        self.out = out
        self.saved: list[Path] = []

    def idle(self) -> None:
        """Attend la fin de l'execution Streamlit (indicateur « Running » absent et stable)."""
        stable = 0
        deadline = time.monotonic() + 30
        while stable < 4 and time.monotonic() < deadline:
            running = self.tools.js(
                "!!document.querySelector('[data-testid=\"stStatusWidget\"]')"
                " || !document.querySelector('[data-testid=\"stChatInputTextArea\"]')"
            )
            stable = 0 if running else stable + 1
            time.sleep(0.25)
        time.sleep(0.5)  # animations d'apparition

    def has_text(self, text: str) -> bool:
        return bool(self.tools.js(f"document.body.innerText.includes({json.dumps(text)})"))

    def center_of(self, selector: str, text: str, exact: bool = True) -> dict[str, float] | None:
        test = "t === wanted" if exact else "t.includes(wanted)"
        return self.tools.js(
            f"""(() => {{
              const wanted = {json.dumps(text)};
              const el = [...document.querySelectorAll({json.dumps(selector)})]
                .find(e => {{ const t = e.innerText.trim(); return {test}; }});
              if (!el) return null;
              el.scrollIntoView({{block: 'center'}});
              const r = el.getBoundingClientRect();
              return {{x: r.left + r.width / 2, y: r.top + r.height / 2}};
            }})()"""
        )

    def click_at(self, point: dict[str, float]) -> None:
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.tools.send(
                "Input.dispatchMouseEvent",
                type=kind,
                x=point["x"],
                y=point["y"],
                button="left",
                clickCount=1,
            )

    def click(self, text: str, selector: str = "button", exact: bool = True) -> None:
        point = wait_until(lambda: self.center_of(selector, text, exact), f"element « {text} »")
        time.sleep(0.2)  # fin du defilement
        self.click_at(self.center_of(selector, text, exact) or point)
        self.idle()

    def choose(self, label: str, option: str) -> None:
        """Choisit une option d'une liste deroulante Streamlit (identifiee par son libelle)."""
        point = wait_until(
            lambda: self.tools.js(
                f"""(() => {{
                  const box = [...document.querySelectorAll('[data-testid="stSelectbox"]')]
                    .find(b => b.innerText.startsWith({json.dumps(label)}));
                  const target = box && box.querySelector('.react-aria-ComboBox [role="group"]');
                  if (!target) return null;
                  const r = target.getBoundingClientRect();
                  return {{x: r.left + r.width / 2, y: r.top + r.height / 2}};
                }})()"""
            ),
            f"liste « {label} »",
        )
        self.click_at(point)
        self.click(option, selector='[role="option"]')

    def type_into(self, selector: str, text: str) -> None:
        wait_until(
            lambda: self.tools.js(
                f"(() => {{ const e = document.querySelector({json.dumps(selector)});"
                " if (!e) return false; e.focus(); return true; })()"
            ),
            f"champ {selector}",
        )
        self.tools.send("Input.insertText", text=text)

    def press_enter(self) -> None:
        for kind in ("keyDown", "keyUp"):
            self.tools.send(
                "Input.dispatchKeyEvent",
                type=kind,
                key="Enter",
                code="Enter",
                windowsVirtualKeyCode=13,
                text="\r" if kind == "keyDown" else "",
            )

    def send_chat(self, text: str, expect: str | None = None) -> None:
        """Envoie un message, puis attend la reponse du coach (ou un texte attendu)."""
        count = "document.querySelectorAll('[data-testid=\"stChatMessage\"]').length"
        before = self.tools.js(count)
        self.type_into('[data-testid="stChatInputTextArea"]', text)
        self.press_enter()
        if expect:
            wait_until(lambda: self.has_text(expect), f"texte « {expect} »")
        else:
            wait_until(lambda: self.tools.js(count) >= before + 2, "reponse du coach")
        self.idle()

    def scroll_main(self, to: str = "top") -> None:
        position = "0" if to == "top" else "c.scrollHeight"
        container = '[data-testid="stAppScrollToBottomContainer"]'  # zone defilante de Streamlit
        self.tools.js(
            f"(() => {{ const c = document.querySelector({json.dumps(container)})"
            " || document.scrollingElement;"
            f" c.scrollTo(0, {position}); }})()"
        )
        time.sleep(0.4)

    def scroll_to_text(self, text: str, block: str = "start") -> None:
        self.tools.js(
            f"""(() => {{
              const el = [...document.querySelectorAll('h1,h2,h3,p,summary,label')]
                .find(e => e.innerText.trim().startsWith({json.dumps(text)}));
              if (el) el.scrollIntoView({{block: {json.dumps(block)}}});
            }})()"""
        )
        time.sleep(0.4)

    def shot(self, name: str) -> None:
        self.tools.js("document.activeElement && document.activeElement.blur()")
        time.sleep(0.3)
        data = self.tools.send("Page.captureScreenshot", format="png")["data"]
        path = self.out / f"{name}.png"
        path.write_bytes(base64.b64decode(data))
        self.saved.append(path)
        print(f"Capture : {path.relative_to(ROOT)}")


def scenario(page: Page) -> None:
    """Parcours de docs/DEMO_SCRIPT.md, avec les memes phrases (faux fournisseur)."""
    page.tools.send("Page.navigate", url=f"http://127.0.0.1:{APP_PORT}/")
    wait_until(lambda: page.has_text("Où en est le projet"), "chargement de l'interface", 60)
    page.idle()
    page.shot("01_accueil_reprise")

    page.choose("Utilisateur fictif", "Bruno (démo)")
    wait_until(lambda: page.has_text("Atelier de réparation de vélos"), "projet de Bruno")
    page.idle()
    page.send_chat("Je veux ouvrir un atelier de réparation de vélos, par où commencer ?")
    page.scroll_main("bottom")
    page.shot("02_conversation_clarification")

    page.send_chat(
        "Trouver trois premiers clients. J'ai 45 minutes par jour et 50 € de budget.",
        "Proposition en attente de votre accord",
    )
    page.scroll_main("top")
    page.shot("03_plan_propose")

    page.click("Confirmer")
    wait_until(lambda: not page.has_text("Proposition en attente"), "plan confirme")
    page.idle()
    page.scroll_main("bottom")
    page.shot("04_plan_confirme")

    page.click("Plan et tâches", selector='[role="tab"]')
    page.click("Commencer T1")
    page.click("Marquer terminée T1")
    page.click("Signaler un blocage sur T2", selector="label")
    page.type_into('input[aria-label="Raison du blocage (obligatoire)"]', "J'attends du matériel")
    page.click("Enregistrer le blocage de T2")
    page.scroll_to_text("Prochaines actions")
    page.shot("05_taches_et_blocage")

    page.scroll_main("top")
    page.shot("06_progression")

    page.click("Conversation", selector='[role="tab"]')
    page.send_chat("Je n'ai pas avancé cette semaine", "Proposition en attente de votre accord")
    page.scroll_main("bottom")
    page.shot("07_replanification_proposee")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--browser", type=Path, help="Chemin d'Edge, de Chrome ou de Chromium")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "screenshots")
    args = parser.parse_args()
    browser = args.browser or next((path for path in BROWSERS if path.exists()), None)
    if browser is None or not browser.exists():
        print("Aucun navigateur Chromium trouve : utiliser --browser.")
        return 2
    args.out.mkdir(parents=True, exist_ok=True)

    shutil.rmtree(DATA_DIR, ignore_errors=True)
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env.update(
        NEUROCOACH_DATA_DIR=str(DATA_DIR), NEUROCOACH_LLM_PROVIDER="fake", NEUROCOACH_LLM_MODEL=""
    )
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(ROOT / "ui" / "app.py"),
            "--server.headless=true",
            f"--server.port={APP_PORT}",
            "--server.address=127.0.0.1",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    profile = Path(tempfile.mkdtemp(prefix="neurocoach-capture-"))
    chromium = None
    try:
        wait_until(lambda: http_ok(f"http://127.0.0.1:{APP_PORT}/_stcore/health"), "serveur", 60)
        chromium = subprocess.Popen(
            [
                str(browser),
                "--headless=new",
                f"--remote-debugging-port={CDP_PORT}",
                f"--user-data-dir={profile}",
                f"--window-size={WIDTH},{HEIGHT}",
                "--force-device-scale-factor=1",
                "--hide-scrollbars",
                "--no-first-run",
                "--lang=fr-FR",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        targets_url = f"http://127.0.0.1:{CDP_PORT}/json/list"
        target = wait_until(
            lambda: (
                http_ok(targets_url)
                and next(
                    (
                        t
                        for t in json.load(urllib.request.urlopen(targets_url, timeout=2))
                        if t["type"] == "page"
                    ),
                    None,
                )
            ),
            "navigateur",
        )
        with connect(target["webSocketDebuggerUrl"], max_size=None, open_timeout=20) as ws:
            tools = DevTools(ws)
            tools.send(
                "Emulation.setDeviceMetricsOverride",
                width=WIDTH,
                height=HEIGHT,
                deviceScaleFactor=1,
                mobile=False,
            )
            tools.send(
                "Emulation.setEmulatedMedia",
                features=[{"name": "prefers-color-scheme", "value": "light"}],
            )
            scenario(Page(tools, args.out))
    finally:
        for process in (chromium, server):
            if process:
                process.terminate()
                process.wait(timeout=20)
        shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
