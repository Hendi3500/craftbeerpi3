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


class FakeAntwort(object):
    """So sieht eine Antwort von Telegram aus - nur das Nötigste."""

    def __init__(self, status_code=200, text='{"ok":true}', daten=None):
        self.status_code = status_code
        self.text = text
        self._daten = daten or {}

    def json(self):
        return self._daten


def run():
    from modules import cbpi
    from modules.plugins import TelegramPushNotifications as telegram

    print("--- Der Text wird escaped --------------------------------------")
    text = telegram._formatiere({
        "headline": "Hop Alert",
        "message": "Heater < 50 % & rising > 20",
    })
    check("die spitzen Klammern sind escaped",
          "Heater &lt; 50" in text and "Heater < 50" not in text, repr(text))
    check("das groesere-Zeichen ist escaped", "&gt; 20" in text, repr(text))
    check("das kaufmännische Und ist escaped", "&amp;" in text, repr(text))
    check("die Formatierung bleibt erhalten", text.startswith("<b>Hop Alert</b>"),
          repr(text))

    text2 = telegram._formatiere({"headline": "Nur eine Ueberschrift", "message": ""})
    check("eine Meldung ohne Text wird nicht kaputt", "<b>" in text2, repr(text2))

    text3 = telegram._formatiere({"headline": None, "message": None})
    check("eine leere Meldung ergibt leeren Text", text3 == "", repr(text3))

    print("\n--- Der Token kommt nicht ins Log ----------------------------")
    token = "123456:ABC-DEF"
    maskiert = telegram._ohne_token(
        "Max retries exceeded with url: /bot123456:ABC-DEF/sendMessage", token)
    check("der Token wird maskiert", token not in maskiert, repr(maskiert))
    check("der Rest des Textes bleibt lesbar", "Max retries exceeded" in maskiert,
          repr(maskiert))

    print("\n--- Die Konfiguration wird bei jeder Nachricht gelesen ------")
    # Zwei Config-Parameter anlegen und den Cache fuellen.
    telegram._parameter_anlegen()
    cache = cbpi.cache.get("config") or {}
    check("der Token-Parameter existiert", telegram.PARAM_TOKEN in cache,
          repr(sorted(cache.keys())))
    check("der Chat-ID-Parameter existiert", telegram.PARAM_CHAT in cache)
    check("der Parameter fuer die Startnachricht existiert",
          telegram.PARAM_STARTUP in cache)

    gespeichert = {}

    def _hole(name, default=None):
        return gespeichert.get(name, default)

    original_get = cbpi.get_config_parameter
    cbpi.get_config_parameter = _hole
    try:
        gespeichert[telegram.PARAM_TOKEN] = "  123456:ABC  "
        gespeichert[telegram.PARAM_CHAT] = "111, 222 ,"
        tok, chats = telegram._einstellungen()
        check("der Token wird getrimmt", tok == "123456:ABC", repr(tok))
        check("mehrere Chat-IDs werden gelesen", chats == ["111", "222"], repr(chats))

        # Und die Aenderung wirkt sofort - ohne Neustart.
        gespeichert[telegram.PARAM_CHAT] = "333"
        tok2, chats2 = telegram._einstellungen()
        check("eine geaenderte Chat-ID wirkt sofort", chats2 == ["333"], repr(chats2))
    finally:
        cbpi.get_config_parameter = original_get

    print("\n--- Senden und Fehlerbehandlung ------------------------------")
    gesendet = []

    def fake_post(url, data=None, timeout=None):
        gesendet.append((url, data, timeout))
        return FakeAntwort(200)

    original_post = telegram.requests.post
    telegram.requests.post = fake_post
    try:
        ok = telegram._sende("123456:ABC", "111", "<b>Test</b>")
        check("eine gueltige Nachricht wird angenommen", ok is True)
        check("die Nachricht geht an den richtigen Chat",
              gesendet and gesendet[0][1].get("chat_id") == "111", repr(gesendet))
        check("die Nachricht hat ein Timeout", gesendet and gesendet[0][2] == telegram.TIMEOUT)
        check("der Token steht in der URL", gesendet and "123456:ABC" in gesendet[0][0])

        gesendet.clear()

        def fake_post_429(url, data=None, timeout=None):
            gesendet.append((url, data, timeout))
            return FakeAntwort(429, '{"ok":false,"error_code":429}',
                               {"ok": False, "error_code": 429,
                                "parameters": {"retry_after": 3}})

        telegram.requests.post = fake_post_429
        ok = telegram._sende("123456:ABC", "111", "<b>Test</b>")
        check("bei 429 wird es noch einmal versucht", ok is False)
        check("bei 429 wird zweimal gesendet", len(gesendet) == 2, repr(len(gesendet)))

        def fake_post_500(url, data=None, timeout=None):
            return FakeAntwort(500, '{"ok":false,"description":"Internal Server Error"}')

        telegram.requests.post = fake_post_500
        ok = telegram._sende("123456:ABC", "111", "<b>Test</b>")
        check("ein Serverfehler wird als Fehler gemeldet", ok is False)

        def fake_post_boom(url, data=None, timeout=None):
            raise telegram.requests.RequestException(
                "Max retries exceeded with url: /bot123456:ABC/sendMessage")

        telegram.requests.post = fake_post_boom
        ok = telegram._sende("123456:ABC", "111", "<b>Test</b>")
        check("ein Netzwerkfehler wirft nicht", ok is False)
    finally:
        telegram.requests.post = original_post

    print("\n--- Ohne Konfiguration wird nichts gesendet ------------------")
    aufrufe = []

    def fake_post2(url, data=None, timeout=None):
        aufrufe.append(url)
        return FakeAntwort(200)

    original_post = telegram.requests.post
    original_get = cbpi.get_config_parameter
    cbpi.get_config_parameter = lambda name, default=None: default
    telegram.requests.post = fake_post2
    try:
        telegram.message_event({"headline": "Test", "message": "Test"})
        check("ohne Token wird nichts gesendet", len(aufrufe) == 0, repr(aufrufe))
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
