#!/usr/bin/env python3
"""Sync-Report per E-Mail an den Admin — reine Standardbibliothek (smtplib).

Bewusst KEINE Mail-Action aus dem Marketplace: die SMTP-Zugangsdaten sollen
nicht durch fremden Action-Code laufen. Konfiguration ausschließlich über
Repo-Secrets (als Env-Variablen hereingereicht):

  MAIL_TO    Empfängeradresse (Pflicht — fehlt sie, wird still übersprungen)
  SMTP_HOST  z. B. smtp.gmail.com
  SMTP_PORT  optional; 465 = SSL, sonst STARTTLS (Standard: 587)
  SMTP_USER  Login (auch Absenderadresse, sofern MAIL_FROM nicht gesetzt)
  SMTP_PASS  Passwort bzw. App-Passwort

Aufruf für Erfolgsbericht:
  python tools/send_report_mail.py --subject "…" --body report.md [--url PR-URL]

Aufruf für Fehlerbericht:
  python tools/send_report_mail.py --failure --run-url "…" [--error-msg "…"]
"""
from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", default="")
    ap.add_argument("--body", default="", help="Pfad zur Markdown-Datei oder Nachrichtentext")
    ap.add_argument("--url", default="", help="PR-URL oder Compare-URL, wird dem Text vorangestellt")
    ap.add_argument("--failure", action="store_true", help="Sendet Fehlerbericht statt Erfolgsbericht")
    ap.add_argument("--run-url", default="", help="URL des GitHub Actions Runs")
    ap.add_argument("--branch", default="", help="Git Branch")
    ap.add_argument("--commit", default="", help="Commit SHA")
    ap.add_argument("--error-msg", default="", help="Spezifische Fehlermeldung")
    args = ap.parse_args()

    to = os.environ.get("MAIL_TO", "").strip()
    host = os.environ.get("SMTP_HOST", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    pw = os.environ.get("SMTP_PASS", "")
    port = int(os.environ.get("SMTP_PORT", "587") or "587")
    sender = os.environ.get("MAIL_FROM", "").strip() or user

    fehlt = [n for n, v in [("MAIL_TO", to), ("SMTP_HOST", host),
                            ("SMTP_USER", user), ("SMTP_PASS", pw)] if not v]
    if fehlt:
        print(f"::warning::E-Mail-Benachrichtigung übersprungen — Secrets fehlen: {', '.join(fehlt)}")
        return 0

    if args.failure:
        subject = args.subject or "❌ Fehler beim wöchentlichen Sync (Ratsinfo) — Erlangen-Kommunal/SBR-Buechenbach"
        lines = [
            "Der automatische wöchentliche Sync (Weekly Sync / Ratsinfo) ist fehlgeschlagen.",
            "",
            f"GitHub Action Run:  {args.run_url}" if args.run_url else "",
            f"Branch:             {args.branch}" if args.branch else "",
            f"Commit:             {args.commit}" if args.commit else "",
            f"Status / Fehler:    {args.error_msg}" if args.error_msg else "",
            "",
            "Mögliche Ursachen & Lösung:",
            "1. Pull Request konnte nicht erstellt werden (Exit Code 1):",
            "   -> In den GitHub-Repo-Einstellungen unter 'Settings' -> 'Actions' -> 'General' -> 'Workflow permissions'",
            "      die Option 'Allow GitHub Actions to create and approve pull requests' AKTIVIEREN.",
            "   -> Die Änderungen wurden bereits auf den Branch 'sync/ratsinfo' gepusht.",
            "      Sie können den PR manuell prüfen & öffnen unter:",
            "      https://github.com/Erlangen-Kommunal/SBR-Buechenbach/compare/main...sync/ratsinfo?expand=1",
            "",
            "2. Ratsinformationssystem oder Overpass/OSM temporär nicht erreichbar:",
            "   -> Der Sync kann manuell in VS Code / Antigravity oder über 'Run workflow' auf GitHub wiederholt werden.",
            "",
        ]
        if args.body:
            body_path = Path(args.body)
            if body_path.is_file():
                lines.append("--- Auszug aus dem Sync-Bericht ---")
                lines.append(body_path.read_text(encoding="utf-8"))
            else:
                lines.append(args.body)
        body = "\n".join(line for line in lines if line is not None)
    else:
        subject = args.subject or "Wöchentlicher Sync-Bericht (Ratsinfo)"
        body_text = ""
        if args.body:
            body_path = Path(args.body)
            body_text = body_path.read_text(encoding="utf-8") if body_path.is_file() else args.body

        header = []
        if args.url:
            if "compare" in args.url:
                header.append("HINWEIS: Automatische PR-Erstellung benötigt Repo-Berechtigung.")
                header.append("Änderungen wurden auf den Branch 'sync/ratsinfo' gepusht.")
                header.append(f"Pull Request manuell erstellen und prüfen:\n{args.url}\n")
            else:
                header.append(f"Pull Request zum Prüfen und Mergen:\n{args.url}\n")
        body = "\n".join(header) + "\n\n" + body_text if header else body_text

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body)

    ctx = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(user, pw)
                s.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        print(f"::error::E-Mail-Versand fehlgeschlagen: {e}")
        return 1

    print(f"Benachrichtigung an {to} gesendet ({subject}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
