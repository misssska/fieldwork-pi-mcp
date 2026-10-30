# Pi MCP v0.6.1 – megszakadó session és aszinkron staging-teszt

## 2026-10-30 – ellenőrzött állapot

A reboot után a Pi MCP `v0.6.1` ismét válaszolt. A rögzített `ec110000000000000000000000000002` futás bizonylata `SANDBOX_COMMAND_PASS`, pontos parancs SHA-256 `428930d45faa55e7bfe35be3598e9f7787ad32ca0874a5ffbc9e7cb53d27232f`, `62 passed`, éles módosítás és production mount nélkül, sikeres takarítással.

A `fieldwork_stage_prepare` ezután `STAGE_RELEASE_ALREADY_EXISTS` hibával visszautasított. A v0.6.1 helyi forrása szerint ez akkor történik, ha a kiadási célkönyvtár már létezik. A hiba **nem bizonyítja**, hogy a meglévő kiadás hibás; tilos a könyvtárat automatikusan törölni vagy felülírni.

A `fieldwork_stage_full_test` távoli hívás időtúllépéssel végződött, majd a Pi MCP `Session terminated` hibával elérhetetlenné vált. A pontos okot nem igazoltuk, de a v0.6.1 forrása alapján a teljes Docker-teszt **szinkron** eszközhívásként, legfeljebb 900 másodpercig fut, ami érzékeny a kapcsolat időkorlátjára.

## Már elkészült, de nem aktivált v0.6.2 aszinkron megoldás

A helyileg rendelkezésre álló `FieldWork-Pi-MCP-Async-Stage-r2.zip` forrását ellenőriztem:

- `stage_async.request`: kizárólag rögzített staging-tesztet indít, azonnal visszatér; nincs általános host shell.
- `stage_async.status`: tartós `async-test.json` bizonylatból olvas; `ASYNC_TEST_WORKER_LOST` esetén nem indít automatikusan második tesztet.
- A teljes teszt a `fieldwork-stage-tests` elkülönített Docker-projektben fut, cleanup-pal; a produkciós projektet nem érinti.
- A hozzá tartozó **29 eszközös** MCP API tartalmazza a `fieldwork_stage_test_request` és `fieldwork_stage_test_status` hívásokat. A Pi jelenleg telepített **27 eszközös v0.6.1** API-ja ezeket még nem teszi elérhetővé.
- A helyi v0.6.2 r2 forrás **71/71 egységtesztje PASS**. Ez nem Pi-n végzett integrációs teszt, és nem telepítési engedély.

## Biztonságos folytatás

1. A megszakadt MCP-kapcsolatot az alkalmazás/plugin oldalán helyre kell állítani. A további reboot önmagában nem garantálja a távoli session újranyitását.
2. Csak olvasási hívásokkal ellenőrizni a Pi MCP verzióját, a meglévő staging release státuszát és a staging projekt állapotát.
3. Ha a kiadás már elő van készítve, **nem** szabad újra `stage_prepare`-t hívni, törölni vagy felülírni a kiadást.
4. A v0.6.2 aszinkron MCP-képességek aktiválása kizárólag helyi jóváhagyással, rögzített forrás- és telepített SHA-256 egyezéssel, tranzakciós mentéssel és visszaállítással történhet. A korábban észlelt telepített MCP-hash driftet nem szabad megkerülni.
5. Ezután az új `fieldwork_stage_test_request` indítson **egyszer** tesztet; a `fieldwork_stage_test_status` segítségével a futás a kapcsolat megszakadása után is ellenőrizhető.
6. Az éles `/opt/fieldwork`, PostgreSQL, Docker és a meglévő tunnel nem módosítható.

**Állapot:** a Pi MCP kapcsolat jelenleg `Session terminated`; új staging-teszt eredmény nincs, éles frissítés nem történt.
