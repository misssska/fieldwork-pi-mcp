# Rögzített GitHub-források — 2026-10-30

## Frissítés-előkészítő (bootstrap)

**Git commit:** `88e7995aeee01ea3612f1b8e8a235eaccb93ba08`

| Fájl | SHA-256 |
|---|---|
| `bootstrap/bootstrap.py` | `cce08bda986e21ee61d058013a20e652ad604765ac9c89bd7df1383b25a668d9` |
| `bootstrap/manifest.json` | `fe41094c55b7b227ff2bfef972cef4cadc7c52a59dce0dbf7f101db9b2b6540d` |
| `updater/stage_release.py` | `0bb65fada3e76add4aef209441f0fd46d233718d21fe36bbb2a59acea37002b6` |
| `updater/compatibility.py` | `ef8940996be6fe5f6e2e5a5567e51ae42f2a0a4e8a10cf306261e7b8b80b3b0e` |
| `updater/async_overlay.py` | `0a0591f2414194fcf64e70274ab53a08fceb130f90d3afd650530ea06ab44afd` |
| `updater/qualification.py` | `c0f6f4e22b09f22f54b2b8ddc2fd79cc66b33f061968aba9af60fe49aa84a66b` |

## Async Stage r2 (változatlan, ellenőrzött kiadás)

**Git commit:** `b59066526b433ceab124dc1b01dd192f74825c76`

| Fájl | SHA-256 |
|---|---|
| `release/stage_async.py` | `add1db45504e53af0663bc7432d893a35819b8fcf6acc057451182c7f1dca964` |
| `release/async_overlay.py` | `0a0591f2414194fcf64e70274ab53a08fceb130f90d3afd650530ea06ab44afd` |

**Figyelem:** a GitHubon publikált modulok még nem aktívak a Pi-n. A bootstrap kizárólag előkészít; a qualification kizárólag olvas és ellenőriz. Egyik sem telepít vagy indít újra szolgáltatást.

A Pi-n jelentett MCP-főfájl SHA-256: `7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04`. A tényleges Pi-forrás ellenőrzése és helyben jóváhagyott aktiválás még hátravan.
