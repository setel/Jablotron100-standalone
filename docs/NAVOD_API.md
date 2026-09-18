# Návod k jablotron100-standalone a Python API

Stav dokumentace: 19. 9. 2026, pracovní verze projektu 0.3.1 včetně místních
oprav. Popis odpovídá souborům v tomto repozitáři; nemusí odpovídat poslednímu
publikovanému stavu na GitHubu.

## 1. Co spouštět a zda potřebujeme nadřazený skript

Hlavní rozhraní je `JablotronClient`. Vlastní aplikace vytvoří jednoho klienta,
načte konfiguraci, přihlásí odběr změn a podle potřeby volá jeho metody.
Klient už sjednocuje čtení, autorizaci, diagnostiku, heartbeat i reconnect.
Není potřeba postupně spouštět jednotlivé soubory knihovny.

| Součást | Úloha |
| --- | --- |
| `src/jablotron100/client.py` | Veřejný asynchronní klient, stavy, události a ovládání |
| `transport.py` | Linux USB/HID a rozhraní vyměnitelného transportu |
| `protocol.py` | Sestavení příkazů a dělení HID reportů na pakety |
| `devices.py`, `state.py`, `models.py` | Dekódování a datové modely |
| `config.py` | TOML, převod HA konfigurace a import F-Link CSV |
| `communication_log.py` | Logování protokolu a potlačení opakování |
| `python -m jablotron100` | Pomocné příkazy pro konfiguraci |
| `tools/hardware_smoke.py` | Časově omezený test skutečného USB připojení |

Nadřazená aplikace by dávala smysl pro vlastní automatizace, MQTT, webové
rozhraní nebo provoz jako služba. Má používat tento klient a obsahovat jen
aplikační logiku. Taková služba ani HTTP API zatím součástí projektu nejsou.
Pro jeden USB port používejte jednoho vlastníka spojení; více částí aplikace
může sdílet jeho klienta v jednom asyncio event loopu. HA nebo F-Link přes
stejné USB nesmí zařízení současně obsluhovat.

## 2. Prostředí na tomto RPi

Požadovaný Python je 3.11 nebo novější. Ověřeno bylo RPi5 / Python 3.13.5.
USB transport používá linuxový `/dev/hidraw*`; běh tohoto transportu na
Windows není implementován. Knihovna nemá běhovou závislost na HA.

Následující nastavení spouští přímo zdrojové soubory bez instalace do
sdíleného virtuálního prostředí:

```bash
cd /home/emil/prj_jablotron100-standalone
export PYTHONPATH="$PWD/src"
/home/emil/python3env/bin/python -m jablotron100 --help
/home/emil/python3env/bin/python -m unittest discover -s tests
```

V dalších příkazech se předpokládá tento pracovní adresář a `PYTHONPATH`.
Změny prostředí platí pro daný shell a jeho potomky, nikoli pro jiné SSH
relace nebo již spuštěné procesy.

## 3. Konfigurace a autorizační kód

Vzor: [jablotron.example.toml](../config/jablotron.example.toml).
Místní konfigurace: `config/jablotron.toml`, ignorovaná Gitem.

```toml
[connection]
port = "auto"
code_env = "JABLOTRON_CODE"

[system]
number_of_devices = 120
number_of_pg_outputs = 32

[[devices]]
number = 10
type = "door_opening_detector"
name = "Hlavní dveře"
model = "JA-118M"

[[sections]]
number = 1
name = "Dům"

[[pg_outputs]]
number = 2
name = "Výstup 2"
```

Čísla odpovídají pozicím ústředny; zařízení jsou 1–230, sekce 1–15 a PG
1–128. Ústředna má pozici 0 a nepřidává se jako běžná periferie.
`number_of_devices` je rozsah pozic, nikoli počet skutečně osazených čidel.
Neuvedené pozice se doplní jako `empty`. Pozice `empty` a `other` klient
nezpracovává jako běžná zařízení. Funkční `type` není totéž co hardwarový
`model`: vstupy stejného JA-118M mohou představovat různá čidla.

