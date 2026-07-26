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

Aufruf:  python tools/send_report_mail.py --subject "…" --body report.md [--url PR-URL]
Exit 0 auch bei fehlender Konfiguration (Sync soll daran nie scheitern);
Exit 1 nur, wenn Zugangsdaten da sind, aber der Versand misslingt.
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
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body", required=True, help="Pfad zur Markdown-Datei")
    ap.add_argument("--url", default="", help="PR-URL, wird dem Text vorangestellt")
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
        print(f"::warning::E-Mail-Report übersprungen — Secrets fehlen: {', '.join(fehlt)}")
        return 0

    body = Path(args.body).read_text(encoding="utf-8")
    if args.url:
        body = f"Pull Request zum Prüfen und Mergen:\n{args.url}\n\n{body}"

    msg = EmailMessage()
    msg["Subject"] = args.subject
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

    print(f"Report an {to} gesendet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
