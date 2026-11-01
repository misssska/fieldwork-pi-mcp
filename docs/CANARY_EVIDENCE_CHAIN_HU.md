# FieldWork M8 – teljes canary bizonyítéklánc (read-only)

Dátum: 2026-10-31. **Csak a PR #2 fejlesztési ágán. Nem aktív Pi MCP-eszköz.**

## Miért készült?

Az átvitt, SHA256-tal ellenőrzött ZIP önmagában nem igazolja a
forrás eredetét. A privát Git-bázis megléte nem igazolja a stage fájlfa
változatlanságát. A korábbi FieldWork staging `FULL_TEST_PASS` nyugtája
nem alkalmazható az új `transfer_id`-ra.

Az `updater/canary_readiness_gate.py` ezért egyetlen, **csak olvasási**
kérésként köti össze:

1. **Transfer**: az eredeti `transfer_id` ZIP-je teljes, ellenőrzött,
   és `STATIC_CANARY_ARCHIVE_QUALIFIED_NOT_STAGED` minősítést kapott.
2. **Privát Git-bázis**: a forrásverzió és a ZIP SHA256 megegyezik a
   független, tiszta, privát Git-checkoutban ellenőrzött `HEAD`-del;
   a változtatási terv saját hashértékkel rendelkezik.
3. **Izolált snapshot**: a fájlfát függetlenül újrahasheli, és a
   `STAGE_RECEIPT.json` eredeti ZIP, Git commit, terv és filelista
   lenyomatát összeveti az első két kapuval. A stage tree ellenőrzése
   megismétlődik a nyugta olvasása után.
4. **Hitelesített tesztnyugta**: az önálló HMAC-SHA256 test gate
   igazolja a teljes ötös tesztprofilt, a stage-tree és Git-bázis
   azonosságát, valamint a korábbi `transfer_id`-hoz kötést.

Bármelyik hiányzó vagy eltérő adat `READINESS_BLOCKED` státuszt ad
a blokkoló fázissal. A kivétel részletes üzenetét és privát elérési
útvonalakat nem közli.

## Kimeneti állapotok

- `READINESS_BLOCKED`: a bizonyítéklánc hiányos vagy eltérő; nem PASS.
- `READINESS_EVIDENCE_COMPLETE_NOT_DEPLOYABLE`: a lánc minden
  olvasási kapun egyezik. **Ez sem engedélyez canary indítást,
  routingváltást vagy production deployt.**

A kód nem hív `materialize_transfer`, `runner.run`, Docker-t,
host shellt, networköt vagy stage startot, és nem hoz létre
új transzfert, Git-bázist vagy receiptet.

## A működő Pi állapota ettől független

Az élő Pi MCP v0.6.1 V2-artifact eszközökkel rendelkezik, de ez az új
readiness modul **nem telepített**. A 633 bájtos, szintetikus
`base_commit=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` canary
csomag csak az első (ZIP) kaput teljesítheti, és semmiképp sem indítható.

A korábbi `fieldwork_stage_full_test` és `fieldwork_stage_smoke`
másik, régebbi `proposal_id` kiadáshoz tartoznak. Ezek eredményét
**tilos az új artifact tesztbizonyítékaként átvenni**.

## Kötelező következő rendszerkapuk

- Helyileg jóváhagyott, pontos commitból épülő tiszta privát Git-bázis.
- A v2 ZIP-ből létrehozott valódi, éles rendszertől elkülönített
  FieldWork snapshot, a stage lineage SHA-jának ellenőrzésével.
- Valós, ARM64-en ellenőrzött, dependency-pinned offline teszt-appliance:
  négy frontend suite és külön teszt-PostgreSQL-t használó backend suite.
- Korábbi test receipt nélküli, megszakítás/crash/timeout/rollback
  ellenőrzés. Egyetlen sikertelen fázis esetén fail-closed.
- Külön, helyileg jóváhagyott MCP integráció és Docker-adapter.
  Nem lehet általános shell, új tunnel, production-volume mount
  vagy automatikus production telepítés.
- Csak ezután külön canary start, health/auth smoke és a tervezett
  LAN-only `192.168.22.13:18090` útvonal-váltási vizsgálat.

**Teszteredmény:** a GitHub Actions aktuális PR #2 HEAD-jére
vonatkozó CI-t külön kell ellenőrizni; új Pi-integrációs
teszt ebből a fejlesztési körből még nincs.