Kód můžete zadat bez vypsání a uložení jeho hodnoty do historie shellu:

```bash
read -r -s -p 'Autorizační kód: ' JABLOTRON_CODE
echo
export JABLOTRON_CODE
```

Alternativou je `code = "..."` v `[connection]` místního TOML. Pořadí přednosti
je explicitní `JablotronClient.from_config(config, code=...)`, pak neprázdná
proměnná určená `code_env`, nakonec `connection.code`. Kód nepatří do příkladů
ani do sdílených logů. Pokud se používá prefix, zachovejte formát s `*`.

```bash
/home/emil/python3env/bin/python -m jablotron100 check-config config/jablotron.toml
```

Kontrola konfigurace neotvírá USB, neověřuje platnost kódu vůči ústředně a
nepotvrzuje dostupnost hardwaru. Položky `require_code_to_arm`,
`require_code_to_disarm` a `partially_arming_mode` se v konfiguraci zachovávají,
ale aktuální `JablotronClient` z nich nevytváří oprávnění ani ochranu volání.
Režim sekce předává aplikace explicitně přes `ArmMode`; oprávnění příkazů
vyhodnocuje ústředna podle použitého kódu.

## 4. První test skutečného připojení

Po zastavení ostatních klientů stejného USB:

```bash
/home/emil/python3env/bin/python tools/hardware_smoke.py \
  --config config/jablotron.toml --seconds 45 --log logs/communication.log
```

Test načte identitu, sekce, PG stavy a dostupné diagnostické hodnoty.
Neovládá PG ani sekce. I čtení zahrnuje odesílání autorizace, dotazů,
heartbeat a zapnutí/vypnutí diagnostiky zařízení.

`--seconds` musí být větší než 0 a nejvýše 300. Pro ruční ověření odpojení
a připojení USB přidejte `--reconnect`; test bez této volby obnovu spojení
neprovádí. Výchozí `--heartbeat` je 0,5 s. Tento nástroj není dlouhodobá služba.
Do stejného souboru můžete průběžně nahlížet v druhém terminálu:

```bash
tail -f logs/communication.log
```

Nulový návratový kód znamená splnění základních kontrol testu, nikoli
dostupnost každé diagnostické hodnoty. Neznámé údaje mohou zůstat `None`.

## 5. Úplný příklad: sledování bez ovládání

Kód lze uložit například jako `monitor.py` v kořeni tohoto repozitáře a
spustit pomocí `/home/emil/python3env/bin/python monitor.py`.

```python
import asyncio
from pathlib import Path

from jablotron100 import (
    CommunicationLog, HidrawTransport, JablotronClient,
    LoggedTransport, load_config,
)


async def main():
    config = load_config("config/jablotron.toml")
    Path("logs").mkdir(exist_ok=True)
    with CommunicationLog("logs/monitor.log") as log:
        transport = LoggedTransport(HidrawTransport(config.serial_port), log)
        client = JablotronClient.from_config(
            config, transport=transport, auto_reconnect=True,
        )

        def changed(change):
            if change.kind == "connection":
                print("Spojení:", change.value)
            elif change.kind == "device":
                device = change.value
                print("Zařízení:", device.number, device.name, device.active)
            elif change.kind == "pg_output":
                print("PG:", change.number, change.value)
            elif change.kind == "section":
                print("Sekce:", change.number, change.value.alarm_state.value)

        unsubscribe = client.add_state_listener(changed)
        try:
            await client.start()
            async with asyncio.timeout(45):
                while not (
                    client.connected and client.initialization_complete
                    and client.central_unit.model and client.sections
                ):
                    await asyncio.sleep(0.1)
            print("Ústředna:", client.central_unit)
            print("GSM signál:", client.diagnostics.gsm_signal_strength)
            await asyncio.Event().wait()  # ukončení Ctrl+C
        finally:
            unsubscribe()
            await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```

