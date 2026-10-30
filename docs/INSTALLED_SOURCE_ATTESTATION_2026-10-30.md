# Telepített Pi MCP forrásazonosítása – 2026-10-30

**Állapot:** kizárólag olvasási diagnosztika, új MCP-eszköz még nincs telepítve.

Az `updater/installed_source_attestation.py` modul a Pi-n **helyileg**
futtatható, de kizárólag a saját felhasználói MCP-v0.6.1 főfájlt olvassa:

`~/.local/share/fieldwork-pi-mcp/v0.6.1/fieldwork_mcp.py`

Nem fogad tetszőleges fájlnevet, nem futtatja az MCP-kódot, nem érinti a
`/opt/fieldwork` projektet vagy a Docker/systemd szolgáltatásokat.
A kimenet **nem tartalmaz forráskódot, környezeti változókat, jelszót vagy
tetszőleges szövegliterált**. Kizárólag SHA-256, fájlméret, Python AST
ellenőrzés, néhány előre rögzített staging eszköznév statikus tuple-száma
és tiltó jelzők szerepelnek benne.

## Biztonsági ellenőrzések

- Nem root felhasználó, pontosan rögzített forrásútvonal.
- Az MCP könyvtárlánca nem lehet symlink vagy idegen tulajdonú,
  csoportnak / más felhasználónak írható könyvtár. Minden komponenst
  `O_NOFOLLOW` és `dir_fd` használatával rögzített könyvtárdeskriptoron
  keresztül nyit meg, majd újra ellenőrzi az inode-azonosságot.
- A forrás normál, felhasználó tulajdonú fájl lehet csak; symlink és
  hardlink tiltva.
- Legfeljebb 1 MB fájl; az olvasás előtt méret- és módellenőrzés.
- Fájldeskriptor-azonosság, méret és módosítási idő vizsgálata az olvasás
  előtt/után; szintaktikai AST elemzés végrehajtás nélkül.
- Minden eredményben `activation_authorized=false` és
  `mcp_modified=false`.
- A hash egyezése sem jelenti a forrás teljes biztonsági felülvizsgálatát.
  A tuple-számok sem MCP-discovery bizonyítékok.

Az előzőleg jelentett Pi SHA-256:
`7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04`.

A korábbi v0.6.1 csomag eredeti főfájljának SHA-256:
`b504460dc1477898dc048dc990e7fd432ba880926f9f063904cd6a9b085e5948`.

Az eltérés **nem oldódik fel a hash-ek összevetésétől**. A valódi
telepített forrás tételes, titokvédő összevetése és egy hitelesített
lokális jóváhagyó még szükséges; a bizonyítatlan forrást tilos átírni.

## Tesztelés

```bash
python -m unittest discover -s tests -p 'test_installed_source_attestation.py' -v
python -m compileall -q updater/installed_source_attestation.py
```

A fejlesztői izolált környezetben 17/17 teszt PASS, beleértve a
fájl és a szülőkönyvtár megnyitás közbeni kicserélését. A GitHub Actions
eredménye önálló ellenőrzési kapu. Pi-n még nem futtattuk.

A **helyi futtatás** csak a megfelelő, hitelesített repository checkout
esetén és a Pi felhasználó saját jóváhagyásával engedélyezett:

```bash
python -m updater.installed_source_attestation
```

A fenti parancs kizárólag kiolvas, de a scriptet előbb biztonságos,
SHA-256-/Git-commit-pinnelt módon kell a Pi helyi könyvtárába eljuttatni;
a GitHubra feltöltött fájl nem jelenti a Pi-re telepítést.
**Nem alkalmazunk `curl | bash` jellegű közvetlen futtatást.**

## Hátralévő aktiválási kapuk

1. Helyileg hitelesített forrásazonosítás és a tényleges Pi-fájl
   részletes, titokmentes összevetése a felülvizsgált alappal.
2. Pi-kompatibilis izolált teszt a pontosan rögzített lifecycle
   modulokra, beleértve a megszakítást és visszaállítást.
3. Külön, explicit helyi engedélyt kezelő aktiváló telepítése, saját
   belső állapotgép, kényszerített rollback, service readiness.
4. Csak ezután az új staging Docker-diagnosztika bekapcsolása.

Ez a diagnosztikai kód nem kiadás és nem helyi jogosultságpótlék.
