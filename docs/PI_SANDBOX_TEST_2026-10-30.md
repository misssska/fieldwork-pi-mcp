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


## Folytatás – adatbázis-környezet helyreállítása és sikeres tesztek

**Gyökérok megerősítve:** az eredeti sandbox-futtató a `DATABASE_URL` és `TEST_DATABASE_URL` változóknak **azonos** tesztadatbázis-URL-t adott, de nem állította be a `FIELDWORK_TEST_DATABASE_URL` értékét. A `test_database_guard.py` előbb a hiányzó teszt-URL-t utasította el, majd a kézzel átadott teszt-URL mellett azt, hogy a `DATABASE_URL` ugyanarra az adatbázisra mutat. Ez helyes fail-closed működés, nem feloldandó biztonsági korlátozás.

A kizárólag **eldobható sandbox Docker-konténerben** alkalmazott, működő konfiguráció:

```sh
env -u DATABASE_URL FIELDWORK_TEST_DATABASE_URL="$TEST_DATABASE_URL" \
  python -m pytest -q tests/test_api.py --disable-warnings --maxfail=1
```

Ezzel a `configure_test_database()` ellenőrzés `GUARD_PASS True True` eredményt adott. A teszt-adatbázis hostja `test-db`, adatbázisneve `fieldwork_test`; éles kapcsolati adatot nem használtunk.

| Izolált futás | Eredmény | Időtartam |
|---|---|---|
| `tests/test_api.py -k photo` | **8 PASS**, 21 deselected | 23,65 s |
| `tests/test_api.py` | **29 PASS** | 68,57 s |
| `tests/test_safety.py tests/test_migrations.py` | **33 PASS** | 86,05 s |
| `tests/test_admin_rotation.py` | **ImportError** a gyűjtés során | 1,28 s |

**Összesen 62 egyedi teszt PASS.** A fotótesztek az API-modul 29 tesztjének részhalmazát alkotják, nem számítanak további 8 egyedi tesztnek.

A `test_admin_rotation.py` további vizsgálatakor az `app`, `passlib`, `scripts`, `sqlalchemy` modulcsaládok importja jelent meg; a sandbox `scripts` könyvtárában csak `init_db.py` és `migrate.py` fájl látszott. Az importhiba **pontos hiányzó szimbólumát még nem sikerült igazolni**. A teljes backend suite ezért **BLOCKED**, nem PASS.

A `fieldwork_stage_full_test` eszköz hívása belső hibával végződött, így abból nem áll rendelkezésre megbízható teszteredmény. Egy későbbi sandbox-parancs a kapcsolat megszakadása miatt nem adott eredményt.

**Éles változtatás nem történt:** minden sikeres sandbox-teszt `production_modified=false`, `production_mounts=false` és sikeres erőforrás-takarítás értékeket jelzett. A futó MCP továbbra is a korábban ellenőrzött v0.6.1.

### Következő javítás

Az MCP sandbox-futtató konfigurációját a következő, helyben jóváhagyott MCP-kiadásban úgy kell módosítani, hogy a tesztadatbázis változóit a védelmi ellenőrzés által megkövetelt módon adja át, és a produkciós `DATABASE_URL` változót ne állítsa be a tesztadatbázis URL-jére. A teljes admin-rotation tesztkészlet függőségeit és forrásmásolatát külön ellenőrizni kell. A `test_database_guard.py` védelmi feltételei **nem lazíthatók**.
