# FieldWork Pi MCP — ellenőrzött GitHub-frissítések

A Raspberry Pi-n futó FieldWork MCP biztonságos, reprodukálható frissítési infrastruktúrája.

## 2026-10-30 – staging lifecycle mérföldkő (NEM telepített)

A v0.6.1 MCP-ben a staging `STAGE_RUNNING_CHECK` státusza félrevezető: az utolsó Docker `ps` kimenet **üres**, a staging health `STAGE_HEALTH_FAIL`. A produkciós API és PostgreSQL a csak olvasási Docker-lekérdezéskor healthy volt. A staging **nem elfogadott**.

Az új, egyben kezelendő fejlesztési csomag: `experimental/stage_inspect.py` (valódi `ps -a` diagnosztika), `experimental/stage_start_async.py` (tartós, duplikálást tiltó aszinkron indítás), `experimental/lifecycle_overlay.py` (pontos forrás-illesztési kapu) és `experimental/lifecycle_qualification.py` (SHA-256-alapú, kizárólag olvasási ellenőrzés). Az öt modul rögzített SHA-256 értékeit a [lifecycle manifest](experimental/lifecycle_manifest.json) tartalmazza. A manifest SHA-256: `d500da3872ff05c22cefbc75fa8091fc30e39471a634926e127e3a48d13a1c0e`, az első teljes snapshot commit: `45657a2592218b326f4ca75a63a78923e86bd69f`.

A [biztonsági ellenőrzési kapu](docs/STAGE_LIFECYCLE_CANDIDATE_2026-10-30.md) és az új offline tesztek a GitHubon vannak. A statikus ellenőrző helyi, izolált tesztje **11/11 PASS** (9 negatív/pozitív kvalifikációs teszt + 2 overlay-lánc teszt); a GitHub Actions futási eredményét és a Pi-n végzett integrációt még külön igazolni kell. **Nincs Pi-telepítés, automatikus MCP-frissítés vagy production-deploy.**

## Elkészült

- **Egyszeri bootstrap**: [bootstrap/bootstrap.py](bootstrap/bootstrap.py). GitHubról, konkrét commitból és SHA-256 ellenőrzéssel tölti le az updater modulokat, kizárólag külön staging könyvtárba. Nem írja felül a futó MCP-t.
- **Frissítés-előkészítő**: [updater/stage_release.py](updater/stage_release.py). Csak az Async Stage modulokat fogadja el, a teljes `fieldwork_mcp.py` lecserélését a manifest elutasítja.
- **Eltérésérzékeny MCP-módosító**: [updater/async_overlay.py](updater/async_overlay.py). A tényleges telepített forrásra csak akkor alkalmazható, ha minden egyedi integrációs pont pontosan egyezik. 
- **Új: csak olvasható frissítési alkalmassági kapu**: [updater/qualification.py](updater/qualification.py). Ellenőrzi a Pi telepített főfájljának pontos SHA-256 értékét, a staging receiptet, a két kiadásfájlt, az overlay azonosságát, és memóriában előállítja a jelöltet. Semmit nem telepít.
- **Publikált, hash-ellenőrzött Async Stage kiadás**: [release/manifest.json](release/manifest.json), [release/stage_async.py](release/stage_async.py), [release/async_overlay.py](release/async_overlay.py).
- **Új, izoláltan tesztelt aktiválási terv**: [updater/activation_plan.py](updater/activation_plan.py). Csak olvasható, SHA-256-ellenőrzött dry-run; nem aktivál, nem indít újra és nem ad telepítési jogosultságot. 12/12 helyi offline teszt PASS. [Biztonsági kapu](docs/ACTIVATION_GATE.md). 
- **Új: visszaállítási tranzakciós labor**: [updater/transaction_lab.py](updater/transaction_lab.py) és [16 hibainjektálásos teszt](tests/test_transaction_lab.py). Tartós napló, atomikus fájlcsere, megszakítás utáni rollback. **Csak izolált tesztkönyvtárban működik, nem telepítő.** [Részletek](docs/TRANSACTION_LAB.md).
- **Helyi jóváhagyási bizonyíték prototípus**: [updater/local_approval_lab.py](updater/local_approval_lab.py) és [17 offline teszt](tests/test_local_approval_lab.py). Rövid élettartamú, konkrét forráshash-ekhez kötött HMAC és egyszer használatos nonce. **Nincs tokenkiállító, telepítési jogosultság vagy távoli aktiválás.** [Korlátok](docs/LOCAL_APPROVAL_LAB.md).
- **Új: izolált tesztadatbázis-környezet javításának előkészítése**: [updater/sandbox_db_env.py](updater/sandbox_db_env.py), [12/12 offline egységteszt](tests/test_sandbox_db_env.py). A Pi-n a fotófeltöltési és API-regresszióból 62 különböző teszt PASS; a 62 tesztből álló biztonságosan gyűjthető suite PASS; az admin-rotation tesztet a sandbox szándékos forráskizárása miatt külön kell vizsgálni. [Diagnózis és korlátok](docs/SANDBOX_DB_ENV_FIX.md). **Nem telepített Pi-frissítés.**
- **Admin-rotation importhiba vizsgálata**: [updater/admin_import_preflight.py](updater/admin_import_preflight.py), [15/15 offline teszt](tests/test_admin_import_preflight.py). Az előző tesztadatbázis-javítóval együtt 27/27 helyi teszt PASS. A Pi-kapcsolat helyreállt; igazoltuk, hogy az egyetlen hiányzó modul a biztonsági forráskizárási szabály miatt maradt ki. A kizárást nem oldjuk fel. [Diagnosztika](docs/ADMIN_IMPORT_PREFLIGHT.md).
- **Automatikus CI-tesztek**: [.github/workflows/security-tests.yml](.github/workflows/security-tests.yml), beleértve a bootstrap manifest és a kiadás integritását.

## Ellenőrzött eredmények

- A bootstrap 10 izolált, offline tesztje: **10/10 PASS** a helyi munkakörnyezetben.
- A publikált `release/stage_async.py` Git blob hashértéke egyezik az Async Stage r2 eredeti csomagjával.
- Az r2 csomag korábbi összeállított tesztjei: **71/71 PASS**, de ez **nem** a Pi telepített MCP-forrásának tesztje.
- A GitHub Actions aktuális futási eredménye nincs megerősítve.

## Ami még NINCS kész

A Pi-re **nem** telepítettem a bootstrapot vagy az új MCP-eszközöket. A jelenlegi MCP nem engedi a saját host-fájljainak távoli módosítását, és ezt nem kerülöm meg. A telepített `fieldwork_mcp.py` SHA-256: `7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04`, amely eltér a korábbi v0.6.1 alapverziótól.

A GitHubról történő előkészítés **nem egyenlő** az önálló telepítéssel. A helyben jóváhagyható, izoláltan tesztelő, aktiváló és hibánál visszaállító komponens még szükséges. A GitHub-frissítési csatorna teljes MCP-integrációja előtt **ne telepíts kézzel kódot** ebből a repositoryból.

## Védelem

Az éles `/opt/fieldwork`, az adatbázis, a produkciós Docker és a meglévő `fieldwork-pi-tunnel.service` változatlan. Nincs általános host shell, nincs új tunnel és nincs jóváhagyás nélküli önfrissítés.

Részletek: [Architektúra](docs/ARCHITECTURE.md), [Ellenőrzési napló](docs/TEST_EVIDENCE_2026-10-30.md).
