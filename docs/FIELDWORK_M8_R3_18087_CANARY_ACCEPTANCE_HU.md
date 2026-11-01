# FieldWork M8 R3 – első izolált böngészős canary-átvétel

**Állapot (2026-11-01):** a Pi helyi terminálja szerint teljes forrás-integráció, frontend 112 és PostgreSQL-backend 109 teszt **PASS**, M8 még nincs telepítve. Ez a dokumentum az első külön, `18087`-es canary indításának kapuja.

## Kizárólag helyi admin indítás

- GitHub forrás: `updater/fieldwork_m8_r3_first_canary_18087.py`, SHA256 `f10937a3268a1f096ca950a8e3a981f46edc97a01a9507f5bc085332c1ea9c80`. A parancsnak exact commit SHA-ra és exact fájl-SHA-ra kell hivatkoznia.
- Először `--precheck`: immutable M8 forrás `parity-m8-editor.u0ytzpgq`, 8 módosított fájl pontos SHA, 112+109 log, cleanup, Docker service/port/volume/image/config guard. Az ellenőrzés nem indít konténert.
- Csak sikeres precheck után `--launch`: külön Docker Compose projekt `fieldwork-parity-m8-r3-canary`, LAN `192.168.22.13:18087`, saját PostgreSQL és file-storage named volume. Új JWT/application signing, bootstrap admin és adatbázis-jelszó (privát 0600 fájlok), külön API és nginx image tag. Nem másolja az M6 adatait.
- Sikertelen indítás: kizárólag az M8 canary Compose-projekt `down --remove-orphans` (nincs `-v`), saját start/rollback naplók. Ismételt launch és portütközés STOP; hiba esetén diagnosztika, ne törölj/nem szerkessz vakon régi Docker volume-okat.
- A régi `18086` M6, `18090` stabil R8, `18081` staging, `/opt/fieldwork` éles kód/DB, Gmail és Google Calendar NEM célzott.

## Kötelező valós böngészős jogosultsági és funkcionális átvétel

1. Az M8 admin belép (a Pi-n, a canary saját védett állományában tárolt új belépési adatokkal); két külön worker fiókot készít.
2. Admin létrehozza az A projektet, másik worker létrehozza a B projektet. Az admin számára az explicit megosztás nélküli B projekt továbbra sem feltétlenül látható, mert az `admin` nem automatikus globális projektolvasó.
3. Admin a Csapat felületen egy worker fiókhoz az új globális `editor` rendszerszerepet adja: A+B projektek és feladatok látszanak; az A/B projektbe NEM írhat, ha ott nincs külön `ProjectMember(owner/editor)`.
4. A projektgazda az aktív felhasználók **kereshető, e-mail begépelése nélküli** listájából a globális editort az A projekthez `editor` tagsággal hozzáadja; most A-ban módosítás megengedett, B-ben továbbra is tilos.
5. Ugyanez megtekintővel: saját projektbe nem tagként nem jut be; tagság után olvas, de POST/PUT/DELETE/komment/fotó/dokumentum/videó feltöltése tilos. A globális editor olvasási joga nem ad automatikus csapatkezelést.
6. Két külön böngészővel vagy privát ablakokkal A feladat módosítása után a másik fiókban kézi Frissítés gomb nélkül, látható/online lapon megjelenik. Cél 12–15 s, hálózati hibával késhet.
7. Admin visszavonja a globális editor-jogot, illetve a projektgazda elveszi az A-tagságot: az aktuális böngésző önműködően új jogosultsági scope szerinti adatokat tölt, a védett PDF/video HTTP-kérés már 403/404, az offline, korábban ténylegesen letöltött bájtok utólagos törlése nem garantált.
8. PDF (különösen többoldalas műszaki alaprajz) lapozható/nagyítható, MP4/WebM projektdokumentumként feltölthető és ahol a kodek támogatott, lejátszható. Nincs 100 MB-nál nagyobb videó; fájl a külön canary saját volume-jában marad.
9. Minden egyes szerepváltás után azonosítani kell a felhasználói nézetet, a jelenlegi szerepkört és a hozzá tartozó projektjogot. Ha bármi váratlan, nincs `18090` gateway-promotion.

**Elfogadási kapu:** 112+109 natív teszt PASS + 15 local script gate PASS + CI ARM64/x86 PASS + `18087` health HTTP 200 + a fenti browser-mátrix minden kötelező művelete PASS; az M6 és R8 működik, production érintetlen.

## Nem végrehajtott műveletek

E dokumentum és a canary-indító GitHubra rögzítése **nem telepíti** az M8-at, nem hoz létre felhasználókat, nem küld Gmailt, nem módosít naptárat, és nem aktivál automatikus e-mail-importot.
