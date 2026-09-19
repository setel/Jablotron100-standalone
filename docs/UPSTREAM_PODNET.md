# Podklad pro issue v kukulich/home-assistant-jablotron100

Tento text je připravený ke kontrole a ručnímu vložení do
[GitHub Issues](https://github.com/kukulich/home-assistant-jablotron100/issues).
Nebylo odesláno žádné hlášení správci upstreamu.

**Název:** JA-107K: GSM diagnostický podtyp 0x15 a síla signálu

**Text:**

Na JA-107K (HW `MD6112.09.3`, FW `MD12006`) jsem při místním USB/HID
čtení zachytil diagnostickou odpověď GSM modulu číslo 234 s podtypem `0x15`.
Referenční verze integrace jej označuje jako `UNKNOWN_GSM`. Ve dvou
pozorováních odpovídal bajt bezprostředně za hlavičkou podtypu síle signálu:

| Začátek diagnostické hodnoty | Pozorovaná síla signálu |
| --- | --- |
| `d5 32 …` | 50 %; potvrzeno uživatelem |
| `d5 3c …` | 60 %; potvrzeno tabulkou F-Linku |

Úplný paket pro tento typ má tvar `90 0c ea 0a 09 0f 84 d5 XX …`,
kde `XX` je ve vzorcích `32` nebo `3c`. Zbývající bajty záměrně
nezveřejňuji, protože jejich význam ani případná citlivost nejsou ověřeny.

Navrhuji ověřit, zda může integrace z tohoto podtypu číst sílu signálu.
Z dvou vzorků zatím nevyplývá význam dalších polí, stav připojení GSM ani
typ sítě. Je proto důležité nepoužít bez ověření rozložení staršího typu
`0x04` pro tato pole. Anonymizované regresní vzorky a parser jsou v
samostatné knihovně `setel/Jablotron100-standalone`, v
`src/jablotron100/devices.py` a `tests/test_devices.py`.

Poznámka k dalším změnám: samostatná knihovna také opravila ukončování
vlastního asynchronního USB čtení a dekódování bitmapy `0xd8`. Bitmapu
však upstream již dekóduje a původní HA integrace používá jiný transport;
tyto opravy proto nepředkládám jako chyby upstreamu.

Údaje baterie a BUS poskytl F-Link při vzdáleném připojení. Na místním USB
zatím nebyla zachycena odpovídající diagnostická odpověď zařízení 0; z
tohoto pozorování nelze vyvozovat chybu původní HA integrace.
