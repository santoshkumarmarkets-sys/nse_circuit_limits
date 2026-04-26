#!/usr/bin/env python3
"""
NSE Scanner Status Mailer
Checks if all scanners ran today, reads signal counts, sends email summary.

Setup: set GMAIL_APP_PASSWORD as a Windows env variable (run once as admin):
  setx GMAIL_APP_PASSWORD "your-16-char-app-password" /M
Get an app password at: myaccount.google.com/apppasswords
"""

import subprocess, smtplib, os, re, sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8")

IST       = timezone(timedelta(hours=5, minutes=30))
BASE      = os.path.dirname(os.path.abspath(__file__))
TO_EMAIL  = "santoshkumarmarkets@gmail.com"
FROM_EMAIL= os.environ.get("GMAIL_USER", "santoshkumarmarkets@gmail.com")

SCANNER_KEYWORDS = {
    "Swing Scanner":        "swing scan",
    "Momentum Scanner":     "momentum scan",
    "Weekly RS Scanner":    "momentum rs-weekly scan",
    "EMA25 ZL Scanner":     "ema25-zl scan",
    "EMA Screener":         "screener:",
    "Dashboard":            "dashboard",
}


def today_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def get_today_commits() -> str:
    today = today_ist()
    r = subprocess.run(
        ["git", "log", "--oneline", f"--since={today} 00:00"],
        capture_output=True, text=True, cwd=BASE
    )
    return r.stdout.lower()


def read_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def parse_signal_count(md: str, today: str) -> str:
    blocks = re.split(r'\n---\n', md)
    for block in blocks:
        if today in block:
            rows = [l for l in block.splitlines()
                    if l.strip().startswith('|') and not l.strip().startswith('| Symbol') and '|---' not in l]
            return str(len(rows))
    return "—"


def parse_ema25_zl_counts(md: str, today: str) -> tuple[str, str]:
    m = re.search(rf'\*\*ZLEMA25 Rising: (\d+)\*\*.*?\*\*ZLEMA25 Watch: (\d+)\*\*', md)
    if m and today in md[:200]:
        return m.group(1), m.group(2)
    return "—", "—"


def parse_screener_counts(md: str, today: str) -> tuple[str, str]:
    if today not in md[:100]:
        return "—", "—"
    adds = re.search(r'## ✅ Additions.*?\((\d+)\)', md)
    dels = re.search(r'## ❌ Deletions.*?\((\d+)\)', md)
    return (adds.group(1) if adds else "0"), (dels.group(1) if dels else "0")


def get_scan_details(today: str) -> dict:
    swing_md    = read_file(os.path.join(BASE, "swing_scans", "swing_scans.md"))
    mom_md      = read_file(os.path.join(BASE, "momentum_scans", "momentum_scans.md"))
    weekly_md   = read_file(os.path.join(BASE, "momentum_scans", "momentum_rs_weekly_scans.md"))
    zl25_md     = read_file(os.path.join(BASE, "ema25_zl_scans", "ema25_zl_scans.md"))
    screener_md = read_file(os.path.join(BASE, "ema_screener_changes.md"))

    zl_rising, zl_watch = parse_ema25_zl_counts(zl25_md, today)
    ema_adds, ema_dels  = parse_screener_counts(screener_md, today)

    return {
        "Swing Scanner":     parse_signal_count(swing_md,  today) + " signals",
        "Momentum Scanner":  parse_signal_count(mom_md,    today) + " signals",
        "Weekly RS Scanner": parse_signal_count(weekly_md, today) + " signals",
        "EMA25 ZL Scanner":  f"Rising {zl_rising} / Watch {zl_watch}",
        "EMA Screener":      f"+{ema_adds} adds / -{ema_dels} exits",
        "Dashboard":         "generated",
    }


def build_html_email(today: str, status: dict, details: dict, all_ok: bool) -> str:
    color  = "#2ea44f" if all_ok else "#d73a49"
    header = "All scanners OK" if all_ok else "Scanner issues detected"

    rows = ""
    for name, ok in status.items():
        icon   = "✅" if ok else "❌"
        detail = details.get(name, "—")
        bg     = "#f6fff8" if ok else "#fff6f6"
        rows += f"""
        <tr style="background:{bg}">
          <td style="padding:8px 12px;border-bottom:1px solid #e1e4e8">{icon} {name}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e1e4e8;color:#586069">{detail}</td>
        </tr>"""

    failed_note = ""
    if not all_ok:
        failed = [n for n, ok in status.items() if not ok]
        failed_note = f'<p style="color:#d73a49;margin-top:12px">Missing: {", ".join(failed)}</p>'

    return f"""
<html><body style="font-family:Segoe UI,sans-serif;font-size:14px;color:#24292e;max-width:600px;margin:0 auto;padding:20px">
  <h2 style="color:{color};margin-bottom:4px">NSE Scanners — {header}</h2>
  <p style="color:#586069;margin-top:0">{today} · Generated {datetime.now(IST).strftime('%H:%M IST')}</p>
  <table style="width:100%;border-collapse:collapse;border:1px solid #e1e4e8;border-radius:6px;overflow:hidden">
    <thead>
      <tr style="background:#f6f8fa">
        <th style="padding:8px 12px;text-align:left;color:#586069;font-size:12px">Scanner</th>
        <th style="padding:8px 12px;text-align:left;color:#586069;font-size:12px">Result</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  {failed_note}
  <p style="color:#959da5;font-size:11px;margin-top:16px">NSE Circuit Limits Dashboard · satya482/nse_circuit_limits</p>
</body></html>"""


def send_email(subject: str, html: str) -> bool:
    app_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not app_pass:
        print("  [email] GMAIL_APP_PASSWORD not set.")
        print("  Run: setx GMAIL_APP_PASSWORD \"your-app-password\" /M")
        print("  Get one at: myaccount.google.com/apppasswords")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = FROM_EMAIL
    msg["To"]      = TO_EMAIL
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(FROM_EMAIL, app_pass)
        s.send_message(msg)
    return True


def main():
    today   = today_ist()
    commits = get_today_commits()

    status = {
        name: keyword in commits
        for name, keyword in SCANNER_KEYWORDS.items()
    }
    details = get_scan_details(today)
    all_ok  = all(status.values())

    print(f"\nNSE Scanner Status — {today}")
    print("=" * 45)
    for name, ok in status.items():
        icon   = "OK  " if ok else "MISS"
        detail = details.get(name, "")
        print(f"  [{icon}] {name:<22}  {detail}")
    print("=" * 45)
    if all_ok:
        print("  All scanners completed.\n")
    else:
        failed = [n for n, ok in status.items() if not ok]
        print(f"  Missing: {', '.join(failed)}\n")

    icon    = "OK" if all_ok else "ALERT"
    subject = f"[NSE {icon}] Scanners {today} — {'All OK' if all_ok else 'Issues'}"
    html    = build_html_email(today, status, details, all_ok)

    if send_email(subject, html):
        print(f"  Email sent to {TO_EMAIL}")
    else:
        print("  Email skipped — set GMAIL_APP_PASSWORD to enable.")


if __name__ == "__main__":
    main()