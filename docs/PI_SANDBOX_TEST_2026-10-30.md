# Raspberry Pi – izolált fotóregresszió, 2026-10-30

## Élő ellenőrzés

- MCP: `v0.6.1`, elérhető
- `fieldwork_stage_capabilities`: lokálisan jóváhagyott staging képességek, **nincs host shell vagy production deploy**
- Fotójavítási javaslat: `cfb10c47c1b3413c9adbd50e5c7249ef`
- `fieldwork_sandbox_runtime_status` induláskor: `NOT_RUN`, image/resource preflight PASS
- `fieldwork_sandbox_runtime_test(suite=photo)`: **RUNTIME_TEST_FAIL**, kb. 24,5 s

A teszt még a pytest gyűjtésekor, a `server/tests/conftest.py` által hívott `configure_test_database()` védelmi ellenőrzésénél állt meg. Ez **nem bizonyít fotófeltöltési kódhibát**: a regresszió nem jutott el a tesztesetekig.

## Izolált diagnosztika

Az engedélyezett `fieldwork_sandbox_command` eszközzel, külön eldobható Docker-konténerben ellenőriztem:

- `FIELDWORK_TESTING=1` aktív.
- A `DATABASE_URL` és `TEST_DATABASE_URL` változó létezik, és a vizsgált URL hostja `test-db`, az adatbázis neve `fieldwork_test`.
- A `FIELDWORK_TEST_DATABASE_URL` kezdetben **hiányzott**.
- Az utóbbi változó izolált tesztfutásban történő átadásakor a védelmi ellenőrzés egy **további feltételnél** utasította el a futást. A napló érzékeny sorait az MCP helyesen kitakarta.
- Az ellenőrzést nem kerültem meg, és nem lazítottam az adatbázis-védelmi feltételeken.

## Következtetés és következő lépés

A jelenlegi tesztakadály a sandbox teszt-adatbázis környezetének és a `test_database_guard.py` elvárásainak eltérése. A pontos második feltételt forrás- és konfigurációs felülvizsgálattal, **a védelmi ellenőrzés gyengítése nélkül** kell feloldani. A fotófeltöltési javítás eredménye továbbra is **NEM IGAZOLT**.

A teszt és a diagnosztikai parancsok minden alkalommal `production_modified=false`, `production_mounts=false` értéket jeleztek; a tesztkonténerek, ideiglenes adatbázis és belső hálózat takarítása sikeres. Az éles `/opt/fieldwork`, adatbázis és Docker-konténerek nem változtak.

## Frissítőrendszer

A GitHubon új `updater/local_approval_lab.py` prototípus és 17 offline teszt található. **Nincs helyi tokenkiállító, telepítő, aktiválási jog vagy Pi-n telepített új modul.** A GitHub Actions tesztfutásának eredménye még nem igazolt.
