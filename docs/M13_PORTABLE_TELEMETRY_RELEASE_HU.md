# M13 – Linux CPU/RAM + Docker erőforrásmérés: ellenőrzött kiadási jelölt

**Dátum:** 2026-10-31.

**KÉSZ A FEJLESZTŐI ÁGON; A PI-N MÉG NEM AKTÍV.**
A korábbi, működő M12 Pi MCP-t, FieldWorköt, staginget,
Docker-projekteket, PostgreSQL-köteteket és tunnelt
ez a fejlesztési mérföldkő **nem módosította**.

## Új MCP végpontok

1. `fieldwork_mcp_host_metrics` (`{}`): a futó Linux agent
   által látott `/proc/meminfo`, `/proc/stat`,
   `/proc/loadavg` alapján memória, swap, load,
   és ~0,4 másodperces **kétpontos** CPU-kihasználtság.
   `MemAvailable`-t használ, nem a félrevezető
   `MemFree` adatot. A memória `procfs_visible_to_agent`
   mérési hatókörű, nem bizonyított fizikai összmemória.
2. `fieldwork_mcp_container_stats` (`{}`):
   kizárólag a rögzített
   `/usr/bin/docker --host unix:///var/run/docker.sock
   stats --no-stream --format '{{json .}}'`
   lekérdezés. Minden futó konténer CPU-ja
   (egy CPU-mag százalékában, akár 100 feletti érték)
   és memóriája bájtban. Nincs tetszőleges parancs,
   konténernév-/ID-bemenet vagy mutáló Docker-művelet.
   Bounded stdout (200 KiB), maximum 96 konténer,
   18 s CLI timeout és fail-closed hibakezelés.
   Az idegen konténerneveket kitakarja, Docker
   label/image/mount/env/argv nem jelenik meg.

A mag (`updater/linux_telemetry.py`) Raspberry Pi- és
Orange Pi-független, csak a Linux `/proc` fájlrendszert
használja. Opcionális Docker: ha nincs Docker, a
host CPU/RAM eszköz ettől függetlenül működhet.
A per-process PID/top és a cgroup limit részletes
megkülönböztetése a további mérföldkő része.

## Biztonsági korlát és update-scope

A `updater/mcp_linux_telemetry_overlay.py` kizárólag
az aktív, tényleges Pi M12 `fieldwork_mcp.py` pontos
`ee218971079b988e1e85b3790dd50228847e5e911e2e688b3df77972ad78b532`
SHA256-ára épít; eltérő main esetén azonnal STOP.
Egyszeri, pontos import- és regisztrációs horgonyt
követel; hozzáadja a **két read-only toolt**, nem
változtatja meg az MCP korábbi 36 eszközének
működését és a mutáló műveleteket jelölő allowlistet.

`updater/mcp_linux_telemetry_activate.py` csak lokális
operátori jóváhagyással aktiválhat:
- pontos Git commit (40-hex) + minden letöltött modul
  külön SHA256-ja, redirect tiltva;
- a források és új MCP AST-jének fordíthatósága
  írás és jóváhagyáskérés előtt;
- egyetlen `ENGEDÉLYEZEM_M13` helyi consent,
  meglévő sudo engedély a már futó
  `fieldwork-pi-tunnel.service` restartjára;
- kizárólag `~/.local/share/fieldwork-pi-mcp/v0.6.1`:
  `fieldwork_mcp.py` SHA-pinnelt cseréje és két
  új modulfájl (`linux_telemetry.py`,
  `mcp_linux_telemetry.py`).
- 0600 atomikus forrásbackup és receipt,
  `/readyz` ellenőrzés és automatikus rollback
  sikertelen restart/health esetén; új tunnel nincs.
- nincs távoli privilege-escalation, root-telepítés,
  Docker stop/rm/prune vagy éles FieldWork-írás.
- a 36 meglévő MCP-eszköz + az új két eszköz
  live discoveryje **külön elfogadási kapu**.
  Nem állítunk `38/38 PASS`-t a Pi-próba előtt.

## Elvégzett tesztek és határuk

| Ellenőrzés | Eredmény |
| --- | --- |
| [Teljes CI #41218236454](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41218236454) | **586 updater + 12 bootstrap = 598/598 PASS** |
| [Natív Linux ARM64 #41218149384](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41218149384) | **PASS**, valódi ARM64 `/proc` |
| [Valódi Docker #41218149408](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41218149408) | **PASS**, élő Linux Docker daemon, izolált CI |
| Egyetlen lokális consent + backup/rollback unit | PASS, külön temp-homedir |
| Pi aktuális M12 main SHA | korábban élő Pi MCP-vel ellenőrizve |
| Pi M13 frissítés + új toolok tényleges meghívása | **NOT RUN** |
| Orange Pi telepítés és HA read-only adapter | **NOT RUN** |

Ezek az eredmények NEM bizonyítják, hogy az Orange Pi-n
már fut vagy hogy egy konkrét Raspberry Pi mérés kész.
Az ARM64 GitHub runner nem azonos az Orange Pi-vel.

## Változatlan kiadási jelölt / integritás

`updater/mcp_linux_telemetry_activate.py`
SHA256: `df6c295e2be9d509c52f1baea66ea0ed5f94f990ac5ddbb700e22aa3540e061d`

Immutable release commit:
`5d53a03d5154ed8b307f5b8baebbf2ef5f88f98f`

Modul SHA256 értékek:
- `linux_telemetry.py`:
  `40de0c1807be2f25052b6433130c412dfafeffc83bbe5cd2d935c3e25d73652f`
- `mcp_linux_telemetry.py`:
  `c7539b8abb0c0a9530441fe3c8f885dde406d21c764694c1d204362752dcff6b`
- `mcp_linux_telemetry_overlay.py`:
  `8cc573ce7707e7e70744de94861ad95f5ac7e08f99203ea97020f4d7bdf240e7`

Az alábbi parancs **csak egy későbbi, kifejezett
helyi aktiváláshoz van dokumentálva**; itt nem futott,
nem kértünk újabb parancsmásolást a felhasználótól:

```sh
python3 -c 'import hashlib,urllib.request;u="https://raw.githubusercontent.com/misssska/fieldwork-pi-mcp/5d53a03d5154ed8b307f5b8baebbf2ef5f88f98f/updater/mcp_linux_telemetry_activate.py";b=urllib.request.urlopen(u,timeout=20).read(200001);assert len(b)<=200000 and hashlib.sha256(b).hexdigest()=="df6c295e2be9d509c52f1baea66ea0ed5f94f990ac5ddbb700e22aa3540e061d","M13_INSTALLER_SHA256_MISMATCH";exec(compile(b,"m13_pinned_installer.py","exec"),{"__name__":"__main__"})' --commit 5d53a03d5154ed8b307f5b8baebbf2ef5f88f98f --activate
```

**Kockázat:** egy rossz backend bootstrap vagy tunnel restart
átmeneti kapcsolatvesztést okozhat. A backup/rollback
negatív tesztelt, de a Pi valódi szolgáltatás-újraindítása
ezzel a kiadással nem tesztelt. A plugin/tool discovery
frissítése a felhasználói kliensen később kellhet.
A publikált fejlesztői PR **draft**, aktív Pi M12
továbbra is működik.
