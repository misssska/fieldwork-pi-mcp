# Ellenőrzött, rögzített GitHub-források

Ez a dokumentum a bootstrap és a csak előkészítő Async Stage release reprodukálható azonosítóit tartalmazza.

**Git commit:** `45e2cbe03017b52a4e83a50f8d177d958d8d986d`

| Forrás | SHA-256 |
|---|---|
| `bootstrap/bootstrap.py` | `bb952b5933a0164df93fca6dcfcf2e462c1b9a2c02005af6c828e47ded544902` |
| `bootstrap/manifest.json` | `cb96bbbe3f6b1514fa2b307f55f83f13d5c474c4ae16fc5488ff0bea3b7fcb1f` |
| `release/manifest.json` | `847b77fa819e210df6b9c4bc24bbca9039f93bc1d7ccf9f57268ca65b69ce1f8` |
| `release/stage_async.py` | `add1db45504e53af0663bc7432d893a35819b8fcf6acc057451182c7f1dca964` |

A rögzített commitban a fenti fájlok megtalálhatók. A `release/async_overlay.py` hashértéke `0a0591f2414194fcf64e70274ab53a08fceb130f90d3afd650530ea06ab44afd`.

**Állapot:** csak GitHubon publikált, még nem telepített előkészítő komponensek. A telepítésre és újraindításra szolgáló külön helyi jóváhagyási kapu hiányzik. Ez a dokumentum nem telepítési utasítás.

A Pi-n telepített `fieldwork_mcp.py` utoljára jelentett SHA-256 értéke: `7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04`. Ez nem egyenlő a korábbi v0.6.1 csomag SHA-256 értékével; forrásösszevetés nélkül semmit nem írunk felül.
