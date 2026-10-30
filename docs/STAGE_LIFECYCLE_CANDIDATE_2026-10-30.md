# FieldWork Pi staging lifecycle – async start és valódi konténerdiagnosztika

Dátum: 2026-10-30. Állapot: **kísérleti, csak GitHubon**. A Pi MCP v0.6.1 változatlan, az új kód nem telepített.

## Kiinduló tények

- A `cfb10c47c1b3413c9adbd50e5c7249ef` staging-kiadás teljes tesztje `FULL_TEST_PASS`.
- A v0.6.1 `fieldwork_stage_start` hívás időtúllépés után elvesztette a távoli MCP-sessiont.
- A v0.6.1 `fieldwork_stage_status` `STAGE_RUNNING_CHECK` értéket ad, de a Docker kimenetének SHA-256 lenyomata `e3b0c44298fc1c14:0:0`: **üres kimenet**, nem igazoltan futó konténerek.
- Az ismételt `fieldwork_stage_smoke` `STAGE_HEALTH_FAIL`. A staging tehát jelenleg **nem elfogadott**. A production_modified minden eddigi staging válaszban `false`.

## Elkészült kísérleti komponensek

1. [experimental/stage_inspect.py](../experimental/stage_inspect.py): kizárólag a helyileg rögzített `fieldwork-stage` projekten futtat `docker compose ps -a --format json` lekérdezést. Whitelistelt szolgáltatás- és állapotmezőket ad vissza; az üres konténerlista `STAGE_NO_CONTAINERS`, nem `STAGE_RUNNING_CHECK`. A Docker nyers kimenetét nem teszi közzé.
2. [experimental/stage_start_async.py](../experimental/stage_start_async.py): kizárólag a tesztelt, változatlan staging-kiadás `stage_manager.start` műveletét indíthatja leválasztott munkafolyamatban. Tartós `async-start.json` bizonylat, egyszer használatos job ID, meglévő staging-tesztekkel közös zárolás, duplikált indítás elleni védelem.
3. [tests/test_stage_inspect_candidate.py](../tests/test_stage_inspect_candidate.py) és [tests/test_stage_start_async_candidate.py](../tests/test_stage_start_async_candidate.py): **25/25 helyi izolált Python-egységteszt PASS**. Ezek mockolt unit tesztek, nem Raspberry Pi Docker-integrációs tesztek.

A worker sikeres visszatérése `START_COMMAND_PASS` – ez **nem** jelenti az API egészségellenőrzésének sikerét. A `STAGE_START_RECOVERY_REQUIRED` állapot tiltja a félbemaradt `STARTING` indítás automatikus újrapróbálását.

## Biztonsági korlátok

- Nincs általános shell, tetszőleges Docker-projekt, új tunnel vagy production-deploy.
- A jelenlegi `release/manifest.json` **nem** tartalmazza ezeket a kísérleti modulokat. Nem szabad őket csendben a korábbi v0.6.2 csomagba vagy telepítőbe becsempészni.
- Az `experimental/stage_start_async.py` a korábbi `stage_async.py` függvényeire épül, tehát önállóan **nem telepíthető**.
- A telepített Pi MCP SHA-256 eltérése korábban megfigyelt; előbb pontos forrásazonosítás és hash-pinning kell.
- Helyi explicit jóváhagyás, atomikus mentés/csere, service readiness, visszaállítási teszt és valódi Docker-integrációs teszt nélkül az új MCP-eszközök nem aktiválhatók.

## Következő mérnöki kapuk

1. A meglévő `active.json` állapotának és a `fieldwork-stage` projekt teljes (`ps -a`) konténerlistájának **csak olvasási** ellenőrzése. A jelenlegi MCP API ezt még nem adja ki, ezért a mostani üres kimenetből csak az bizonyítható, hogy a normál `ps` nem listázott futó konténert.
2. Az aszinkron teszt és indítás együttes versenyhelyzet-, újraindulás-, crash- és rollback-tesztje.
3. Egységes, aláírt/hashelt kiadási manifest és integrációs overlay kialakítása, amely a tényleges telepített forráson fail-closed módon ellenőrizhető.
4. Helyileg jóváhagyott aktiválás után `STAGE_CONTAINERS_RUNNING_HEALTH_UNVERIFIED` + `STAGE_HEALTH_PASS` + API regresszió kell a staging elfogadásához.

**Nem történt Pi MCP telepítés, staging újraindítás vagy éles FieldWork módosítás ebben a fejlesztési körben.**

## Újabb ellenőrzés és integrációs jelölt

A Pi MCP v0.6.1 kapcsolat 2026-10-30-án ismét válaszolt. Az újabb `fieldwork_stage_status` változatlanul `STAGE_RUNNING_CHECK` / `e3b0c44298fc1c14:0:0`, a `fieldwork_stage_smoke` `STAGE_HEALTH_FAIL`, az API staging-napló üres. A staging **nem healthy**. A szinkron `stage_start` újraindítását a bizonyítékok tisztázásáig nem ismételtük meg.

- [experimental/lifecycle_overlay.py](../experimental/lifecycle_overlay.py) pontos integrációs anchorokkal, AST-szintaxisellenőrzéssel, duplikált/eltérő forrás elutasításával egészíti ki a **már aszinkron tesztelésre felkészített** MCP-jelöltet. Három új eszköz: `fieldwork_stage_start_request`, `fieldwork_stage_start_status`, `fieldwork_stage_inspect`.
- A GitHubon új tesztek: [test_lifecycle_overlay.py](../tests/test_lifecycle_overlay.py), [test_stage_inspect.py](../tests/test_stage_inspect.py), [test_stage_start_async.py](../tests/test_stage_start_async.py).
- A helyi, izolált munkakönyvtárban az integrációs és staging-jelöltekre **35/35 Python unittest PASS**, `compileall` PASS. Ezek nem Pi Docker-integrációs tesztek; GitHub Actions eredményük még nincs ellenőrizve.
- A v0.6.1 -> aszinkron teszt -> aszinkron indítás láncot külön, hash-ellenőrzött és helyben jóváhagyott kiadásban kell aktiválni. **A GitHub-kód nem telepített Pi-kód.**

A következő elfogadási feltétel: a rögzített `fieldwork-stage` projekt `ps -a` állapotának biztonságos lekérdezése, majd a konkrét build/start hiba elkülönítése. `active.json` automatikus törlése vagy duplikált indítás tilos.