Odběr se registruje před `start()`, aby zachytil i první změny. Lze použít
i `async with client`, který při běžném opuštění kontextu volá `close()`.
Explicitní `try/finally` v příkladu uklidí klienta i při chybě startu.

## 6. Životní cyklus a metody

`JablotronClient.from_config(config, *, code=None, transport=None,
keepalive_interval=0.5, auto_reconnect=True, reconnect_delay=1.0,
reconnect_max_delay=30.0)` vytvoří klienta, ale ještě neotvírá spojení.
Vlastní transport předaný přes `transport=` nahrazuje výchozí USB transport.

| Metoda | Co dělá a na co čeká |
| --- | --- |
| `await start()` | Otevře spojení a zahájí čtení a inicializaci. Nečeká na všechna data. Při povoleném reconnectu může návrat znamenat i naplánované opakování neúspěšného startu. |
| `await close()` | Zruší úlohy klienta a zavře transport. Nevypíná automaticky PG a nemění sekce. |
| `await refresh()` | Odešle dotaz na stavy sekcí a PG. Nečeká na jejich odpověď. |
| `await refresh_diagnostics(timeout=2.0)` | Postupně vyžádá diagnostiku; timeout je pro jednotlivé čekání, nikoli celý průchod. Timeout zařízení se běžně nezvedá jako výjimka. |
| `await initialize_devices()` | Opakuje inicializační požadavky; normálně volá klient sám při spojení/reconnectu. |
| `await set_pg_output(pg_output, enabled)` | Odešle nastavení PG. Návrat není potvrzením změny od ústředny. |
| `await set_section(section, mode, code=None)` | Odešle režim sekce, po prodlevě vyžádá stav. Případný jiný kód použije dočasně; metoda sama nezaručuje potvrzený výsledek. |
| `add_state_listener(callback)` | Přihlásí odběr změn modelů; vrací funkci pro odhlášení. |
| `add_packet_listener(callback)` | Přihlásí odběr zpracovaných příchozích paketů; vrací funkci pro odhlášení. |

Diagnostiku nespouštějte souběžně s probíhající diagnostickou inicializací
nebo jiným diagnostickým průchodem. Pro běžné používání nevolejte privátní
metody začínající `_` ani nesestavujte vlastní pakety.

## 7. Stavy a jejich význam

| Vlastnost | Význam |
| --- | --- |
| `running` | Klient má spuštěný životní cyklus; může právě čekat na reconnect. |
| `connected` | Transportní spojení je otevřené; není to potvrzení oprávnění k ovládání. |
| `initialization_complete` | Inicializační úloha skončila bez výjimky; i zařízení bez odpovědi mohlo pouze vyčerpat timeout. |
| `central_unit` | `model`, `hardware_version`, `firmware_version` |
| `sections` | Slovník číslo → `SectionState`; čitelný stav v `alarm_state.value` |
| `pg_outputs` | Slovník číslo → `bool`; chybějící klíč znamená dosud nenačtený stav |
| `devices` | Slovník číslo → `DeviceSnapshot`; metadata mohou existovat už před příjmem dat |
| `diagnostics` | `CentralUnitDiagnostics` s dostupnými diagnostickými údaji |
| `section_names`, `pg_output_names` | Názvy z konfigurace; chybějící název není chyba komunikace |
| `device_definitions`, `section_definitions`, `pg_output_definitions` | Konfigurační definice, nikoli živé stavy |

`DeviceSnapshot` obsahuje například `number`, `name`, `model`, `device_type`,
`active`, `connection`, `signal_strength`, `battery_level`, `battery_ok`,
`temperature`, `problem`, `sabotage`, `last_event` a `pulses`.
`None` znamená neznámé/neposkytnuté; není to totéž co `False` nebo nula.
Výchozí `problem=False` a `sabotage=False` nejsou důkazem přijatého potvrzení
bezporuchovosti každého zařízení.

