# SHA-256 rögzítésű lifecycle kiadáscsomag — csak offline review

Dátum: 2026-10-30. **Kísérleti jelölt: nem telepítő, nem operatív release.**

## Mit old meg?

A korábbi kétmodulos Async Stage-frissítés előkészítője nem tudta a
Schemafix-r1-re épülő, **négy futásidejű fájlból** álló kiadást kezelni.
Az `updater/lifecycle_release_builder.py` most kizárólag memóriában
összeállít egy determinisztikus ZIP-et:

- `fieldwork_mcp.py`: a Schemafix-r1 forrásra alkalmazott két ellenőrzött overlay
- `stage_async.py`
- `stage_inspect.py`
- `stage_start_async.py`
- `lifecycle-release.json`: SHA-256 fájllista és kötelező tiltó jelzők

Az overlay-kód maga nem kerül a futásidejű ZIP-be. Az öt korábban jóváhagyott
forrásmodult az `experimental/lifecycle_manifest.json` **pontos**
`d500da3872ff05c22cefbc75fa8091fc30e39471a634926e127e3a48d13a1c0e`
SHA-256 értékéhez köti. Ezt nem helyettesítheti a hívó által készített
tetszőleges manifest. A fájlok saját SHA-256 értékét, AST-szintaxisát és
a két overlay helyi implementációval való egyezését az
`experimental/lifecycle_qualification.py` ellenőrzi.

A főfájl eredeti forrás-hash:
`7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04`.

Az elvárt, összeállított lifecycle-főfájl SHA-256:
`b9d449ba2802b2f13e8e09252cdcf593007f3aeadfebe06010fa01ac2f5a62a5`.

A ZIP-ben csak fix nevű, nem végrehajtható (`0600`) fájlok vannak.
Nincs útvonalbejárás, symlink vagy váratlan állomány. A ZIP azonos
bemenetre bájtra azonos, mivel a sorrend és a ZIP-időbélyeg rögzített.

## Tesztek

```bash
python -m unittest discover -s tests -p 'test_lifecycle_release_builder.py' -v
python -m unittest discover -s tests -p 'test_*.py' -v
PYTHONPATH=bootstrap python -m unittest discover -s bootstrap/tests -p 'test_*.py' -v
python -m compileall -q updater bootstrap experimental
```

A kiadásépítő tesztek **szintetikus/mockolt qualification bemenetekkel**
futnak: determinisztikus ZIP, fájlcsere, hibás jogosultság, rossz hash,
ZIP path traversal, duplikált fájl, helytelen manifest, szintaktikai hiba
és jogosulatlan flags ellen véd. **A GitHub CI nem tartalmazza a három
korábbi eredeti ZIP-et**, így a valós, teljes release ZIP ténylegesen
még nem épült meg a CI-ben, nem telepítettük.

A korábbi helyi forrásvizsgálat viszont már igazolta a megőrzött
Schemafix-r1 kiadási fájlt és az overlay-eredmény SHA-256 értékét.

## Nem összetévesztendő az aktiválóval

A builder sem a Pi-n lévő telepítési könyvtárhoz, sem Dockerhez,
systemd-hez, tunnelhez, production adatbázishoz nem fér hozzá.
Nem írja fájlba az archívumot, nem futtatja a benne lévő kódot.
Az elkészült ZIP metaadataiban:

```json
{
  "activation_authorized": false,
  "mcp_modified": false,
  "production_modified": false,
  "real_pi_readiness_verified": false,
  "tunnel_restarted": false
}
```

## Következő elengedhetetlen kapuk

1. A Pi **aktuális** telepített MCP-főfájl hashének lokális megerősítése.
2. A tényleges runtime fájlokkal végrehajtott teljes Pi ARM64 teszt.
3. Az operátori, kifejezett **helyi** engedélyt kezelő, szűk jogosultságú
   aktiváló megírása és független ellenőrzése.
4. Crash/reboot utáni valódi rollback, régi tunnel megőrzése, MCP discovery
   és health-check: mind PASS az elfogadáshoz.
5. Csak ezután az új staging `ps -a` diagnosztika használata és
   a `STAGE_HEALTH_FAIL` gyökerének felderítése.

A jelenlegi eszközökön keresztül az éles MCP saját hostfájljainak
távoli módosítása nem megengedett. A csomag összerakása
**nem** egyenlő a telepítés felhatalmazásával.
