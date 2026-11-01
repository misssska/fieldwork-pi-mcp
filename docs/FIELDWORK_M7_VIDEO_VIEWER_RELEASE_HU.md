# FieldWork M7 – MP4/WebM és megtekintői űrlapok, izolált forrásjelölt

## Funkció
- Projekt „Tervek és dokumentumok” területén MP4/WebM fájlok feltöltése, megtekintése/lejátszása és letöltése; a rajzok és PDF-ek továbbra is önálló dokumentumok, nem kerülnek a fényképek közé.
- MP4/WebM fájlonként 100 MiB korlát; más dokumentumok és fotók alapértelmezett 25 MiB korlátja megmarad. Nginx engedélyez 110 MiB kérésméretet, és CSP media-src blob: szabályt. A 100 MiB-os videó v1 teljes, hitelesített blobként tölthető be, tehát a böngésző egyszerre sok memóriát használhat. Nincs resumable upload vagy video-transcoding, codec-függő lejátszás.
- A szerveroldali MP4/WebM MIME-ellenőrzés alap konténerfejlécet ellenőriz; ez nem teljes vírus-/codec-ellenőrzés. A tisztán szövegként átnevezett hamis videót elutasítja. A hitelesített dokumentumletöltés és projekt-szintű jogosultság-ellenőrzés megmarad.
- A projektdokumentumok és a feladatpanel feltöltő/kommentelő űrlapjai a szerver által visszaadott projekt-tagság alapján csak szerkesztőnek vagy tulajdonosnak jelennek meg. A teljes FieldWork UI összes műveletének viewer kezelése **még nincs kész**; külön éles API elfogadási kapu kötelező.
- M7 **nem importál valódi Gmail PDF-eket** és nem állítja át a 18090 gatewayt; ez külön projektmérföldkő a jogosultsági hiba feloldása után.

## Munkamenet
1. E csomag csak a már igazolt, működő `parity-m6._sdfbhky` jelöltet olvassa, eredeti R6 SHA/tesztnyugták és források ellenőrzésével.
2. Új könyvtárat hoz létre `~/.local/state/fieldwork-pi-mcp-v03/stage-v06/parity-m7-video.*` alatt, pontosan deklarált 11 régi fájlt alakít át, és négy új teszt/hook fájlt ír. A létező M6 módosítatlan.
3. Külön frontend Docker build és hálózat nélküli TS/ESLint/Vitest: várható 19 fájl / 112 teszt.
4. Külön, csak ideiglenes PostgreSQL-memóriaadatbázissal teljes backend suite: várható 103 teszt (95 régi + 8 új). A teszt Compose vége `down`, M7 nem futó, nem telepített alkalmazás.
5. Ha bármelyik ellenőrzés FAIL, a jelölt és naplók megmaradnak diagnosztikára. Nincs fallback a működő M6/18090/prod átalakítására.

## Visszaállítás és elfogadás
- A M6 18086, R8 18085 és 18090, stage 18081, éles `/opt/fieldwork` és meglévő Docker volumenek változatlanok. Nincs migráció vagy admin/jelszó változtatás.
- Release gate: 112/112 + 103/103 Pi teljes teszt; valódi MP4 H.264 és WebM lejátszás teszt külön canary-n; jogosultság owner/editor/viewer külön identitásokkal, 403/`rejected` szerveroldalon; tárolási kvóta és későbbi backup.

**Jelen csomag állapota:** offline patch-regressziók PASS; a Pi teljes M7 gate csak az admin által elindított készítést követően lesz ellenőrizhető.

## R2 – 2026-11-01: pontos M6-forrás SHA-javítás

A Pi-n az R1 bundle integrity és `--precheck` PASS volt, de az izolált M7 előkészítése leállt:
`M7_STOP:UNMODIFIED_SOURCE_PIN_DRIFT:frontend/src/components/Documents.tsx`.
A helyileg jóváhagyott read-only diagnosztika az aktuális `parity-m6._sdfbhky` jelöltet vizsgálta: 8/10 régi hash PASS, **2 DIFF**, 11/11 patch-anker PASS.

Az M7 R2 kizárólag a `video_overlay.py` két rögzített SHA256 értékét változtatja:
- `frontend/src/components/Documents.tsx` tényleges Pi SHA `a99dd1f32d240bc1540c36e7bb8977f8583b4e328825f815cc3ae7da4524e947`.
- `frontend/src/components/TaskDetail.tsx` tényleges Pi SHA `2ef173512fc252c6f9229c1812d7ae650b473e97d0340813bb4fc792b5f3c170`.

Minden más forrás- és overlayfájl az R1-ben pontosan ugyanaz maradt. Az M7 full test számok **továbbra is csak elvárt** 19/112 frontend, 103 backend, nem Pi-n igazolt eredmények. Hozzáadva két negatív regresszió: exact M6 Pi SHA-k és drift fail-closed. Offline unit **18/18 PASS**.

- R2 ZIP: `FieldWork_M7_R2_Exact_M6_Pins_Video_Viewer_20261101.zip`, **18 329 byte**, SHA256 `729404125914ccd4fda521f1380e48dbbd016a0c29ad5a469bff08ae1f609fc8`.
- Pi MCP inert transfer `729404125914ccd4fda521f1380e48db`: **VERIFIED_NOT_DEPLOYED**, Pi oldali SHA match, production_modified=false.
- Loader: `updater/fieldwork_m7_r2_prepare_verified_inbox.py`, SHA256 `06eb8c7f537a3ea7af0d30d8a75a8a79de92bac773b2b41e39487836d80d00d5`.
- R2 változtatás a meglévő **draft PR #5** ágában; nem új alternatív release vagy Pi-konténer. Aktív M6 18086, stabil R8 18090, éles /opt/fieldwork érintetlen.

**M7 R2 teljes Pi teszt még NEM FUTOTT**, kézi admin `--precheck` és `--prepare-and-test` jóváhagyásra vár. Hiba esetén új jegyzőkönyv alapján célzottan javítandó; 18090 átállítás és Gmail import TILOS viewer-acceptance előtt.
