# Jablotron 100+ standalone

Samostatná Python knihovna pro lokální komunikaci s ústřednami Jablotron
100+, zejména JA-107K. Nevyžaduje Home Assistant.

Projekt vzniká oddělením protokolové části z integrace
[`kukulich/home-assistant-jablotron100`](https://github.com/kukulich/home-assistant-jablotron100).
Původní integrace i tento odvozený kód používají licenci MIT. Podrobnosti jsou
v `NOTICE.md`.

## Dokumentace

- [Český návod a reference Python API](docs/NAVOD_API.md): spuštění na RPi,
  konfigurace, příklady, stavy, callbacky, ovládání a logování.
- [Zjištěné chyby a rozdíly proti HA integraci](docs/CHYBY_A_ROZDILY_HA.txt):
  opravy, otevřené body, ověřené chování a odkazy na místní záznamy.
- [Podklad pro hlášení upstreamu](docs/UPSTREAM_PODNET.md):
  anonymizované nové zjištění o GSM diagnostice JA-107K.

Jednotícím rozhraním knihovny je `JablotronClient`; vlastní aplikace používá
jeho metody. Pomocné konfigurační a testovací skripty nejsou nutné pro její
běh. Další nadřazená služba je potřebná až pro konkrétní automatizace či MQTT.

## Aktuální stav

Verze 0.3.1 obsahuje:

- automatické vyhledání USB HID zařízení `16D6:0008`;
- transport přes `/dev/hidraw*` s vyměnitelným testovacím transportem;
- dělení 64b HID reportů na protokolové pakety;
- vytváření autorizačních, keepalive a ovládacích paketů;
- asynchronního klienta s odběrem příchozích paketů;
- stavové modely a callbacky pro sekce a PG výstupy;
- samostatnou, ručně editovatelnou TOML konfiguraci;
- bezpečný převod z Home Assistant `.storage/core.config_entries`;
- import názvů a hardwarových modelů periferií z F-Link CSV;
- import názvů sekcí a PG výstupů z F-Link CSV;
- dekódování periferií, baterií, signálu, teplot, napětí sirén a pulzů;
- identifikaci modelu, HW a FW ústředny;
- diagnostiku napájení, baterie, BUS napětí a proudu podle upstreamu;
- stav LAN, DHCP, IP adresu, stav GSM a sílu GSM signálu;
- úplnou inicializační sekvenci nakonfigurovaných periferií;
- automatický reconnect USB s exponenciální prodlevou;
- příkazy pro zastřežení, částečné zastřežení, odstřežení a PG výstupy;
- jednotkové testy bez připojené ústředny.

API je stále vývojové a nemá nahrazovat certifikované ovládání
zabezpečovacího systému. Diagnostické dekódování vychází z upstream integrace;
rozsah ověření na skutečné JA-107K a zbývající omezení jsou uvedeny níže.

## Instalace pro vývoj

Na tomto RPi je připravené prostředí `/home/emil/python3env`; postup bez
další instalace je v [návodu](docs/NAVOD_API.md#2-prostředí-na-tomto-rpi).
Obecná instalace do nového prostředí:

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
model = "JA-110P"

[[sections]]
number = 1
name = "Dům"

[[pg_outputs]]
number = 1
name = "Vrata"
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

from jablotron100 import JablotronClient, load_config


async def main() -> None:
    config = load_config("config/jablotron.toml")
    alarm = JablotronClient.from_config(config)
    alarm.add_state_listener(
        lambda change: print(change.kind, change.number, change.value)
    )
    try:
        await alarm.start()
        await asyncio.Event().wait()
    finally:
        await alarm.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```

Autorizační kód neukládejte přímo do zdrojového kódu.
Tento příklad sleduje změny; neovládá sekce ani PG. Příklady ovládání
a ověření výsledku jsou v [návodu API](docs/NAVOD_API.md#9-ovládání-pg-a-ověření-výsledku).

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

## Názvy periferií z F-Linku

F-Link umí exportovat tabulku periferií do středníkem odděleného CSV.
Knihovna podporuje UTF-8 i běžný export Windows-1250. Názvy a hardwarové
modely lze přidat do již vytvořené TOML konfigurace:

```bash
python -m jablotron100 merge-flink \
  config/jablotron.toml \
  config/Periferie.csv \
  config/jablotron.toml \
  --sections config/Sekce.csv \
  --pg-outputs config/PGvystupy.csv
```

Funkční `type` zůstává zachovaný. To je důležité například u JA-118M,
jehož jednotlivé vstupy mohou představovat dveře, okno nebo garážová vrata.
Sériová čísla se standardně nepřenášejí. Volba
`--include-serial-numbers` je uloží, pokud je aplikace potřebuje.

Uživatel bez Home Assistantu může vytvořit výchozí konfiguraci přímo:

```bash
python -m jablotron100 import-flink \
  config/Periferie.csv \
  config/jablotron.toml \
  --number-of-pg-outputs 32
```

U nejednoznačných modelů nastaví importér `type = "custom"`; uživatel jej
pak upraví podle skutečného zapojení. Export ODS vytvořený kopírováním přes
schránku není pro import potřeba.

Export `Uzivatele.csv` obsahuje telefonní čísla, přístupové kódy a karty.
Knihovna jej z bezpečnostních důvodů neimportuje a Git jej ignoruje.

## Diagnostika a stav připojení

- `client.central_unit` — model, HW a FW verze;
- `client.diagnostics` — napájení, baterie, BUS, LAN a GSM;
- `client.connected` — aktuální dostupnost USB spojení;
- `client.initialization_complete` — dokončení diagnostické inicializace.
- `client.devices[number].name` — název z F-Linku;
- `client.devices[number].model` — hardwarový model periferie.
- `client.section_names` — slovník čísel a názvů sekcí;
- `client.pg_output_names` — slovník čísel a názvů PG výstupů.

Změny přicházejí přes `add_state_listener()` s typy `connection`,
`central_unit`, `diagnostics`, `section`, `pg_output` a `device`.
Po výpadku USB klient spojení zavře, znovu vyhledá `/dev/hidraw*`, obnoví
autorizaci a zopakuje inicializaci zařízení.

## Test skutečného připojení

Nejprve zastavte Home Assistant nebo jiného klienta stejného USB zařízení.
V `config/jablotron.toml` nastavte připojení a zpřístupněte autorizační kód
procesu testu (například přes `JABLOTRON_CODE` ve stejném shellu).
Z kořene repozitáře spusťte:

```bash
PYTHONPATH=src timeout --signal=TERM --kill-after=5s 60s \
  /home/emil/python3env/bin/python tools/hardware_smoke.py --seconds 45
```

Jde o ruční hardwarový test, nikoli součást jednotkových testů. Odesílá
autorizaci, dotazy na stav, heartbeat a zapnutí/vypnutí diagnostiky periferií;
neovládá sekce ani PG výstupy. Vypíše identifikaci ústředny, diagnostiku,
stavy sekcí a počty přijatých paketů a periferií. Nevypisuje autorizační kód,
sériová čísla, názvy periferií ani LAN IP adresu. Automatické opakování
připojení je při testu vypnuté. `initialization_complete` znamená dokončení
inicializační úlohy, nikoli potvrzení odpovědi od každé periferie.
Vnější `timeout` omezuje také případné zablokování při ukončování USB čtení.
Test skončí chybou, pokud nedokončí inicializaci, ztratí spojení nebo chybí
model, sekce, PG stavy či status některé nakonfigurované periferie.
Chybějící jednotlivé diagnostické hodnoty samotné chybu testu nezpůsobí.

## Čitelný log komunikace

```bash
PYTHONPATH=src /home/emil/python3env/bin/python tools/hardware_smoke.py \
  --seconds 300 --log logs/communication.log --reconnect
```

Volba `--reconnect` umožní během tohoto ručního testu obnovit spojení po
odpojení a opětovném připojení USB. Bez ní test automaticky nepřipojuje znovu.
Před testem zastavte HA; po skončení testu jej můžete znovu spustit.

Log obsahuje čas, směr, hexadecimální paket a jeho známý význam, například:

```text
ODESÍLÁM hex 52 01 02 — Heartbeat
ODESÍLÁM hex 96 03 00 09 00 — Diagnostika zařízení 0: dotaz na hodnoty
PŘIJÍMÁM hex d8 03 00 00 04 — Aktivní zařízení: [10]; ostatní přítomné bity neaktivní
ODESÍLÁM: potlačeno 119 stejných opakování; hex 52 01 02
```

Stejné pakety se potlačují samostatně podle směru, typu a zařízení; změna
A → B → A zůstává viditelná. Souhrn opakování se vypíše při dalším paketu
po 60 sekundách, změně hodnoty nebo zavření spojení. Log se rotuje po
2 MB a uchovává tři zálohy. Neznámé formáty jsou označené jako nedekódované.
Všechny UI pakety `0x80` mají skrytý obsah, aby se nezapsal přístupový kód.
Ostatní pakety mohou obsahovat IP adresy a stavy instalace; adresář `logs/`
je ignorovaný Gitem. Log zachycuje úspěšně odeslaná data, nikoli potvrzení,
že ústředna požadavek provedla.

Vlastní aplikace může použít stejný transportní obal:

```python
from jablotron100 import CommunicationLog, HidrawTransport, LoggedTransport

with CommunicationLog("communication.log") as log:
    transport = LoggedTransport(HidrawTransport(config.serial_port), log)
    async with JablotronClient.from_config(config, transport=transport) as client:
        await asyncio.sleep(60)
```

Výchozí heartbeat je nyní 0,5 s podle upstream integrace, s obnovením
autorizace a odběru událostí po 30 s. Obnovení autorizace se vynechá během
aktivního alarmu nebo vstupního zpoždění. Knihovna zpracovává i souhrnné
stavy periferií `0xd8`; pozice chybějící v paketu nepovažuje za neaktivní.

### Ověření na RPi5 dne 18. 9. 2026

Na Pythonu 3.13.5 přes `/dev/hidraw1` byla ověřena JA-107K
(HW `MD6112.09.3`, FW `MD12006`). Během 45sekundového testu se načetly
3 sekce, 32 PG stavů a status všech 41 nakonfigurovaných periferií.
Po opravě zrušitelného USB čtení klient i proces řádně skončily.

Diagnostické odpovědi přišly od modulů 233 a 234 a sedmi periferií,
ale nikoli od zařízení 0 (ústředny). Napájení, baterie a BUS diagnostika
proto zůstaly neznámé; stav GSM také nebyl dekódován. Nejde o potvrzení
poruchy těchto částí. Příčinu je potřeba dále ověřit. Test neověřoval
ovládání, reakce na fyzické změny čidel ani reconnect po vytažení USB.

### Navazující ověření 19. 9. 2026

Po sjednocení heartbeat s upstreamem a doplnění parseru `0xd8` bylo
ověřeno otevření hlavních dveří (zařízení 10) a jejich zavření. Zavření
ohlásil paket `55 08 44 92 80 02 d0 74 80 2e` a potvrdil následující
souhrnný stav `0xd8`. Tyto skutečné pakety jsou součástí regresních testů.
Přicházely také změny pohybových čidel.
Při fyzickém odpojení a opětovném připojení USB klient zaznamenal výpadek,
opakoval detekci, obnovil autorizaci a inicializaci a znovu přijímal změny
čidel. Reconnect je tedy ověřený i na skutečném zařízení.
Ověřeno bylo také zapnutí PG 2 na 30 sekund a následné vypnutí; oba stavy
potvrdila ústředna i uživatel. Záznam je v `logs/pg2-control.log`.

GSM modul 234 odpovídá diagnostickým podtypem `0x15`, který referenční
upstream označuje jako neznámý. V zachycené odpovědi začínající `d5 32 …`
druhý bajt odpovídá uživatelem potvrzenému signálu 50 %. Knihovna nyní čte
toto pole jako sílu signálu; jde zatím o porovnání dvou hodnot, nikoli
úplně ověřený popis protokolu. Stav GSM spojení z tohoto podtypu zůstává
neznámý. Opraveno bylo také chybné vyhodnocení obecného statusu modulu jako
signálu 0 %. Ostatní neznámé podtypy log uvádí v `unknown_info_types`.
V závěrečném hardwarovém testu bylo ze stejného pole načteno 60 %;
uživatelem následně dodaná tabulka potvrdila i tuto hodnotu.

Napájení, baterie a BUS zůstávají neznámé: od zařízení 0 nepřišla
diagnostická odpověď během pětiminutového monitorování ani při samostatném
opakování dotazu s prodlevou 1 s po zapnutí diagnostiky a čekáním 10 s.
Bez odpovědi nelze potvrdit, zda je příčinou oprávnění, jiná inicializační
sekvence nebo odlišnost firmwaru. Je třeba porovnat funkční čtení těchto
hodnot v HA/F-Linku; neznámé hodnoty nejsou nahrazeny nulami.

Referenční tabulka dodaná uživatelem 19. 9. 2026 pochází z F-Linku připojeného
vzdáleně, nikoli z našeho USB čtení ani z HA. Obsahuje:

| Údaj | Referenční hodnota | Porovnání s USB záznamem |
| --- | --- | --- |
| Napětí baterie ústředny | 13,2 V / 12,9 V | Odpovídající diagnostická odpověď chybí |
| Sběrnice 1 | 13,1 V / 42 mA | Odpovídající diagnostická odpověď chybí |
| Sběrnice 2 | 13,1 V / 68 mA | Odpovídající diagnostická odpověď chybí |
| Sběrnice 3 | 13,1 V / 0 mA | Odpovídající diagnostická odpověď chybí |
| GSM | 60 %, 2G | Signál souhlasí; typ sítě dosud nedekódujeme |
| Baterie periferií 30 / 31 / 32 | 90 % / 100 % / 90 % | Souhlasí |

Pořadí dvou napětí baterie zatím nepřiřazujeme k pojmům klid/zátěž bez
ověření významu příslušných polí. Upstream používá pro historicky pojmenované
pole `devices_loss` jednotku mA a typ proudového senzoru. Proto knihovna
nabízí alias `BusDiagnostics.current_ma`; starý atribut zůstává kvůli
kompatibilitě. Jednotku potvrzuje [definice senzoru v upstreamu](https://github.com/kukulich/home-assistant-jablotron100/blob/master/custom_components/jablotron100/sensor.py).
Skutečné dekódování BUS na této JA-107K dosud není ověřené.
Údaj 0,0 V u periferií zatím nelze rozlišit od nevyplněné či
nedostupné hodnoty a není důvodem k vyhodnocení poruchy.

Další pokus s diagnostikou zařízení 0 ponechanou zapnutou po 60 s,
třemi dotazy na diagnostiku a status během tohoto okna také neposkytl
odpověď s hodnotami napájení. Průběh je v místním ignorovaném souboru
`logs/central-long.log`. Diagnostika byla na konci opět vypnuta a klient
řádně ukončen. Další krok vyžaduje porovnání se sekvencí komunikace programu,
který tyto hodnoty skutečně načetl; není doloženo, že problém způsobují
oprávnění či časování.

## Směr další práce

1. Získat úspěšnou USB sekvenci F-Linku pro napájení, baterii a BUS.
2. Ověřit zbývající pole novější GSM diagnostiky.
3. Rozšiřovat regresní vzorky a ověření chybových stavů.
4. Podle potřeby vytvořit adaptér pro vlastní aplikaci a MQTT.
