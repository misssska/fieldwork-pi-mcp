# Rögzített GitHub-források — 2026-10-30

## Frissítés-előkészítő (bootstrap)

**Git commit:** `8cde531698719ae963a167fe99e0c31340ce474d`

| Fájl | SHA-256 |
|---|---|
| `bootstrap/bootstrap.py` | `3389dfc19b8691c56e3d2a59e137c813cda584d2edc8edb604de6fe116ab1f7e` |
| `bootstrap/manifest.json` | `5ba0d8a33d19684d7d3e8d6d5312956f96edf4d5377905d8f8e3e0df3d4797d1` |
| `updater/stage_release.py` | `0bb65fada3e76add4aef209441f0fd46d233718d21fe36bbb2a59acea37002b6` |
| `updater/compatibility.py` | `ef8940996be6fe5f6e2e5a5567e51ae42f2a0a4e8a10cf306261e7b8b80b3b0e` |
| `updater/async_overlay.py` | `0a0591f2414194fcf64e70274ab53a08fceb130f90d3afd650530ea06ab44afd` |
| `updater/qualification.py` | `c0f6f4e22b09f22f54b2b8ddc2fd79cc66b33f061968aba9af60fe49aa84a66b` |
| `updater/activation_plan.py` | `1f89706cdf3899fa69e15d9d0f804c940a7dfb02dd68107ca7cb367379aacee5` |

## Async Stage r2 (változatlan, ellenőrzött kiadás)

**Git commit:** `b59066526b433ceab124dc1b01dd192f74825c76`

| Fájl | SHA-256 |
|---|---|
| `release/stage_async.py` | `add1db45504e53af0663bc7432d893a35819b8fcf6acc057451182c7f1dca964` |
| `release/async_overlay.py` | `0a0591f2414194fcf64e70274ab53a08fceb130f90d3afd650530ea06ab44afd` |

**Figyelem:** a GitHubon publikált modulok még nem aktívak a Pi-n. A bootstrap kizárólag előkészít; a qualification és az activation_plan kizárólag olvas és ellenőriz. Egyik sem telepít vagy indít újra szolgáltatást.

A Pi-n jelentett MCP-főfájl SHA-256: `7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04`. A tényleges Pi-forrás ellenőrzése és helyben jóváhagyott aktiválás még hátravan.
