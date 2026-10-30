# Rögzített GitHub-források — 2026-10-30

## Frissítés-előkészítő (bootstrap)

**Git commit:** `0c7a83228e5969c2eae959798beda883bb9f9ad5`

| Fájl | SHA-256 |
|---|---|
| `bootstrap/bootstrap.py` | `cce08bda986e21ee61d058013a20e652ad604765ac9c89bd7df1383b25a668d9` |
| `bootstrap/manifest.json` | `76e2097efdb05bfd1a87a413f363ec9837183d51f4bd858a3b00d4ee88242191` |
| `updater/stage_release.py` | `eb4324ed13542b63a5dab0edc3183fc256fe095a5e21e07c426c507f61a524e6` |
| `updater/compatibility.py` | `ef8940996be6fe5f6e2e5a5567e51ae42f2a0a4e8a10cf306261e7b8b80b3b0e` |
| `updater/async_overlay.py` | `0a0591f2414194fcf64e70274ab53a08fceb130f90d3afd650530ea06ab44afd` |
| `updater/qualification.py` | `16fb56d5afdc412360bf4d62261d6794d2029597520392710ca7cbea9877784a` |

## Async Stage r2 (változatlan, ellenőrzött kiadás)

**Git commit:** `b59066526b433ceab124dc1b01dd192f74825c76`

| Fájl | SHA-256 |
|---|---|
| `release/stage_async.py` | `add1db45504e53af0663bc7432d893a35819b8fcf6acc057451182c7f1dca964` |
| `release/async_overlay.py` | `0a0591f2414194fcf64e70274ab53a08fceb130f90d3afd650530ea06ab44afd` |

**Figyelem:** a GitHubon publikált modulok még nem aktívak a Pi-n. A bootstrap kizárólag előkészít; a qualification kizárólag olvas és ellenőriz. Egyik sem telepít vagy indít újra szolgáltatást.

A Pi-n jelentett MCP-főfájl SHA-256: `7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04`. A tényleges Pi-forrás ellenőrzése és helyben jóváhagyott aktiválás még hátravan.
