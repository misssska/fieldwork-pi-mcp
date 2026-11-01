# FieldWork – privát Git-snapshotból izolált canary stage

2026-10-31. ÁLLAPOT: kizárólag PR/CI teszt, a Pi aktív MCP-eszközkészlete még nem tartalmazza ezt a stage-funkciót.

## Megvalósult

`updater/canary_stage_materializer.py` csak `VERIFIED` transferből és az előellenőrzött `~/.local/state/fieldwork-pi-mcp/canary-git-base` tiszta, rögzített Git HEAD-ből dolgozhat. Nem olvas forrást a piszkos `/opt/fieldwork` production munkafából. Minden base fájlt Git objektumból (ls-tree/cat-file), típus- és méretellenőrzéssel olvas, és csak új `~/.local/state/fieldwork-pi-mcp/canary-stage-workspaces/<32hex>` munkakönyvtárba ír.

A stage kizárólag owner módban (`0700` mappák és `0600` fájlok) készül, nem követi a szimbolikus hivatkozásokat, nem enged többféle veszélyes fájlnevet vagy titok-/DB-fájlt, a fájlokat nem állítja executable módba, nem hív Dockert vagy host-shellt. A végleges `STAGE_RECEIPT.json` csak az összes forrás bájtjának kiírása és visszaellenőrzése után jelenik meg. Megszakított részleges stage munkakönyvtár újrafelhasználása tilos.

`updater/canary_stage_inspect.py` külön, csak olvasási gate: minden stage-file path, size és SHA256 értékét ismételt tree-digestben ellenőrzi, megvizsgálja a tulajdonost és a jogosultságokat, és kizárólag a teljesen befejezett, változatlan stage esetén ad `STAGE_VERIFIED_NOT_TESTED` státuszt.

## Tesztek

Valódi ideiglenes Git repo + inbox véglegesítés -> byte-pontos snapshot (köztük üres `__init__.py`), szigorú staging fájljogosultság, újrafuttatás/replay deny, elavult source SHA/commit deny, dirty/untracked base deny, symlink deny, megszakadt receipt deny, stage-file módosítás utáni integrity deny.

GitHub Actions PR head run #41187323812: **323 updater unittest + 12 bootstrap unittest PASS**, Python compile PASS. Sem a Pi host, sem az éles Docker nem része ennek a CI-nek.

## Kritikus még hátralévő kapcsolatok

1. A Pi-n a külön privát Git-bázis **még nem telepített/ellenőrzött**. Valódi FieldWork source provenance és pontos bázis-commit kell, nem szintetikus 40 hex.
2. Az MCP transport aktuális négy eszközét továbbra is elérjük; a hozzáadott minősítő/stage eszközöket helyileg jóváhagyott, pontos SHA256-hoz kötött frissítésben kell bekötni, az ismert v0.6.1+transport MCP-forrás ellenőrzésével.
3. A stage materializálás **nem futtat teszteket**. Külön, előre korlátozott runner kell frontend `npm ci` / `npm run typecheck` / `npm run lint` / `npm test` / `npm run build` és a FieldWork `docker-compose.test.yml` backendteszt szigorúan izolált Docker környezetével. Meg kell oldani a lockfile/package letöltések hitelesített, kontrollált függőségi hozzáférését, vagy előre feltöltött image-et.
4. Az új kiadásra váltás előtt szükséges a külön canary rendszerindítás, health/auth smoke, tartós DEV-adatbázis/JWT és LAN-only fix `192.168.22.13:18090` cím, plusz bizonyított route rollback.
5. A stage nyugta `STAGE_VERIFIED_NOT_TESTED` nem `TESTS_PASS`, `CANARY_HEALTH_PASS` vagy production deployment. Az utóbbi továbbra is külön, kifejezett jóváhagyású feladat.

## Működő Pi-részek ellenőrzése

2026-10-31: a régi staging `cfb10c47c1b3413c9adbd50e5c7249ef` release status `FULL_TEST_PASS`, staging smoke `STAGE_HEALTH_PASS`. Ez korábbi stage-bizonyíték, nem az új privát stage-snapshot éles próbája. Az éles API health HTTP 200.
