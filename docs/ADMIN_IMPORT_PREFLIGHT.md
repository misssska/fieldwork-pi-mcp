# Admin-rotation importhiba – diagnosztikai előkészítés

## Kiinduló állapot

A Raspberry Pi izolált tesztkörnyezetében a fotófeltöltési javítás 62 különböző API/biztonsági/migrációs teszten átment. A `tests/test_admin_rotation.py` azonban még a pytest tesztgyűjtése során `ImportError` hibával megállt. Az MCP naplója a potenciálisan érzékeny importsort kitakarta, ezért a hiányzó pontos modulnév **nem igazolt**.

A korábbi izolált forrásmásolatban a `scripts` könyvtárból csak `init_db.py` és `migrate.py` volt látható. Ez felveti a hiányos forrásmásolat lehetőségét, de **nem bizonyítja**, hogy valóban ez okozta az importhibát.

## Új, ténylegesen tesztelt eszköz

Az `updater/admin_import_preflight.py` a `tests/test_admin_rotation.py` Python AST-jét elemzi, és a `scripts.*` importokhoz tartozó fájlok meglétét ellenőrzi a **megadott izolált forrásgyökérben**. Nem importál és nem futtat FieldWork-kódot, nem nyit adatbázist, nem futtat shellt és nem ír fájlt.

Kimenete háromféle:

- `MISSING_LOCAL_IMPORTS`: a forrásban szereplő, egyértelmű `scripts.modul` importhoz nem található fájl vagy csomag.
- `AMBIGUOUS_LOCAL_IMPORTS`: a `from scripts import név` importot nem lehet biztonsággal modulnak minősíteni.
- `STATIC_IMPORT_PATHS_PRESENT`: a vizsgált importútvonalak megtalálhatók. **Ez nem jelenti, hogy az import futáskor sikeres.**

A symlinkes importútvonalakat elutasítja. A diagnosztika nem tartalmaz automatikus telepítést vagy biztonsági ellenőrzés megkerülését.

## Ellenőrzött eredmény

- `tests/test_admin_import_preflight.py`: **12/12 PASS** helyi, izolált Python-környezetben.
- `tests/test_sandbox_db_env.py`: **12/12 PASS**, újrafuttatva ugyanott.
- Összesen **24/24 PASS**, `compileall` PASS.
- A GitHubon a kód és a tesztek a `main` ágon szerepelnek.
- A GitHub Actions státusza **nem igazolt**.
- A Pi MCP új lekérdezései `Session terminated` hibával végződtek, így a diagnosztikát a Pi tényleges forrásmásolatán **még nem futtattam**.

## Következő művelet a Pi MCP kapcsolat helyreállása után

1. Az eredeti `tests/test_admin_rotation.py` importjainak AST-alapú vizsgálata kizárólag az engedélyezett izolált sandboxban.
2. A hiányzó importútvonalak összevetése a stage-forrásmásolat szűrési szabályaival és az eredeti, csak olvasható forrásállománnyal.
3. Ha a másolat hiányos, a stage-forráscsomag előállításának javítása; **nem** az éles teszt kikapcsolása.
4. Teljes tesztcsomag újrafuttatása helyes, izolált tesztadatbázis-konfigurációval.
5. Csak sikeres teljes teszt és kifejezett helyi jóváhagyás után következhet éles MCP-frissítés.

Az éles `/opt/fieldwork`, adatbázis, Docker és a meglévő tunnel változatlan.

## Fájlazonosság ellenőrzése

A helyi tesztekben futtatott Python-fájlokat a GitHubon visszaolvasott tartalmakkal Git blob SHA-1 alapján is összevetettem. **Mind a négy egyezik**:

| Fájl | Git blob SHA-1 |
|---|---|
| `updater/admin_import_preflight.py` | `75b90a5675209a72d7158cf491275c0048b2bc00` |
| `tests/test_admin_import_preflight.py` | `8874783fb138a610530e84c897b0902352194c85` |
| `updater/sandbox_db_env.py` | `417bf552b839ad4bc96f56a3a3409bb0894e5a7a` |
| `tests/test_sandbox_db_env.py` | `a1b365919de10d3d9c2dda8aba3b533082c092c0` |

Ez a négy GitHub-fájl és a 24/24 PASS tesztelt helyi példány közötti **byte-azonosságot** igazolja, de **nem** igazol Pi-n történő futtatást vagy GitHub Actions sikert.

## 2026-10-30 – gyökérok a Pi-n igazolva

Az MCP kapcsolat helyreállt, és az eredeti, változatlan `cfb10c47c1b3413c9adbd50e5c7249ef` sandboxban három új, csak olvasó diagnosztika futott.

1. A `tests/test_admin_rotation.py` pontosan **2** `scripts.*` modult importál, ezekből a sandboxban **1** hiányzik.
2. A hiányzó modul fájlneve **illeszkedik** az MCP forrásmásolatának `operator_support.DENY_FILE` kizárási szabályára; nem maradt olyan hiányzó `scripts.*` modul, amelyre ez ne lenne igaz. A szabály a jelszót, titkot, hitelesítő adatot stb. jelölő fájlneveket **szándékosan kizárja**.
3. A `pytest --collect-only --ignore=tests/test_admin_rotation.py` parancs a helyes tesztadatbázis-környezettel **62 tesztet gyűjtött**. Ezek megegyeznek a korábban két izolált futásban sikeres 29 API + 33 safety/migration teszttel.

**Következtetés:** a hiányzó admin-rotation modul a sandbox biztonsági forráskizárásának **várt következménye**, nem indok a kizárási szabály feloldására. Az általános fotóteszt-sandbox nem alkalmas a jelszókezelési admin-modul tesztelésére. Ezt csak külön, kifejezetten erre tervezett és helyben jóváhagyott biztonságos tesztkörnyezetben lehet elvégezni.

A diagnosztika a Pi-n **nem olvasta, nem másolta és nem futtatta** a kizárt fájlt. Az MCP `fieldwork_read_file` eszköze a tiltott útvonalra `PATH_DENIED` eredményt adott. A három izolált diagnosztika `production_modified=false`, `production_mounts=false` és sikeres takarítás értéket jelzett.

### Kódjavítás és tesztek

Az `updater/admin_import_preflight.py` most `POLICY_EXCLUDED_IMPORTS` állapotot ad, ha kizárólag a fenti szándékos szabály miatt hiányoznak modulok. A tiltott modulneveket nem adja vissza a részletes hiánylistában; csak a számukat. A valódi, nem kizárt hiányok továbbra is `MISSING_LOCAL_IMPORTS` eredményt adnak.

**15/15 admin-preflight teszt és 12/12 sandbox DB teszt PASS**, összesen **27/27 helyi egységteszt**, Python `compileall` PASS. A GitHubon visszaolvasott fájlok Git blob SHA-1 azonosítója egyezik a tesztelt helyi példányokéval.

A `fieldwork_stage_release_status` külön **`FULL_TEST_PASS`** állapotot jelez a staging-folyamathoz. Ez nem azonos a kizárt admin-rotation teszteket is tartalmazó teljes backend-suite PASS eredményével.

**Nem történt éles frissítés, a bootstrap manifestet nem módosítottam, az éles FieldWork és a tunnel változatlan.**
