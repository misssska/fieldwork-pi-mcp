# FieldWork Pi MCP

A Raspberry Pi-n futó FieldWork MCP biztonságos, ellenőrizhető fejlesztése és frissítése.

## Állapot — 2026-10-30

- **Kész a GitHub-alapú frissítés előkészítő komponense**: `updater/stage_release.py`.
- A komponens kizárólag rögzített Git commitból, ellenőrzött SHA-256 hashértékekkel tölt le, és privát staging könyvtárba ment. **Nem telepít és nem indít újra semmit.**
- Elkészült az offline biztonsági tesztcsomag és a GitHub Actions tesztfolyamat. A GitHub Actions futás eredményét külön ellenőrizni kell.
- **Nincs még telepítve a Pi-re.** A korábbi r2 telepítés helyesen megállt: a Pi-n telepített `fieldwork_mcp.py` SHA-256 értéke eltért a csomag által elvárttól.

## Cél

A jövőben ChatGPT által előkészített és ellenőrzött frissítések GitHubon keresztül, egyszeri helyi engedélyezéssel, kézi ZIP-másolás nélkül. Az önfrissítés nem jelent korlátlan távoli shell-hozzáférést vagy automatikus éles telepítést.

## Biztonsági korlátok

- Az éles `/opt/fieldwork`, az adatbázis és a produkciós Docker-konténerek érintetlenek maradnak.
- A meglévő `fieldwork-pi-tunnel.service` megmarad; új tunnel nem szükséges.
- A Pi-n jelenleg telepített MCP-forrást előbb egyeztetni kell az új verzióval.
- A letöltés, teszt, telepítés és visszaállítás külön lépések; telepítéshez helyi jóváhagyás kell.
- Titkok, kulcsok, hitelesítők és ügyféladatok nem kerülhetnek ebbe a publikus repositoryba.

A műszaki terv: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Következő feladat

A Pi jelenlegi MCP-forrásának biztonságos, csak olvasható ellenőrzése, majd a helyben jóváhagyható, atomikus telepítő és visszaállító komponens kialakítása. Amíg ez nem készült el és nincs validálva, **ne futtass telepítőt a repositoryból**.
