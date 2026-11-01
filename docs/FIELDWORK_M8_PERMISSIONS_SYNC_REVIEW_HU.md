# FieldWork M8 – átfogó jogosultsági korrekció, izolált natív teszt

A korábbi, **bizonyított** M7 R2 Pi forrásból (parity-m7-video.7bc9a74m) készít új forrásjelöltet; a korábbi M7/M6/R8 és /opt/fieldwork módosítása tiltott. A ZIP saját szerkezeti manifesttel és SHA256 azonosítóval rendelkezik.

## Javítások
- Rendszer-admin: minden projekt lekérdezése és módosítása, csapat- és szerepkezelés, beleértve a korábban csak egyetlen fióknak látszó projektet. Az adatbázis tulajdonos- és tagsági sorait nem írjuk át automatán.
- Csak rendszergazda hozhat létre új főprojektet; editor/gazda kizárólag írásra jogosult szülőprojekt alatt hozhat létre alprojektet. Viewer nem hozhat létre főprojektet/alprojektet/feladatot, és nem írhat, tölthet fel, kommentelhet vagy módosíthat tagságot.
- Admin nélküli projektcsapat/hozzáférési régi tesztet az új szabályokhoz igazítja; a last-owner védelmet megtartja.
- Új `/sync/access-scope` endpoint tagság+szerep fingerprinttel; kliens a látható/online fülön 12 s-ként frissít, scope-változáskor teljes újratöltés. Első offline-first betöltés változatlan.
- Hat új PostgreSQL regressziós teszt: privilege escalation, szerkesztői határok, régi privát projekt adatmegőrzése, tagságváltozás/tiltás, kívülálló, inaktív admin.
- Nincs M8 telepítés, 18086/18090 módosítás, Gmail írás, valós useradat migráció vagy admin/admin jelszó.

## Még szükséges elfogadási kapuk
Full Pi Docker frontend TS/ESLint + 112 Vitest, PostgreSQL 109 pytest. A tesztkapu nem bizonyít élő böngészős kétfiókos viselkedést vagy teljes adat-migrációt. A megtekintő által régebben létrehozott projektek admin számára való megjelenítését és a revokációt élesítés előtt böngészőből is tesztelni kell. A teljes ACL/UI felülvizsgálat még nyitott lehet a már létrehozott, eltérő tulajdonú objektumoknál.
