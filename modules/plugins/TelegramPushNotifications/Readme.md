# TelegramPushNotifications

Schickt jede Meldung von CraftBeerPi an einen Telegram-Chat.

Eine lokale, auf Python 3 ueberarbeitete Fassung von
[ShintoTuna/cbpi-telegram](https://github.com/ShintoTuna/cbpi-telegram)
(Nikita Shatunov). Die Vorlage laeuft nicht unter Python 3 (sie
importiert `thread`) und liest die Konfiguration nur beim Start - eine
Aenderung an Token oder Chat-ID wird erst nach einem Neustart
wirksam. Die Aenderungen sind im Docstring der Datei
`__init__.py` einzeln begruendet.

## Einrichtung

1. **Bot anlegen.** In Telegram `@BotFather` suchen, `/newbot` schicken
   und den Anweisungen folgen. BotFather antwortet mit dem Token des
   Bots - der wird als `telegram_bot_token` eingetragen.

2. **Chat-ID ermitteln.** Den eigenen Bot in Telegram oeffnen und
   `/start` schicken. Der Bot muss eine Nachricht vom Chat bekommen,
   sonst kennt er die Chat-ID nicht. Danach im Browser
   `https://api.telegram.org/bot<token>/getUpdates` oeffnen:

   ```json
   {"ok":true,"result":[{"update_id":77,
     "message":{"message_id":333,
       "from":{"id":34,"is_bot":false,"first_name":"..."}}}]}
   ```

   Die Zahl unter `from.id` (hier `34`) ist die Chat-ID. Sie wird als
   `telegram_chat_id` eingetragen.

   Bekommt man keine Chat-ID zu sehen, hilft es, den Bot aus dem Chat
   zu entfernen und wieder hinzuzufuegen - dann startet der Chat die
   Unterhaltung neu und `getUpdates` liefert sie.

3. **Eintragen.** In CraftBeerPi unter *System -> Parameter*:

   | Parameter | Bedeutung |
   |---|---|
   | `telegram_bot_token` | der Token von BotFather |
   | `telegram_chat_id` | die Chat-ID; mehrere durch Komma trennen, dann bekommen alle Geraete die Meldungen |
   | `telegram_startup_message` | `YES` schickt nach jedem Start eine Testnachricht, `NO` nicht |

4. **Backend neu starten.** Die Startnachricht kommt an - damit ist
   bestaetigt, dass die Anbindung funktioniert.

## Was ankommt

Alles, was CraftBeerPi als Meldung erzeugt: "Brewing Finished",
"Step Temp Reached!", "Hop Alert", Fehlermeldungen der Controller, die
Meldung vor einem Neustart des Backends und so weiter.

Die Meldungen der Notification-Oberflaeche (`GET /api/notification/`)
sind davon nicht betroffen - das sind die eintragbaren Nachrichten des
Kerns, keine Ereignisse.

## Hinweise

- Der Bot-Token steht in der URL der Telegram-API. Das Plugin maskiert
  ihn in jeder Logzeile - im Log steht nie der Token.
- Telegram nimmt hoechstens 4096 Zeichen pro Nachricht an; laengere
  Texte werden abgeschnitten.
- Antwortet Telegram mit "Too Many Requests" (429), wartet das Plugin
  die von Telegram genannte Zeit und versucht es ein zweites Mal.
- Der Text wird HTML-escaped. Ein `<`, `>` oder `&` in einer Meldung
  wuerde Telegram sonst die Nachricht ablehnen ("can't parse
  entities") - sie kaeme nie an.
- Laeuft das Backend hinter einem Proxy, der WebSockets nicht
  kann, ist das fuer dieses Plugin ohne Bedeutung: es nutzt nur
  ausgehende HTTP-Anfragen.
