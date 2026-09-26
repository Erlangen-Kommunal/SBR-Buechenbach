#!/usr/bin/env python3
"""Manuelles Update der SBR-Büchenbach Daten.

Kann direkt aus der Konsole, per VS Code / Antigravity Task oder per PowerShell
aufgerufen werden.

Verwendung:
  python tools/manual_sync.py [OPTIONEN]

Optionen:
  --all             Führt alle Sync-Schritte lokal nacheinander aus (Standard)
  --ratsinfo        Lädt nur neue Beiratsdokumente von ratsinfo.erlangen.de
  --geo             Aktualisiert nur Geodaten (Beiratsgrenzen & Straßen)
  --gremien         Aktualisiert nur Tagesordnungen der Nachbargremien
  --rebuild-db      Baut nur die DuckDB graph.db neu (GraphBuilder)
  --no-text         Beim DB-Bau keine PDF-Volltexte extrahieren (sehr schnell)
  --trigger-github  Startet den GitHub Actions Sync-Workflow per GitHub CLI
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Sicherstellen, dass auf Windows UTF-8 sauber ausgegeben werden kann
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_step(name: str, cmd: list[str], cwd: Path | None = None) -> bool:
    print(f"\n{'='*60}")
    print(f">> {name}")
    print(f"   Befehl: {' '.join(cmd)}")
    print(f"   Ordner: {cwd or REPO_ROOT}")
    print(f"{'='*60}")
    t0 = time.time()
    try:
        res = subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), check=False)
        dur = time.time() - t0
        if res.returncode == 0:
            print(f"[OK] {name} erfolgreich abgeschlossen ({dur:.1f}s).")
            return True
        else:
            print(f"[FEHLER] {name} fehlgeschlagen mit Exit-Code {res.returncode} ({dur:.1f}s).")
            return False
    except Exception as e:
        print(f"[FEHLER] Fehler beim Ausfuehren von {name}: {e}")
        return False


def sync_ratsinfo() -> bool:
    sbr_dir = REPO_ROOT / "SBR"
    script = sbr_dir / "uvp_agent.py"
    if not script.is_file():
        print(f"Fehler: {script} nicht gefunden.")
        return False
    return run_step("Ratsinfo Dokumente synchronisieren", [sys.executable, str(script), "--sync"], cwd=sbr_dir)


def sync_geo() -> bool:
    script = REPO_ROOT / "tools" / "fetch_geodata.py"
    if not script.is_file():
        print(f"Fehler: {script} nicht gefunden.")
        return False
    return run_step("Geodaten aktualisieren (Beiratsgrenzen & Strassen)", [sys.executable, str(script)])


def sync_gremien() -> bool:
    script = REPO_ROOT / "tools" / "fetch_gremien_tops.py"
    if not script.is_file():
        print(f"Fehler: {script} nicht gefunden.")
        return False
    return run_step("Tagesordnungen der Nachbargremien aktualisieren", [sys.executable, str(script)])


def rebuild_db(no_text: bool = False) -> bool:
    cmd = ["dotnet", "run", "--project", "GraphBuilder", "--", str(REPO_ROOT), "--db", "graph.db"]
    if no_text:
        cmd.append("--no-text")
    return run_step("Datenbank graph.db neu erstellen", cmd)


def trigger_github() -> bool:
    gh_path = shutil.which("gh")
    if not gh_path:
        print("[FEHLER] GitHub CLI ('gh') ist nicht installiert oder nicht im PATH.")
        print("  Installation: winget install GitHub.cli")
        return False
    return run_step("GitHub Actions Workflow 'Weekly Sync (Ratsinfo)' anstossen", ["gh", "workflow", "run", "sync.yml"])


def main() -> int:
    ap = argparse.ArgumentParser(description="Manuelles Update der SBR Buechenbach Daten")
    ap.add_argument("--all", action="store_true", help="Alle Schritte nacheinander ausfuehren")
    ap.add_argument("--ratsinfo", action="store_true", help="Nur Beiratsdokumente von ratsinfo.erlangen.de abrufen")
    ap.add_argument("--geo", action="store_true", help="Nur Geodaten & Strassen aktualisieren")
    ap.add_argument("--gremien", action="store_true", help="Nur Tagesordnungen der Nachbargremien abrufen")
    ap.add_argument("--rebuild-db", action="store_true", help="Nur graph.db neu erstellen")
    ap.add_argument("--no-text", action="store_true", help="Ohne Volltext-Extraktion beim DB-Bau")
    ap.add_argument("--trigger-github", action="store_true", help="GitHub Actions Sync-Workflow starten")
    args = ap.parse_args()

    explicit = any([args.ratsinfo, args.geo, args.gremien, args.rebuild_db, args.trigger_github])
    do_all = args.all or not explicit

    success = True
    print("+----------------------------------------------------------+")
    print("|   SBR Buechenbach -- Manuelle Datenaktualisierung        |")
    print("+----------------------------------------------------------+")

    if args.trigger_github:
        return 0 if trigger_github() else 1

    if do_all or args.ratsinfo:
        if not sync_ratsinfo():
            success = False

    if do_all or args.geo:
        if not sync_geo():
            print("  (Hinweis: Geodaten-Fehler sind meist unkritisch, z. B. temporaere Overpass-Auslastung)")

    if do_all or args.gremien:
        if not sync_gremien():
            print("  (Hinweis: Gremien-Fehler sind meist unkritisch)")

    if do_all or args.rebuild_db:
        if not rebuild_db(no_text=args.no_text):
            success = False

    print("\n" + "="*60)
    if success:
        print("[OK] Gesamter Sync-Vorgang erfolgreich beendet.")
    else:
        print("[WARNUNG] Sync-Vorgang mit Warnungen / Fehlern beendet.")
    print("="*60)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
