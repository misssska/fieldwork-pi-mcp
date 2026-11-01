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
