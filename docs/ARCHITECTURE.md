# FieldWork Pi MCP — biztonságos GitHub-frissítés

## Jelenlegi, ellenőrizhető határ

A repository jelenleg két **csak előkészítést végző** komponenst tartalmaz:

1. `bootstrap/bootstrap.py`: egyszeri, felhasználó által indított, SHA-256-tal rögzített GitHub-letöltés. Csak az `~/.local/share/fieldwork-pi-mcp/update-agent` alá ír; nem telepít és nem indít újra MCP-t.
2. `updater/stage_release.py`: egy commit SHA-hoz és manifest SHA-256-hoz rögzített Async Stage release letöltése. Kizárólag az `~/.local/state/fieldwork-pi-mcp/update-staging` alá ír. Teljes `fieldwork_mcp.py` cseréjét nem fogadja el.

3. `updater/qualification.py`: kizárólag olvasási kompatibilitás-ellenőrzés. A telepített MCP pontos SHA-256 értékét, a staging receiptet és az abban rögzített fájlhash-eket ellenőrzi; a jelölt főfájlt csak memóriában építi fel. A kimenet `STATIC_QUALIFICATION_PASS`, nem telepítési engedély.\n\nA publikált kiadás fájljai: `release/stage_async.py`, `release/async_overlay.py`, `release/manifest.json`. A `release/async_overlay.py` bájtra egyezik a tesztelt `updater/async_overlay.py` modullal.

## Megbízhatósági modell

- Csak 40 karakteres, változtathatatlan Git commit SHA elfogadott.
- A manifest SHA-256 külön, jóváhagyott érték. Minden modulnak egyeznie kell a manifest SHA-256 értékével.
- A letöltés HTTPS, kizárólag fix `raw.githubusercontent.com/misssska/fieldwork-pi-mcp` útvonalról; átirányítás tiltva.
- Fájlnév-allowlist, méretkorlát, szintaktikai ellenőrzés, szimbolikus linkek elutasítása.
- Atomikus staging könyvtár és tartós receipt a fájlok SHA-256 értékeivel; a qualification újra ellenőrzi a staged fájlok hashét. A stager semmilyen letöltött Python-kódot nem futtat.
- A Pi-n telepített forrás nem egyezik az eredeti v0.6.1 alappal. Az `async_overlay.py` kizárólag egyedi, pontosan egyező integrációs pontok mellett módosíthatna egy memóriában lévő másolatot.

## Kifejezett tiltások

- Nincs általános távoli host shell.
- Nincs jóváhagyás nélküli aktiválás, telepítés vagy tunnel restart.
- Nincs hozzáférés az éles `/opt/fieldwork` forráshoz, adatbázishoz vagy Docker-volume-okhoz.
- A `fieldwork-pi-tunnel.service` az egyetlen alagút, újat nem hozunk létre.
- A publikus repositoryba nem kerülnek jelszavak, tokenek, privát kulcsok, konfigurációs titkok vagy ügyféladatok.

## Hiányzó aktiválási kapu

Az előkészített kód **nem aktív a Pi-n**. Következő szükséges lépések: a Pi tényleges MCP-forrásának helyben ellenőrzött összevetése; teljes izolált teszt; egyszeri helyi jóváhagyással telepíthető, atomikus és visszaállítható MCP-aktiváló; ezt követően korlátozott MCP staging/status végpontok. A jelenlegi csomag még nem helyettesíti ezt.

A bootstrap helyi, offline tesztjei: 10/10 PASS. A GitHub Actions futási eredménye nincs igazolva.