Aktivita představuje logický stav vstupu, nikoli automaticky alarm. Například
čidlo „vrata nejsou plně otevřena“ může být aktivní u zavřených vrat.
Po odpojení USB zůstávají v modelech poslední hodnoty. Aplikace má zvlášť
zobrazovat `connected`; knihovna zatím neposkytuje stáří každé hodnoty.
Modely stavu jsou neměnné datové objekty; změna kopie slovníku nestaví PG.

Diagnostika nabízí napájení, stav a napětí baterie, LAN/IP/DHCP, GSM a
`buses`. Jednotlivá sběrnice má `number`, `voltage` a `current_ma`.
`devices_loss` je historický kompatibilní název téhož údaje o proudu;
`dataclasses.asdict()` zatím používá právě uložený název `devices_loss`.
Na testované JA-107K jsou napájení, baterie a BUS stále neznámé. GSM signál
je ověřen porovnáním hodnot 50/60 %, stav připojení GSM a druh sítě nikoli.

## 8. Callbacky

`StateChange` má `kind`, `number` a `value`:

| `kind` | `number` | `value` |
| --- | --- | --- |
| `connection` | 0 | `bool` |
| `central_unit` | 0 | `CentralUnitInfo` |
| `diagnostics` | 0 | `CentralUnitDiagnostics` |
| `section` | číslo sekce | `SectionState` |
| `pg_output` | číslo PG | `bool` |
| `device` | číslo zařízení | `DeviceSnapshot` |

Callback může být obyčejná nebo asynchronní funkce. Klient čeká na její
dokončení, proto v callbacku neprovádějte dlouhé operace ani nečekejte na
další paket stejného klienta. Událost raději předejte do vlastní
`asyncio.Queue`. Výjimky callbacků klient loguje. Odběratelé nedostávají
automaticky celý dosavadní stav při přihlášení.

`PacketEvent` nabízí `packet: bytes`, `packet_type: int` a
`received_at: float` z monotónních hodin, nikoli datum a čas. Tento odběr
nezahrnuje odchozí pakety. Pro kompletní komunikaci použijte `LoggedTransport`;
ten zachytí příchozí data ještě před dekódováním klientem.

## 9. Ovládání PG a ověření výsledku

Následující funkce je určená pro již spuštěného a inicializovaného klienta.
Její zavolání fyzicky ovládá zvolený výstup. PG 2 bylo při ručním testu
ověřeno zapnutím na 30 sekund a následným vypnutím, včetně potvrzení uživatele.

```python
import asyncio


async def pulse_pg(client, number=2, seconds=30):
    if not client.connected or number not in client.pg_outputs:
        raise RuntimeError("PG nemá načtený stav nebo chybí spojení")
    reports = asyncio.Queue()

    def received(event):
        if event.packet_type == 0x50:
            reports.put_nowait(client.pg_outputs.get(number))

    async def confirm(expected):
        while not reports.empty():
            reports.get_nowait()
        await client.refresh()
        async with asyncio.timeout(5):
            while await reports.get() is not expected:
                pass

    unsubscribe = client.add_packet_listener(received)
    try:
        try:
            await client.set_pg_output(number, True)
            deadline = asyncio.get_running_loop().time() + seconds
            try:
                await confirm(True)
            except TimeoutError:
                print("Zapnutí nebylo potvrzeno; vypnutí zůstává naplánované")
            await asyncio.sleep(max(0, deadline - asyncio.get_running_loop().time()))
        finally:
            await client.set_pg_output(number, False)
            await confirm(False)
    finally:
        unsubscribe()
```

Použití v hlavní asynchronní funkci: `await pulse_pg(client, 2, 30)`.
Tuto funkci nevolejte přímo uvnitř paketového/stavového callbacku, protože
čeká na další příjem. Nejde o časovač v ústředně: při ztrátě napájení RPi,
ukončení procesu silou nebo nedostupném USB nelze následné vypnutí zaručit.
Chybu vypnutí/ověření musí aplikace zpracovat jako nepotvrzený výsledek.

