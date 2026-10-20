#!/usr/bin/env python3
"""
TelegramPushNotifications: das Weiterleiten der Meldungen.

Geprueft werden die Stellen, an denen die Vorlage
(ShintoTuna/cbpi-telegram) in der Praxis ausgefallen ist:

1. Der Text wurde nicht escaped. Ein ``<``, ``>`` oder ``&`` in der
   Meldung laesst Telegram die Nachricht ablehnen ("can't parse
   entities") - sie kommt nie an.
2. Die Fehlermeldung von ``requests`` enthaelt die vollstaendige URL
   und damit den Bot-Token. Im Log darf der Token nicht stehen.
3. Die Konfiguration wird bei jeder Nachricht gelesen - eine
   Aenderung in der Oberflaeche muss sofort wirken, nicht erst nach
   einem Neustart.
4. Ohne Token oder ohne Chat-ID wird nichts gesendet, aber es darf
   auch kein Fehler nach aussen schlagen.

Abruf:  python3 tools/test_telegram_plugin.py
         Exit 0 = alle Pruefungen bestanden.
"""

import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

PASS = []
FAIL = []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print("  [%s] %s" % ("ok  " if condition else "FAIL", name))
    if detail and not condition:
        print("         -> %s" % detail)


class FakeResponse(object):
    """So sieht eine Antwort von Telegram aus - nur das Nötigste."""

    def __init__(self, status_code=200, text='{"ok":true}', data=None):
        self.status_code = status_code
        self.text = text
        self._data = data or {}

    def json(self):
        return self._data


