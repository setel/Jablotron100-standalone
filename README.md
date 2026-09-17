# Jablotron 100+ standalone

Samostatná Python knihovna pro lokální komunikaci s ústřednami Jablotron
100+, zejména JA-107K. Nevyžaduje Home Assistant.

Projekt vzniká oddělením protokolové části z integrace
[`kukulich/home-assistant-jablotron100`](https://github.com/kukulich/home-assistant-jablotron100).
Původní integrace i tento odvozený kód používají licenci MIT. Podrobnosti jsou
v `NOTICE.md`.

## Aktuální stav

Verze 0.2 obsahuje:

- automatické vyhledání USB HID zařízení `16D6:0008`;
- transport přes `/dev/hidraw*` s vyměnitelným testovacím transportem;
- dělení 64b HID reportů na protokolové pakety;
- vytváření autorizačních, keepalive a ovládacích paketů;
- asynchronního klienta s odběrem příchozích paketů;
- stavové modely a callbacky pro sekce a PG výstupy;
- samostatnou, ručně editovatelnou TOML konfiguraci;
- bezpečný převod z Home Assistant `.storage/core.config_entries`;
- dekódování periferií, baterií, signálu, teplot, napětí sirén a pulzů;
- identifikaci modelu, HW a FW ústředny;
- diagnostiku napájení, baterie, BUS napětí a výpadků zařízení;
- stav LAN, DHCP, IP adresu, stav GSM a sílu GSM signálu;
- úplnou inicializační sekvenci nakonfigurovaných periferií;
- automatický reconnect USB s exponenciální prodlevou;
- příkazy pro zastřežení, částečné zastřežení, odstřežení a PG výstupy;
- jednotkové testy bez připojené ústředny.

API je stále vývojové a nemá nahrazovat certifikované ovládání
zabezpečovacího systému. Diagnostické dekódování vychází z upstream integrace;
skutečné pakety konkrétní JA-107K je ještě potřeba ověřit na Raspberry Pi.

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

## Samostatná konfigurace

Vzor je v `config/jablotron.example.toml`. Formát je sparse: uvedou se pouze
osazené pozice a ostatní knihovna automaticky doplní jako `empty`.

```toml
[connection]
port = "auto"
code_env = "JABLOTRON_CODE"

[system]
number_of_devices = 120
number_of_pg_outputs = 32

[[devices]]
number = 3
type = "motion_detector"
name = "Chodba"
```

Autorizační kód doporučujeme ponechat mimo soubor:

```bash
export JABLOTRON_CODE=1234
```

Na Windows PowerShellu použijte
`$env:JABLOTRON_CODE = "1234"`. Soubor `config/jablotron.toml` je
záměrně ignorovaný Gitem.

## Příklad

```python
import asyncio
import os

from jablotron100 import ArmMode, JablotronClient, load_config


async def main() -> None:
    config = load_config("config/jablotron.toml")
    async with JablotronClient.from_config(config) as alarm:
        alarm.add_state_listener(
            lambda change: print(change.kind, change.number, change.value)
        )
        await alarm.set_section(1, ArmMode.ARMED_FULL)
        await asyncio.Event().wait()


asyncio.run(main())
```

Autorizační kód neukládejte přímo do zdrojového kódu.

## Převod existující konfigurace Home Assistantu

Jednorázový převod vytvoří TOML bez autorizačního kódu:

```bash
python -m jablotron100 convert-ha \
  /config/.storage/core.config_entries \
  config/jablotron.toml
python -m jablotron100 check-config config/jablotron.toml
```

```python
from jablotron100 import load_home_assistant_config, save_config

config = load_home_assistant_config("/config/.storage/core.config_entries")
save_config(config, "config/jablotron.toml")
```

Převod záměrně nepřenese heslo. Původní importní funkce jej umí načíst pro
zpětnou kompatibilitu, ale nový TOML standardně používá proměnnou prostředí.

## Diagnostika a stav připojení

- `client.central_unit` — model, HW a FW verze;
- `client.diagnostics` — napájení, baterie, BUS, LAN a GSM;
- `client.connected` — aktuální dostupnost USB spojení;
- `client.initialization_complete` — dokončení diagnostické inicializace.

Změny přicházejí přes `add_state_listener()` s typy `connection`,
`central_unit`, `diagnostics`, `section`, `pg_output` a `device`.
Po výpadku USB klient spojení zavře, znovu vyhledá `/dev/hidraw*`, obnoví
autorizaci a zopakuje inicializaci zařízení.

## Směr další práce

1. Ověřit diagnostické pakety a reconnect na skutečné JA-107K.
2. Doplnit zachycené testovací vektory z konkrétní instalace.
3. Přidat názvy sekcí a PG výstupů do TOML.
4. Vytvořit adaptér pro vlastní řídicí aplikaci a volitelně MQTT.
