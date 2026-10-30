# FieldWork Pi MCP — ellenőrzött GitHub-frissítések

A Raspberry Pi-n futó FieldWork MCP biztonságos, reprodukálható frissítési infrastruktúrája.

## Elkészült

- **Egyszeri bootstrap**: [bootstrap/bootstrap.py](bootstrap/bootstrap.py). GitHubról, konkrét commitból és SHA-256 ellenőrzéssel tölti le az updater modulokat, kizárólag külön staging könyvtárba. Nem írja felül a futó MCP-t.
- **Frissítés-előkészítő**: [updater/stage_release.py](updater/stage_release.py). Csak az Async Stage modulokat fogadja el, a teljes `fieldwork_mcp.py` lecserélését a manifest elutasítja.
- **Eltérésérzékeny MCP-módosító**: [updater/async_overlay.py](updater/async_overlay.py). A tényleges telepített forrásra csak akkor alkalmazható, ha minden egyedi integrációs pont pontosan egyezik.\n- **Új: csak olvasható frissítési alkalmassági kapu**: [updater/qualification.py](updater/qualification.py). Ellenőrzi a Pi telepített főfájljának pontos SHA-256 értékét, a staging receiptet, a két kiadásfájlt, az overlay azonosságát, és memóriában előállítja a jelöltet. Semmit nem telepít.
- **Publikált, hash-ellenőrzött Async Stage kiadás**: [release/manifest.json](release/manifest.json), [release/stage_async.py](release/stage_async.py), [release/async_overlay.py](release/async_overlay.py).
- **Új, izoláltan tesztelt aktiválási terv**: [updater/activation_plan.py](updater/activation_plan.py). Csak olvasható, SHA-256-ellenőrzött dry-run; nem aktivál, nem indít újra és nem ad telepítési jogosultságot. 12/12 helyi offline teszt PASS. [Biztonsági kapu](docs/ACTIVATION_GATE.md).\n- **Automatikus CI-tesztek**: [.github/workflows/security-tests.yml](.github/workflows/security-tests.yml), beleértve a bootstrap manifest és a kiadás integritását.

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