Pro samotné přepnutí použijte `await client.set_pg_output(2, True)` nebo
`await client.set_pg_output(2, False)` a ověřte nový stav stejným způsobem.
Předchozí hodnota ve slovníku není potvrzení právě odeslaného příkazu.

## 10. Ovládání sekcí

Volání `await client.set_section(cislo, rezim)` fyzicky mění stav sekce.
`rezim` je `ArmMode.ARMED_FULL`, `ArmMode.ARMED_PARTIAL` nebo
`ArmMode.DISARMED`, importované z `jablotron100`. Volitelným `code=` lze
použít jiný kód. Výsledek sledujte v nových paketech/stavech sekcí a počítejte
se zpožděním či odmítnutím podle oprávnění a stavu ústředny. Tyto operace
nebyly při dosavadních hardwarových testech provedeny.

## 11. Logování

`CommunicationLog(path, repeat_seconds=60, max_bytes=2_000_000,
backup_count=3)` spravuje souborový log. Jeho nadřazený adresář musí existovat.
`LoggedTransport(HidrawTransport(config.serial_port), log)` předáte klientovi
jako `transport=`. Log držte otevřený po celou dobu života klienta.

Log vypisuje čas, směr, hex a známý význam. Nezměněné pakety potlačuje po
směru/typu/zařízení a později vypíše počet. Rozdílné neanonymizované pakety
zapisuje i tehdy, když se liší jen dosud neznámým polem. Souhrn opakování
vzniká při příštím paketu po intervalu, změně nebo uzavření, ne samostatným
časovačem. `repeat_seconds=0` vypne potlačování, nikoli anonymizaci.

Všechny pakety `0x80` mají skrytý obsah, tedy nejen kódy, ale i UI/PG ovládání.
Proto mohou být různé takové příkazy sloučené; pro audit operace použijte
`log.note("PG 2: požaduji zapnutí")` a zapište zvlášť potvrzený příchozí stav.
Do `note()` nevkládejte přístupové kódy, text se dále neanonymizuje.
Ostatní pakety mohou obsahovat IP a stav instalace. `logs/` je ignorovaný
Gitem. Provozní chyby klienta používají samostatně standardní Python logging.

## 12. Konfigurační příkazy a chybové stavy

Existující CLI podporuje `check-config`, `convert-ha`, `merge-flink` a
`import-flink`. Podrobnou syntaxi zobrazí `python -m jablotron100 <příkaz>
--help`. Import není automatické zjištění osazení z ústředny; jde o převod
uložených údajů. `save_config()` běžně nezapisuje autorizační kód do výstupu.
Příklady převodů jsou v [README](../README.md#názvy-periferií-z-f-linku).

| Projev | Význam / další krok |
| --- | --- |
| `ModuleNotFoundError: jablotron100` | Nastavit `PYTHONPATH` podle části 2. |
| `ConfigurationError` | Chyba konfigurace nebo chybějící autorizační kód. |
| `SerialPortNotDetected` | USB nebylo nalezeno; prověřit připojení a `port`. |
| `PermissionError`, jiný `OSError` | Oprávnění zařízení, odpojení nebo chyba OS/USB. |
| `TransportClosed` | Operace nad zavřeným transportem. |
| `ProtocolError` | Neplatný paket či parametr. V čtecí úloze může vést k reconnectu. |
| `TimeoutError` z příkladu | Aplikace nedostala požadované potvrzení včas. |
| Stav je `None` | Údaj nebyl dodán/dekódován; nevydávat za nulu či poruchu. |

`JablotronError` je základ knihovních výjimek, ale OS chyby a aplikační
`TimeoutError` pod něj nespadají. Při `auto_reconnect=True` se chyby spojení
mohou projevit logem a stavem klienta, nikoli výjimkou v hlavní úloze.
Metody ovládání při odpojení neukládají příkazy do fronty pro budoucí odeslání.

Přehled oprav, rozdílů proti HA a otevřených bodů je v textovém souboru
[CHYBY_A_ROZDILY_HA.txt](CHYBY_A_ROZDILY_HA.txt).
