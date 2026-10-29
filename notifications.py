"""
Envío de notificaciones para las alertas de precio/stock (Fase 3 y 4).

Todo se configura por variables de entorno — nada hardcodeado. Si una
variable no está configurada, ese canal simplemente se omite (no falla el
programa, solo no se envía por ahí). Esto permite correr y probar el
mecanismo de alertas completo en desarrollo sin tener credenciales reales
de SMTP ni un webhook configurado.

Variables de entorno usadas:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, ALERT_EMAIL_TO
  SLACK_WEBHOOK_URL
  DISCORD_WEBHOOK_URL
"""

import os
import smtplib
from email.message import EmailMessage

import requests


def _build_message(alert) -> str:
    if alert.alert_type == "stock_change":
        return (
            f"📦 Cambio de stock — {alert.product_code} en "
            f"{alert.retail.code if alert.retail else alert.retail_id}: "
            f"{alert.previous_value} → {alert.new_value}"
        )
    return (
        f"💰 Cambio de precio — {alert.product_code} en "
        f"{alert.retail.code if alert.retail else alert.retail_id}: "
        f"S/ {alert.previous_value} → S/ {alert.new_value}"
    )


def send_email_alert(alert) -> tuple[bool, str | None]:
    host = os.environ.get("SMTP_HOST")
    port = os.environ.get("SMTP_PORT")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    sender = os.environ.get("SMTP_FROM", user)
    recipient = os.environ.get("ALERT_EMAIL_TO")

    if not all([host, port, user, password, recipient]):
        return False, "SMTP no configurado (falta alguna variable de entorno) — no se envió email."

    try:
        msg = EmailMessage()
        msg["Subject"] = "Vigía — alerta de precio/stock"
        msg["From"] = sender
        msg["To"] = recipient
        msg.set_content(_build_message(alert))

        with smtplib.SMTP(host, int(port), timeout=10) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
        return True, None
    except Exception as e:
        return False, f"Error enviando email: {e}"


def send_webhook_alert(alert) -> tuple[bool, str | None]:
    slack_url = os.environ.get("SLACK_WEBHOOK_URL")
    discord_url = os.environ.get("DISCORD_WEBHOOK_URL")

    if not slack_url and not discord_url:
        return False, "No hay webhook de Slack/Discord configurado — no se envió."

    text = _build_message(alert)
    errors = []
    sent_any = False

    if slack_url:
        try:
            resp = requests.post(slack_url, json={"text": text}, timeout=10)
            resp.raise_for_status()
            sent_any = True
        except Exception as e:
            errors.append(f"Slack: {e}")

    if discord_url:
        try:
            resp = requests.post(discord_url, json={"content": text}, timeout=10)
            resp.raise_for_status()
            sent_any = True
        except Exception as e:
            errors.append(f"Discord: {e}")

    return sent_any, ("; ".join(errors) if errors else None)


def notify_alert(alert):
    """
    Intenta notificar por todos los canales configurados. Actualiza
    alert.notified / alert.notify_error según el resultado, pero NO hace
    commit — eso lo hace quien llama, junto con el resto de la transacción.
    """
    email_ok, email_err = send_email_alert(alert)
    webhook_ok, webhook_err = send_webhook_alert(alert)

    alert.notified = email_ok or webhook_ok

    errors = [e for e in [email_err, webhook_err] if e]
    alert.notify_error = " | ".join(errors) if errors else None

    if not email_ok and not webhook_ok:
        print(f"[alertas] Sin canal configurado o falló el envío — {alert.notify_error}")
    else:
        print(f"[alertas] Notificación enviada ({'email' if email_ok else ''}"
              f"{' + ' if email_ok and webhook_ok else ''}"
              f"{'webhook' if webhook_ok else ''}) para {alert.product_code}")
