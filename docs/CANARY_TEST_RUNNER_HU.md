# FieldWork M7 – izolált tesztfuttató és hitelesített tesztnyugta

2026-10-31. **Állapot: GitHub PR/CI-ben tesztelt kód, a Pi-n MÉG NEM AKTÍV.** Nem tévesztendő össze a Pi korábbi `FULL_TEST_PASS` staging-eredményével.

## Megvalósult

- `updater/canary_test_runner.py`: a `STAGE_VERIFIED_NOT_TESTED` és a teljes stage-tree SHA256 ellenőrzése után pontosan öt, előre meghatározott fázist indíthat:
  1. `frontend-typecheck` → a tényleges FieldWork `npm run typecheck` feladata
  2. `frontend-lint` → `npm run lint`
  3. `frontend-vitest` → `npm test` / `vitest run`
  4. `frontend-build` → `npm run build`
  5. `backend-pytest-postgres` → teljes `pytest` külön, kizárólag teszt-PostgreSQL környezetben.

- Nincs MCP-ből megadható shellparancs, image-név, timeout, mount vagy URL. A Docker argumentumai az indításkor is teljesen újraellenőrzöttek. `--network=none`, `--pull=never`, `--read-only`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, limitált PID/memória/CPU, saját UID/GID, az egész privát stage csak `/source` alatt **read-only**.
- A stage hashét minden tesztfázis előtt és után újraellenőrzi. Hibás fázisnál az összes későbbi fázis kimarad. Timeout esetén kizárólag a pontosan megnevezett tesztkonténert távolíthatja el; bizonyítatlan cleanup esetén nincs PASS.
- Külön privát, tartós `TEST_REPORT.json` nyugta. A futtató és az önálló `updater/canary_test_gate.py` csak az admin által privát fájlként tárolt **32 bájtos helyi HMAC-kulccsal** igazolt eredményt fogadja el. Nem ír ki titkot.
- A gate újraellenőrzi az öt teszt sorrendjét/eredményét, az image digestet, a Git-bázis SHA-t, a stage-fájlfa SHA-t és azt is, hogy a függőségi verziókhoz tartozó helyi image-pin nem változott.
- A helyi policy három forrásfájl hashéhez köti a teszt-image-et: `frontend/package-lock.json`, `server/requirements.txt`, `server/requirements-dev.txt`. Ha bármelyik megváltozik, a teszt **nem indul**, amíg nincs hozzá pontosan épített és jóváhagyott új image.
- Sikerkimenet csak `FULL_TEST_ATTESTED_NOT_DEPLOYED`. Ez **NEM** canary indítási vagy production telepítési engedély.

## Kritikus, jelenleg hiányzó előfeltétel

A Pi-n jelenleg nincs igazolt, előre elkészített, pontos SHA256-digesttel pinelt `fieldwork-canary-test-appliance` image és hozzá jóváhagyott privát konfiguráció. A későbbi image-nek az offline, rögzített `/usr/local/bin/fieldwork-test-suite` belépési pontot kell biztosítania, az öt fázist változatlan módon futtatva. A backend fázishoz a **konténeren belüli**, ideiglenes PostgreSQL kell, mivel `--network=none` mellett nem használható külső adatbázis. A függőségek a build időpontjában, ellenőrzött lockfile/requirements alapján telepítendők; a tesztfutás alatt az image nem tölthet le csomagot.

**Ez az appliance még nincs elkészítve, a Pi-n az új stage sincs telepítve, így valódi új M6/M7 frontend+backendteszt még NEM futott.** A meglévő `fieldwork_stage_full_test` ettől független, már kipróbált, biztonságos backend tesztútvonal. Az új tesztfuttató bekötése előtt vizsgálni kell, hogy azt érdemes-e új appliance helyett használni; ne hozzunk létre párhuzamos kockázatos Docker infrastruktúrát, ha ugyanaz a cél az ismert működő staginggel elérhető.

## Védelmi korlátok

A Docker host-hozzáférés magas jogosultságú művelet, ezért a runner **nem** része a jelenlegi élő MCP-eszközlistának. Aktiválása külön, helyileg jóváhagyott és rollbackelhető, rögzített végrehajtási engedélyt igényel. Az admin aláíró kulcsa, Docker socket és éles környezeti változói nem kerülhetnek a konténerbe. Pi-alagutat, production Compose-t, adatbázist, storage-ot és `/opt/fieldwork`-öt a runner nem módosíthatja.

## Elfogadási teszt

1. A Pi-n valós tiszta Git-bázist és egy valódi FieldWork source overlayt kell előállítani, a feltöltés/fájlhashek alapján.
2. `STAGE_VERIFIED_NOT_TESTED` kötelező, pontos SHA és fájlszám egyezéssel.
3. Az image ellenőrzött digestjének és függőségeinek rögzítése, 32 bájtos privát HMAC kulcs, helyi aktiválás.
4. Mind az öt fázis valós végrehajtása kizárólag a privát, hálózattól elszigetelt snapshoton; minden teszt PASS.
5. A külön test gate `FULL_TEST_ATTESTED_NOT_DEPLOYED` eredménye, rossz image/hmac/stage/függőség esetén FAIL.
6. Csak ezután külön canary build/start/health/auth smoke, előző route megőrzése, majd a tervezett LAN-only állandó `192.168.22.13:18090` dev origin. Az éles alkalmazás frissítése nem része ennek.

A helyi `approved-test-appliance.json` fájl **nem lehet GitHubra feltöltve** és nem tartalmazhat titkokat. A `local-test-attestation.key` helyben generálandó és `0600` jogosultságú; soha nem kerülhet csevegésbe vagy logba.
