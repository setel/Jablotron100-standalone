# Jablotron 100+ standalone

Samostatná Python knihovna pro lokální komunikaci s ústřednami Jablotron
100+, zejména JA-107K. Nevyžaduje Home Assistant.

Projekt vzniká oddělením protokolové části z integrace
[`kukulich/home-assistant-jablotron100`](https://github.com/kukulich/home-assistant-jablotron100).
Původní integrace i tento odvozený kód používají licenci MIT. Podrobnosti jsou
v `NOTICE.md`.

## Aktuální stav

První etapa obsahuje:

- automatické vyhledání USB HID zařízení `16D6:0008`;
- transport přes `/dev/hidraw*` s vyměnitelným testovacím transportem;
- dělení 64b HID reportů na protokolové pakety;
- vytváření autorizačních, keepalive a ovládacích paketů;
- asynchronního klienta s odběrem příchozích paketů;
- stavové modely a callbacky pro sekce a PG výstupy;
- import konfigurace periferií z Home Assistant `.storage/core.config_entries`;
- dekódování periferií, baterií, signálu, teplot, napětí sirén a pulzů;
- příkazy pro zastřežení, částečné zastřežení, odstřežení a PG výstupy;
- jednotkové testy bez připojené ústředny.

Dekódování všech senzorů a diagnostických dat z původního pluginu se bude
přenášet v další etapě. Do té doby je ovládací API považováno za vývojové a
nemá nahrazovat certifikované ovládání zabezpečovacího systému.

## Instalace pro vývoj

```bash
cd jablotron100-standalone
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests
```

Uživatel služby musí mít oprávnění číst a zapisovat do příslušného
`/dev/hidraw*`. Stejné zařízení nesmí současně obsluhovat Home Assistant.

## Příklad

```python
import asyncio
import os

from jablotron100 import ArmMode, JablotronClient


async def main() -> None:
    async with JablotronClient(code=os.environ["JABLOTRON_CODE"]) as alarm:
        alarm.add_packet_listener(lambda event: print(event.packet.hex()))
        await alarm.set_section(1, ArmMode.ARMED_FULL)
        await asyncio.Event().wait()


asyncio.run(main())
```

Autorizační kód neukládejte přímo do zdrojového kódu.

## Import existující konfigurace Home Assistantu

```python
import os

from jablotron100 import JablotronClient, load_home_assistant_config

config = load_home_assistant_config("/config/.storage/core.config_entries")
client = JablotronClient.from_config(
    config,
    code=os.environ.get("JABLOTRON_CODE"),
)
```

Pokud původní soubor obsahuje `password`, použije jej klient automaticky.
Pro přenos konfigurace mezi počítači je bezpečnější heslo z exportu odstranit
a předat ho až za běhu. Pořadí položek v `devices` je významné: položka na
indexu nula odpovídá periferii číslo 1.

## Směr další práce

1. Přenést diagnostiku ústředny, LAN, GSM, napájení a sběrnice.
2. Doplnit automatický reconnect a úplnou inicializační sekvenci zařízení.
3. Přidat další kompatibilní testovací vektory z upstream repozitáře.
4. Vytvořit adaptér pro vlastní řídicí aplikaci a volitelně MQTT.
