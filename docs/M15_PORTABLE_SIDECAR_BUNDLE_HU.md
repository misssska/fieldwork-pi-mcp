# M15 – reprodukálható, hordozható Linux MCP sidecar csomag

**Dátum:** 2026-10-31. **GitHub build és tesztek: PASS.**
**Pi / Orange Pi aktiválás: NEM TÖRTÉNT.**

## Kész, ellenőrzött

Az M13–M14 modulok most először egyetlen
**determinista, SHA256-ellenőrizhető `tar.gz` csomagban**
állnak rendelkezésre. A csomag 20 konkrét,
név szerinti Python/systemd referenciafájlt tartalmaz,
köztük a saját ellenőrző és privát előkészítő kódját.

Kész források:

- `updater/m15_portable_bundle.py`:
  előre rögzített, engedélyezett forrásfájl-lista;
  kizárólag normál fájlok, symlink/path traversal
  tiltás, max. 256 KiB/fájl, 4 MiB archívum;
  canonical, SHA256-os manifest;
  gzip fejléc és tar metadata **rögzített időbélyeggel**;
  a külső archívumlenyomat és 40 karakteres
  konkrét Git commit ellenőrzése. Nincs `extractall`.
- `updater/m15_user_stage.py`:
  egy már **független forrásból hitelesített**
  csomag privát, új, 0700 felhasználói könyvtárba
  történő, helyi, egyszeri előkészítése;
  0600 fájlok, `fsync`, legvégén
  `.complete.json` állapotnyugta,
  meglévő könyvtár felülírásának tiltása;
  csak pontosan validált archívum után ír.
  Sem `root`, sem szolgáltatásmódosítás,
  MCP-frissítés, scriptfuttatás vagy Docker-művelet
  nem végezhető vele.
- `.github/workflows/m15-portable-sidecar.yml`:
  natív GitHub **ARM64 + x86-64 Linux** runner;
  offline negatív tesztek, csomagolás,
  két egymást követő build byte-azonossága,
  a két architektúra archívumainak **bitazonossága**.
  A csomag a sikeres Actions futás
  `m15-portable-ubuntu-24.04` és
  `m15-portable-ubuntu-24.04-arm`
  artifactjai között jelenik meg.
  Ezek **forráscsomagok**, nem natív APK/DEB.
- A régi systemd operátor referencia
  `python3 -I` indítását `python3 -s`-re
  javítottuk: a szomszédos (később root-owned,
  read-only telepített) Python modulok importálhatók,
  de a felhasználói site-packages tiltott.
  A natív CI ezt a belépési pontot is teszteli.

**Példakiadás, immutábilis Git commit:**
`7a4c7707219fe88ab2b3a48d3f2f724b99cd1efa`

**Ennek a csomagnak a külső SHA256 lenyomata:**
`c0057355d1d9be04ddbe89819c57d18545b76f55201e31d5d17b23dccf080fa3`

**Bizonyíték:**
[GitHub Actions – M15 két architektúra](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41227954523):
mindkét build, két build összehasonlítása és
a keresztarchitektúrás bájtonkénti összevetés PASS.
[GitHub teljes biztonsági suite](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41227957800):
**771 updater + 12 bootstrap = 783/783 PASS**.

Az újabb Actions commitokhoz **új, külön SHA256 és
kiadási commit** tartozik: a fenti fix SHA
kizárólag a fenti konkrét Git commitra vonatkozik.

## Mit NEM bizonyít még?

- Ez még **nem telepített és bekapcsolt Pi agent**:
  a build csak GitHubon futott, a forráscsomag
  lokális állapotkönyvtárba történő előkészítése
  is csak a CI izolált könyvtáraiban tesztelt.
- A publisher/aláírás hitelessége nincs megoldva:
  a SHA256 a bájtegyezést igazolja, nem
  a kiadóban való bizalmat. A letöltött archívum
  saját manifestjét nem tekintjük önmagában
  bizalmi alapnak; külön felülvizsgált pin kell.
- A jelenlegi Pi M12 MCP-nek **nincs
  gazdagép-telepítő/önfrissítő eszköze**.
  Az `artifact_*` eszközök inert tárolók,
  nem hajtanak végre host-parancsot.
  Ezt nem lehet legitim módon távoli Python
  kódfuttatássá alakítani a jóváhagyás
  megkerülésével.
- Nincs még a külön helyi operátor
  és a távolról vezérelt MCP között
  függetlenül auditált OS privilege boundary.
  A régi MCP közvetlen Docker-socket
  hozzáférése root-ekvivalens lehet.
- A reference systemd szolgáltatások még
  nincsenek Pi-n telepítve, regisztrálva,
  natív restart/rollback acceptance
  és 36 régi MCP-eszköz regressziós
  hostteszt nincs; stage/sandbox lifecycle
  migráció sem kész.
- A későbbi telefonos jóváhagyáshoz
  külön hitelesített és TLS-es hálózati
  közvetítő szükséges; a csak loopbacken
  működő UI-t nem tesszük ki LAN-ra.

## Tényleges következő kapu

**M15-B**: egyszeri, **valóban helyileg jóváhagyott**
host bootstrap egy külön, nem privilegizált
MCP operátor felhasználóhoz és szűk
service-helperhez, előbb emulált Linux-hoston,
majd csak a valós Pi független preflightja
után. Csak ezt követheti az M13 telemetria
és az M14 frissítő bekapcsolása a Pi-n.

A felhasználói cél változatlan:
**minden későbbi frissítés egy jóváhagyással,
SSH-parancsok és ZIP-másolgatás nélkül**.
Az M15 csomagolás fontos mérföldkő,
de önmagában ezt még nem teljesíti.
