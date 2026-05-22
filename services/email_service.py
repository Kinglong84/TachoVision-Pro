"""
services/email_service.py
Apre il client email locale (Outlook, Thunderbird, Mail, ecc.)
con i file allegati gia pronti. NON invia email direttamente.

Compatibile con Python 3.8+
"""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import urllib.parse
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple
import json

CONFIG_PATH = Path.home() / "TachoVision" / "config" / "email.json"


@dataclass
class EmailConfig:
    default_recipients: List[str] = field(default_factory=list)
    default_subject_prefix: str   = "Scarico carta tachigrafo"
    from_name: str                 = "TachoVision Pro"

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @staticmethod
    def load() -> "EmailConfig":
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return EmailConfig(**{
                    k: v for k, v in data.items()
                    if k in EmailConfig.__dataclass_fields__
                })
            except Exception:
                pass
        return EmailConfig()


def build_email_content(driver_name: str, card_number: str,
                        download_date: str) -> Tuple[str, str]:
    subject = "Scarico carta tachigrafo - " + driver_name + " - " + download_date
    body = (
        "Scarico carta tachigrafo\n\n"
        "Conducente:    " + driver_name + "\n"
        "Numero carta:  " + card_number + "\n"
        "Data scarico:  " + download_date + "\n\n"
        "In allegato il file .DDD e i report generati da TachoVision Pro.\n\n"
        "---\nTachoVision Pro - Reg. (CE) n. 561/2006 e Dir. 2006/22/CE"
    )
    return subject, body


def save_attachments_to_temp(
    attachments: List[Tuple[str, bytes]]
) -> List[str]:
    tmp_dir = Path(tempfile.gettempdir()) / "tachovision_email"
    tmp_dir.mkdir(exist_ok=True)
    paths = []
    for filename, data in attachments:
        # Path.name estrae solo il nome base, eliminando qualsiasi directory component
        # (es. "../../etc/passwd" diventa "passwd"). Previene path traversal.
        safe_name = Path(filename).name or "allegato.bin"
        p = tmp_dir / safe_name
        p.write_bytes(data)
        paths.append(str(p))
    return paths


def open_mail_client(
    recipients: List[str],
    subject: str,
    body: str,
    attachment_paths: List[str],
) -> Tuple[bool, str]:
    os_name = platform.system()
    if os_name == "Windows":
        return _open_windows(recipients, subject, body, attachment_paths)
    elif os_name == "Darwin":
        return _open_macos(recipients, subject, body, attachment_paths)
    else:
        return _open_linux(recipients, subject, body, attachment_paths)


def _open_windows(recipients, subject, body, paths) -> Tuple[bool, str]:
    try:
        import win32com.client  # type: ignore
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.To      = "; ".join(recipients)
        mail.Subject = subject
        mail.Body    = body
        for p in paths:
            mail.Attachments.Add(p)
        mail.Display(True)
        return True, "Outlook aperto con " + str(len(paths)) + " allegato/i."
    except ImportError:
        pass
    except Exception:
        pass

    mailto = _build_mailto(recipients, subject, body)
    try:
        subprocess.Popen(["cmd", "/c", "start", "", mailto], shell=False)
        note = _attach_note(paths)
        return True, "Client email aperto." + note
    except Exception as e:
        return False, "Impossibile aprire il client email: " + str(e)


def _open_macos(recipients, subject, body, paths) -> Tuple[bool, str]:
    # Costruisce AppleScript senza f-string contenenti backslash
    # per compatibilita con Python 3.8-3.11
    newline = "\n"

    def _esc(s):
        # Escape per AppleScript string (no backslash in f-string)
        s = s.replace(chr(92), "\\\\")   # backslash
        s = s.replace('"', '\\"')         # doppio apice
        s = s.replace(newline, "\\n")     # newline
        return s

    recipient_lines = newline.join(
        '        to recipient "' + r + '"' for r in recipients
    ) if recipients else ""

    attach_lines = newline.join(
        '        make new attachment with properties {file name:POSIX file "' + p + '"} '
        'at after the last paragraph of content of theMessage'
        for p in paths
    )

    lines = [
        'tell application "Mail"',
        '    set theMessage to make new outgoing message with properties {',
        '        subject:"' + _esc(subject) + '",',
        '        content:"' + _esc(body) + '",',
        '        visible:true',
        '    }',
        '    tell theMessage',
    ]
    if recipient_lines:
        lines.append(recipient_lines)
    if attach_lines:
        lines.append(attach_lines)
    lines += ['    end tell', '    activate', 'end tell']
    script = newline.join(lines)

    try:
        subprocess.run(["osascript", "-e", script], check=True,
                       capture_output=True, timeout=10)
        return True, "Mail.app aperto con " + str(len(paths)) + " allegato/i."
    except subprocess.SubprocessError:
        pass

    try:
        subprocess.Popen(["open", _build_mailto(recipients, subject, body)])
        return True, "Client email aperto." + _attach_note(paths)
    except Exception as e:
        return False, "Impossibile aprire Mail.app: " + str(e)


def _open_linux(recipients, subject, body, paths) -> Tuple[bool, str]:
    import shutil

    if shutil.which("xdg-email"):
        cmd = ["xdg-email"]
        for r in recipients:
            cmd.append(r)
        cmd += ["--subject", subject, "--body", body]
        for p in paths:
            cmd += ["--attach", p]
        try:
            subprocess.Popen(cmd)
            return True, "Client email aperto con " + str(len(paths)) + " allegato/i."
        except Exception:
            pass

    mailto = _build_mailto(recipients, subject, body)
    launcher = (
        shutil.which("xdg-open")
        or shutil.which("sensible-browser")
        or shutil.which("gnome-open")
    )
    if launcher:
        try:
            subprocess.Popen([launcher, mailto])
            return True, "Client email aperto." + _attach_note(paths)
        except Exception:
            pass

    if paths:
        return (False,
                "Nessun client email trovato.\n"
                "I file sono pronti in:\n" + "\n".join(paths))
    return False, "Nessun client email trovato nel sistema."


def _build_mailto(recipients, subject, body) -> str:
    params = urllib.parse.urlencode(
        {"subject": subject, "body": body},
        quote_via=urllib.parse.quote,
    )
    to = urllib.parse.quote(",".join(recipients))
    return "mailto:" + to + "?" + params


def _attach_note(paths: List[str]) -> str:
    if not paths:
        return ""
    lines = ["\nAllegati salvati in:"]
    lines += ["  - " + p for p in paths]
    lines.append("Trascinali manualmente nella finestra email.")
    return "\n".join(lines)
