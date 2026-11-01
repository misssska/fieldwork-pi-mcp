# FieldWork M8 — globális olvasási szerkesztő és gyors csapattagválasztó

**Állapot:** nem telepített forrásjelölt; kizárólag előkészítés és izolált tesztek. Eredeti M7 canary forrása (a felhasználó Pi host kimenete szerint 112 frontend és 103 backend PASS) változatlan marad.

## Változások

- Az admin a fiókhoz külön kioszthatja/visszavonhatja a globális `editor` szerepkört. Ez minden projekt **olvasását** engedi, de írást csak a tulajdonos/szerkesztő tagság biztosít. A rendszergazdának továbbra sincs automatikus globális projektmegtekintése; az eredeti privát projektmegosztás megmarad.
- Projektgazda a projekt **Csapat** fülén aktív, még nem tag felhasználókat név/e-mail alapján kereshető legördülőből választ, és stabil felhasználóazonosító szerint rendeli hozzá. Csak owner láthatja a jelöltlistát. A régi e-mailes API visszafelé kompatibilis.
- A frontend látható és online állapotban 12 s-onként ellenőrzi a szerveroldali jogosultsági fingerprintet; változáskor teljes böngészőújratöltés, új engedélyezett adathalmaz. Fókuszváltáskor/újra online állapotban azonnal ellenőriz. Jogosultságon kívüli adat lekérését szerveroldali API ellenőrzi. A böngészőn már letöltött adatoknak offline állapotban nincs visszamenőleg garantálható visszavonása.
- A fiók `worker/editor` rendszerszerep és a projektszerep `viewer/editor/owner` **különböző**. `admin/admin` nincs, nem is lesz.

## Integritás

- A PIN-elt M7 forrásról privát könyvtárba másol. Mind a 15 M7 változtatott fájl forrás-hashét, a korábbi 112/103 tesztjegyzőkönyvet, és mind a négy M8 team/account eredeti fájl SHA-ját ellenőrzi, valamint az érintetlen `App.tsx` SHA-ját.
- Összesen 8 új/átírt fájl: team_api, account_api, ReferenceTeam, TeamDirectory, main.py, App.tsx, frontend API, 6 backend integrációs tesztet tartalmazó új fájl. Nincs adatbázismigráció.
- Teszt: Node frontend TypeScript+ESLint+112 Vitest, külön eldobható PostgreSQL 109 pytest (103+6). **Az itt előírt native tesztszám csak elfogadási cél, nem futott teszt.**
- Pi-n éles `/opt/fieldwork`, R8 stabil `:18090`, M6 `:18086`, M7 forrás, felhasználói adatbázisok, levelek és naptár változatlanok. A ZIP önmagában inert, feltöltése nem telepítés.

## Korlátok

- A teljes böngészős, 2 valós fiókos átvétel, szerepmegvonás/offline UI, PDF/videó hozzáférés, régi projektek visszatöltése még kötelező telepítés előtt.
- A 12 másodperces polling nem SSE/WebSocket és a több böngésző közt maximum-idejű garancia nincs hálózati hiba/hibás időzítés alatt.
- Egyszerre egy új M8 tesztprojektet használ; ha korábbi futásból tesztkonténer maradt, STOP és emberi ellenőrzés, nincs automatikus más projekt takarítás.

## R3 – M7 App.tsx ellenőrzési helyesbítés, 2026-11-01

A Pi-n az M8 R2 első valós előkészítése megállt `M8_STOP:M7_APP_SOURCE_PIN_DRIFT` hibával, miután a ZIP, manifest és loader SHA PASS volt. Ez egy tévesen a Pi alapkódból átvett `App.tsx` SHA ellenőrzés volt: az M7 forrás az M5→M6→M7 másolási láncból származik. Az App.tsx egyik overlay módosított forrásfájljai között sem szerepelt.

Az R3 **nem kapcsolja ki a forrásazonosság-védelmet**: az M5, M6 és M7 jelölt `frontend/src/App.tsx` fájljának egyenként ellenőrzi a regular-file státuszát, SHA256-ját és egyezését. Ellenőrzi továbbá az M6 és M7 forrás-receipt mezőit, az App hiányát a módosított fájlok listájából, valamint a három egyedi React patch-anchort. Minden eltérés STOP. Minden változás csak az izolált M8 source candidate-ben történhet.

Az R3 kizárólag `m8_candidate.py` ellenőrzését és négy negatív/pozitív tesztet változtat az R2-höz képest. Nem módosítja a produkciós appot, az M7 videós támogatást, a globális szerkesztő scope szabályt, a Csapat tagválasztót vagy az M8 PostgreSQL-tesztek tartalmát. Lokális statikus ellenőrzés: **22/22 PASS**. Pi-n teljes M8 native frontend/PostgreSQL teszt: **NOT RUN**.