def run():
    from modules import cbpi
    from modules.plugins import TelegramPushNotifications as telegram

    print("--- Der Text wird escaped --------------------------------------")
    text = telegram._format_message({
        "headline": "Hop Alert",
        "message": "Heater < 50 % & rising > 20",
    })
    check("die spitzen Klammern sind escaped",
          "Heater &lt; 50" in text and "Heater < 50" not in text, repr(text))
    check("das groesere-Zeichen ist escaped", "&gt; 20" in text, repr(text))
    check("das kaufmännische Und ist escaped", "&amp;" in text, repr(text))
    check("die Formatierung bleibt erhalten", text.startswith("<b>Hop Alert</b>"),
          repr(text))

    text2 = telegram._format_message({"headline": "Nur eine Ueberschrift", "message": ""})
    check("eine Meldung ohne Text wird nicht kaputt", "<b>" in text2, repr(text2))

    text3 = telegram._format_message({"headline": None, "message": None})
    check("eine leere Meldung ergibt leeren Text", text3 == "", repr(text3))

    print("\n--- Der Token kommt nicht ins Log ----------------------------")
    token = "123456:ABC-DEF"
    masked = telegram._without_token(
        "Max retries exceeded with url: /bot123456:ABC-DEF/sendMessage", token)
    check("der Token wird maskiert", token not in masked, repr(masked))
    check("der Rest des Textes bleibt lesbar", "Max retries exceeded" in masked,
          repr(masked))

    print("\n--- Die Konfiguration wird bei jeder Nachricht gelesen ------")
    # Zwei Config-Parameter anlegen und den Cache fuellen.
    telegram._create_parameters()
    cache = cbpi.cache.get("config") or {}
    check("der Token-Parameter existiert", telegram.PARAM_TOKEN in cache,
          repr(sorted(cache.keys())))
    check("der Chat-ID-Parameter existiert", telegram.PARAM_CHAT in cache)
    check("der Parameter fuer die Startnachricht existiert",
          telegram.PARAM_STARTUP in cache)

    stored = {}

    def _get(name, default=None):
        return stored.get(name, default)

    original_get = cbpi.get_config_parameter
    cbpi.get_config_parameter = _get
    try:
        stored[telegram.PARAM_TOKEN] = "  123456:ABC  "
        stored[telegram.PARAM_CHAT] = "111, 222 ,"
        tok, chats = telegram._settings()
        check("der Token wird getrimmt", tok == "123456:ABC", repr(tok))
        check("mehrere Chat-IDs werden gelesen", chats == ["111", "222"], repr(chats))

        # Und die Aenderung wirkt sofort - ohne Neustart.
        stored[telegram.PARAM_CHAT] = "333"
        tok2, chats2 = telegram._settings()
        check("eine geaenderte Chat-ID wirkt sofort", chats2 == ["333"], repr(chats2))
    finally:
        cbpi.get_config_parameter = original_get

    print("\n--- Senden und Fehlerbehandlung ------------------------------")
    sent = []

    def fake_post(url, data=None, timeout=None):
        sent.append((url, data, timeout))
        return FakeResponse(200)

    original_post = telegram.requests.post
    telegram.requests.post = fake_post
    try:
        ok = telegram._send("123456:ABC", "111", "<b>Test</b>")
        check("eine gueltige Nachricht wird angenommen", ok is True)
        check("die Nachricht geht an den richtigen Chat",
              sent and sent[0][1].get("chat_id") == "111", repr(sent))
        check("die Nachricht hat ein Timeout", sent and sent[0][2] == telegram.TIMEOUT)
        check("der Token steht in der URL", sent and "123456:ABC" in sent[0][0])

        # Der Ton: Telegram kennt den Schalter disable_notification.
        check("mit Ton wird der Ton nicht abgeschaltet",
              sent[0][1].get("disable_notification") == "false", repr(sent))

        sent.clear()
        telegram._send("123456:ABC", "111", "<b>Test</b>", with_sound=False)
        check("ohne Ton wird der Ton abgeschaltet",
              sent and sent[0][1].get("disable_notification") == "true",
              repr(sent))

        sent.clear()

        def fake_post_429(url, data=None, timeout=None):
            sent.append((url, data, timeout))
            return FakeResponse(429, '{"ok":false,"error_code":429}',
                               {"ok": False, "error_code": 429,
                                "parameters": {"retry_after": 3}})

        telegram.requests.post = fake_post_429
        ok = telegram._send("123456:ABC", "111", "<b>Test</b>")
        check("bei 429 wird es noch einmal versucht", ok is False)
        check("bei 429 wird zweimal gesendet", len(sent) == 2, repr(len(sent)))

        def fake_post_500(url, data=None, timeout=None):
            return FakeResponse(500, '{"ok":false,"description":"Internal Server Error"}')

        telegram.requests.post = fake_post_500
        ok = telegram._send("123456:ABC", "111", "<b>Test</b>")
        check("ein Serverfehler wird als Fehler gemeldet", ok is False)

        def fake_post_boom(url, data=None, timeout=None):
            raise telegram.requests.RequestException(
                "Max retries exceeded with url: /bot123456:ABC/sendMessage")

        telegram.requests.post = fake_post_boom
        ok = telegram._send("123456:ABC", "111", "<b>Test</b>")
        check("ein Netzwerkfehler wirft nicht", ok is False)
    finally:
        telegram.requests.post = original_post

    print("\n--- Ohne Konfiguration wird nichts gesendet ------------------")
    calls = []

    def fake_post2(url, data=None, timeout=None):
        calls.append(url)
        return FakeResponse(200)

    original_post = telegram.requests.post
    original_get = cbpi.get_config_parameter
    cbpi.get_config_parameter = lambda name, default=None: default
    telegram.requests.post = fake_post2
    try:
        telegram.message_event({"headline": "Test", "message": "Test"})
        check("ohne Token wird nichts gesendet", len(calls) == 0, repr(calls))
    finally:
        telegram.requests.post = original_post
        cbpi.get_config_parameter = original_get

    print("\n--- Der Ton haengt am Ablauf-Timer -----------------------")
    check("eine Meldung ohne Timer klingelt",
          telegram._with_sound({"headline": "H", "message": "M", "timeout": None}) is True)
    check("eine Meldung mit Timer klingelt nicht",
          telegram._with_sound({"headline": "H", "message": "M", "timeout": 5000}) is False)
    check("eine Meldung ohne Timeout-Angabe klingelt",
          telegram._with_sound({"headline": "H", "message": "M"}) is True)

    sent.clear()
    original_post = telegram.requests.post
    original_get = cbpi.get_config_parameter
    cbpi.get_config_parameter = lambda name, default=None: {
        telegram.PARAM_TOKEN: "123456:ABC",
        telegram.PARAM_CHAT: "111",
    }.get(name, default)
    telegram.requests.post = fake_post
    try:
        telegram.message_event({"headline": "Fehler", "message": "Kessel kalt",
                                "timeout": None})
        check("eine bleibende Meldung klingelt am Handy",
              sent and sent[-1][1].get("disable_notification") == "false",
              repr(sent))

        sent.clear()
        telegram.message_event({"headline": "Schritt", "message": "Heizen",
                                "timeout": 5000})
        check("eine Meldung mit Timer kommt ohne Ton",
              sent and sent[-1][1].get("disable_notification") == "true",
              repr(sent))
    finally:
        telegram.requests.post = original_post
        cbpi.get_config_parameter = original_get

    return len(PASS), len(FAIL)


def main():
    p, f = run()
    print("\n%d von %d Pruefungen bestanden" % (p, p + f))
    if f:
        print("Fehlgeschlagen: %d" % f)
        for name in FAIL:
            print("  - %s" % name)
        return 1
    print("ALLE PRUEFUNGEN BESTANDEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
