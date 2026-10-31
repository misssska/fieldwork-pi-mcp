# FieldWork Pi MCP – egyszeri, helyileg jóváhagyott v2 bővítés

2026-10-31. **Nem telepített**, kizárólag GitHub CI-ben minősített változat.

## Cél és hatókör

A Pi-n aktív v0.6.1 + 4 inert feltöltő MCP-eszközhöz két új funkció:

1. `fieldwork_artifact_qualify` – kizárólag `VERIFIED` ZIP/manifest statikus ellenőrzése, a teljes tartalom SHA256- és forrásútvonal-ellenőrzése, **végrehajtás vagy host-kicsomagolás nélkül**.
2. `fieldwork_artifact_retire` – kizárólag az explicit `transfer_id` és az elvárt teljes SHA256 egyezése után, a `RETIRE_VERIFIED_CANARY` megerősítéssel távolítható el egy már igazolt feltöltés. A már nyugtázott transzferazonosító soha nem válik újra használhatóvá.

A már futó feltöltőmodul `artifact_inbox.py` frissítésével csak a **nyitott, 32 hex nevű transzferkönyvtárak** számítanak a nyolc aktív feltöltési helybe. A befejezetlen és nem igazolt feltöltések nem törölhetők.

## Rögzített környezet

- Várt aktív `fieldwork_mcp.py` SHA256: `2c03f152c26052dcad5dbadf97f809f3f924cddb702b2a92b51a180f29e268b6` (az előző, sikeres helyi aktiválás jelölt forráshashe).
- Várt eredeti `artifact_inbox.py` és `artifact_inbox_adapter.py` bájtjai: a korábbi, immutábilis `dde90680881d2eca4380bfb6c3a53383912e38a6` commitból (a telepítő byte-for-byte összeveti a Pi jelenlegi fájljaival).
- Aktív, `admin` tulajdonú MCP telepítés: `~/.local/share/fieldwork-pi-mcp/v0.6.1`.
- Meglévő systemd service: `fieldwork-pi-tunnel.service`; **sem új tunnel, sem új port, sem production beavatkozás** nem engedett.
- A tényleges telepítő: `updater/activate_artifact_extension_v2.py`; csak immutable 40 karakteres commitra hivatkozhat, és előbb a teljes helyi forrásdiftet, valamint az új modulok szintaxisát ellenőrzi.

## Egyetlen helyi operátori művelet – majd csak GitHub CI PASS után

A jóváhagyott, teljes 40-hex commitból a telepítő HTTPS-en letölthető, de a futtatása **csak az ellenőrzött SHA256 egyezése után** megengedett. A futás egyetlen, helyi `AKTIVALOM_V2` megerősítést és a már meglévő sudo-jogosultság egyszeri jóváhagyását kéri.

A telepítő kizárólag a v0.6.1 MCP Python-forrását, a `artifact_inbox.py` fájlt és négy új, szigorúan inert adaptermodult módosíthat. Előtte a két felülírt fájlról külön, `0600` mentést készít. Az új Python-fájlokat atomikusan írja ki; a meglévő systemd-szolgáltatást egyszer újraindítja. Helyi `readyz` hibánál megkísérli az automatikus rollbacket. **A `readyz` nem igazolja az új MCP-eszközök discoveryjét**; a ChatGPT oldali újracsatlakozás és külön `qualify` próba még kötelező.

Ha a telepítő hibát ír, **nem szabad automatikusan megismételni**; az aktuális receipt alapján ellenőrzött rollback szükséges. Másodszori automatizmus tiltott, mert a felülírás előtti várt hash-ek eltérhetnek.

## Későbbi live-elfogadási próba

1. A v2 aktiválás után a meglévő 4 eszköz működik és megjelenik az új `qualify`, `retire` tool (6 összesen).
2. A korábban sikeresen átvitt, **633 bájtos inert canary ZIP** (`transfer_id=4e1ad4a99c4c4e4db6e1e48b45d78ee5`, `sha256=605b35b2db63fb5c07019d75dae3363f62567fd9b2b6d806b0b376f9b42077cc`) csak statikus ellenőrzési próbára használható. A manifestben a bázis-commit szintetikus; **ezt telepíteni tilos**.
3. A `retire` csak külön explicit jóváhagyással és az azonosított tesztfájlra használható; befejezetlen, idegen vagy eltérő hashű csomagnál FAIL.
4. A Pi production `/api/health` HTTP 200 és a meglévő staging `STAGE_HEALTH_PASS` változatlan.
5. A full release integráció (pinned Git stage, backendteszt, Node frontendteszt, canary start, fix LAN-only 18090) ettől még **nincs kész**.

## Fontos műszaki korlát

A Pi aktív `stage_manager` forrása nincs a `fieldwork-pi-mcp` GitHub repóban; a korábbi stage `proposal_id`-t fogad el. A jelen bővítés **nem próbálja megkerülni** a stage-manager helyi jóváhagyását, és nem állítja, hogy a feltöltött source ZIP-et a legacy `FULL_TEST_PASS` már igazolta. A valódi `transfer_id -> stage` adapterhez a jelenlegi stage-manager pontos, külön rögzített interfészét kell review-zni.
