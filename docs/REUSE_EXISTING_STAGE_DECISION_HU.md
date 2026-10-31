# FieldWork – staging újrahasznosítási döntés (2026-10-31)

## Tényleges Pi-bizonyíték

A meglévő Pi MCP v0.6.1 `fieldwork_stage_capabilities` szerint csak `prepare_from_tracked_head_and_tested_proposal`, `full_suite_in_stage_test_project`, `start_stage`, `stop_stage` és kapcsolódó stage-státuszok támogatottak. Nincs általános `verified artifact -> existing stage` belépési pont.

A `cfb10c47c1b3413c9adbd50e5c7249ef` korábbi stage `FULL_TEST_PASS` állapota **nem** igazolja egy később feltöltött ZIP tesztjét, mert a nyugtában nincs `transfer_id`, `archive_sha256`, `base_commit` vagy `snapshot_tree_sha256`. Ezt tilos új csomag tesztpasszának tekinteni.

Két elkülönített `fieldwork_sandbox_command` próba:

| Jellemző | Mért eredmény |
|---|---|
| CWD | `/workspace/server` |
| Python | `3.13.14` |
| Pytest | `8.4.2` |
| Backend app és tests | jelen vannak |
| Node.js/npm | nincs |
| Frontend source | nincs |
| Cleanup | sikeres |
| Production writes/mounts | false / false |

**Döntés:** a meglévő backend stage/full-test infrastruktúrát megtartjuk, de **nem csatoljuk rá a feltöltött csomagot** addig, amíg a véglegesített ZIP-ből készülő privát stage nem kap egy új, kifejezetten erre jóváhagyott bemeneti kaput. A legacy `proposal_id` és az új `transfer_id` nem felcserélhető.

## Szükséges, nem megkerülhető integrációs változások

1. A privát Git-bázist az éles, piszkos `/opt/fieldwork` clone helyett pontos, külön forrásból kell biztosítani.
2. A `fieldwork_artifact_finalize` után az új archive/manifest/base/stage-integritás kapuk érvényesítik a módosított fájlokat.
3. A már létező backend stage tesztprojektet csak olyan **új, helyileg jóváhagyott API** indíthatja, amely a privát snapshot `transfer_id + archive SHA + tree SHA + base commit` értékére kötött megváltoztathatatlan nyugtát állít elő.
4. A frontend számára külön rögzített Node.js / npm eszközkörnyezet kell, kizárólag a privát source read-only mounttal; nincs production mount, nincs Docker socket a tesztkonténerben. A frontend a tényleges `frontend/package.json` parancsait futtatja: typecheck, lint, vitest, build.
5. A teljes teszt-PASS csak akkor állhat elő, ha **ugyanaz a privát stage-tree SHA** szerepel a frontend és backend igazolásában. Eltérő bázis, hiányzó nyugta, régi `FULL_TEST_PASS`, vagy megváltozott forrás esetén a kiadás BLOCKED.
6. Az új `updater/canary_test_runner.py` egy teljes offline teszt-appliance **kísérleti alternatívája**, **nem helyezhető automatikusan üzembe**. Mivel jelenleg nincs jóváhagyott image a Pi-n, és már rendelkezésre áll backend stage-test, ennek a külön PostgreSQL-es párhuzamos futtatónak a bevezetése nem javasolt, amíg a meglévő stage backend integráció igazolható.

## Javított stage materializer (GitHub PR)

Az éles FieldWork Git-fában vannak követett `.github/workflows`, `.gitignore`, `README.md`, dokumentumok és lehetséges `.env.example` sablonok. A korábbi `_tree` minden ilyet elutasított volna, így a szintetikus unit-teszt még nem bizonyított valós reposnapshot-kompatibilitást.

A materializer most:
- az auditált, inert GitHub-/Git-metaadatokat és dokumentációt **kihagyja**;
- az alkalmazás forrását, tesztjeit, függőségi és compose fájljait megtartja;
- minden Git objektum módját előre validálja, még a kihagyott metaadatokét is;
- a rejtett érzékeny fájlokat (például `frontend/.npmrc`, `server/app/.env`) elutasítja;
- minden egyéb ismeretlen, nem review-zott fájlnál fail-closed;
- kizárólag a privát stage-be ír, nem az éles Git-munkafába.

A kompatibilitást valódi ideiglenes Git-repozitóriumos integrációs tesztek vizsgálják. **A teljes éles FieldWork repo Git-objektumlistáján a Pi-n még nem futott**, így valós forrásazonosság vagy release-pass nem állítható.

## Elfogadási kritérium

Az adapternek ténylegesen a Pi-n kell visszaadnia az új `STAGE_VERIFIED_NOT_TESTED` és később egy hiteles, `transfer_id/sha256/tree` mezőkkel kötött backend és frontend PASS eredményt. Csak ezt követheti a canary start, smoke, visszaállítás. A fix LAN-only `192.168.22.13:18090` dev cím még **nem aktív**.

A működő `fieldwork-stage` és `/opt/fieldwork` változatlan marad. Nem kell új alagút, éles Docker restart vagy éles DB-migráció ehhez az előkészítéshez.
