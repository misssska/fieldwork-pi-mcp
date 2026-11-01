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
