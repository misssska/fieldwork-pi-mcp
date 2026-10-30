# Izolált tesztadatbázis-környezet – javítási előkészítés

## Megerősített hiba

A Raspberry Pi MCP v0.6.1 `fieldwork_sandbox_runtime_test` alapértelmezett fotótesztje a tesztgyűjtéskor elbukott. A sandboxban a `DATABASE_URL` és `TEST_DATABASE_URL` azonos volt, miközben a `FIELDWORK_TEST_DATABASE_URL` hiányzott. A FieldWork `configure_test_database()` védelmi ellenőrzése jogosan blokkolta ezt az állapotot.

A védelmi kód módosítása nélkül sikeres izolált tesztparancs:

```sh
env -u DATABASE_URL FIELDWORK_TEST_DATABASE_URL="$TEST_DATABASE_URL" \
  python -m pytest -q tests/test_api.py --disable-warnings --maxfail=1
```

A fenti parancsot kizárólag a már engedélyezett, eldobható sandbox Docker-konténerben futtattam. A teljes API-modul 29/29, a safety+migration modulok 33/33 PASS, ebből 8 fotóteszt PASS. Összesen 62 különböző teszt PASS.

## Előkészített kód

Az `updater/sandbox_db_env.py` **tisztán memóriában** létrehozza a helyes tesztkörnyezeti változókat. Nem indít tesztet, nem módosítja az aktuális folyamat környezetét, nem csatlakozik adatbázishoz, és nem tartalmaz host-parancsot.

A `build_isolated_test_env()` a következőket követeli meg:

- `FIELDWORK_TESTING=1`
- külön `TEST_DATABASE_URL` PostgreSQL URL
- `test-db` host, `fieldwork_test` adatbázis, csak alapértelmezett/5432 port
- semmilyen URL query vagy fragment (különösen az esetleges host-átirányítás miatt)

A visszaadott **új** környezeti szótárból eltávolítja a `DATABASE_URL` változót, a `FIELDWORK_TEST_DATABASE_URL` változóba pedig az ellenőrzött teszt URL-t helyezi. Az eredeti környezetet nem módosítja. A FieldWork saját `configure_test_database()` ellenőrzése ettől függetlenül továbbra is kötelező.

**12/12 offline egységteszt PASS** a ChatGPT izolált környezetében, beleértve a tiltott hostot, adatbázisnevet, portot, SQL driver-t, URL query-t és a titkokat nem tartalmazó hibajelzéseket.

## Korlátok

Ez még **nem aktív a Raspberry Pi MCP-jében**. A prototípus szándékosan nincs benne a bootstrap manifestben; a futó MCP-főfájlhoz és a tunnelhez nem nyúltam.

A teljes tesztcsomag admin-rotation modulja importálási hibával megállt, ezért a teljes suite még nem PASS. A stage-full-test eszköz belső hibával tért vissza. A Pi-kapcsolat később megszakadt, így további helyi diagnosztika akkor folytatható, ha az MCP ismét elérhető.
