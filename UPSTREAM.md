# Synchronizace s upstream integrací

Zdroj protokolové logiky:

- repozitář: https://github.com/kukulich/home-assistant-jablotron100
- uživatelova výchozí verze: tag `3.29.0`, commit
  `7593480e48bafaa19d05501f1fd916230bf12f83`
- naposledy porovnaná verze: `3.33.5`, commit
  `4b1c30d5105ec041e5343d94a049666702454750`
- datum porovnání: 2026-09-17

Knihovna přebírá paketové konstanty a dekódovací algoritmy, nikoli třídy
Home Assistantu. Testovací vektory pocházejí z upstream testů a zachycených
paketů.

Zjištění z hardwarových testů 18.–19. 9. 2026, opravy standalone přenosu
a záměrné odchylky jsou vedené v
[docs/CHYBY_A_ROZDILY_HA.txt](docs/CHYBY_A_ROZDILY_HA.txt).
Tento přehled nenahrazuje úplný diff proti nové verzi upstreamu.

Při další synchronizaci porovnat především:

- `custom_components/jablotron100/const.py`
- `custom_components/jablotron100/jablotron.py`
- `tests/test_device_status_packets.py`
- `tests/test_device_state_packets.py`
- `tests/test_device_info_packets.py`

Změny po verzi 3.29.0 rozšířily interpretaci událostí a příznaků zařízení,
ale základní formát paketů, číslování zařízení a stavové příkazy zůstaly
kompatibilní. Samostatná knihovna používá novější, přesnější interpretaci a
zachovává kompatibilitu se zachycenými pakety verze 3.29.0.
