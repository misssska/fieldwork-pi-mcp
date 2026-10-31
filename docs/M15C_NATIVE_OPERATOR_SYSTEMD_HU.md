# M15-C – külön Unix-identitású, systemd-vel indított jóváhagyó: natív elfogadás

**Dátum:** 2026-10-31. **GitHub disposable natív ARM64 + x86-64: PASS.**
**Éles Raspberry Pi / Orange Pi systemd telepítés: NEM TÖRTÉNT.**

## Mit sikerült most ténylegesen ellenőrizni?

A [M15-C Actions #41230921612](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41230921612)
mindkét natív Linux architektúrán:

1. A pontos commit/SHA-pinnelt M15 sidecar forrásmodulokat
   valódi root tulajdonú, csak olvasható fájlokként telepítette
   a **kizárólag ideiglenes GitHub runner** `/opt/linux-mcp-operator`
   könyvtárába.
2. Előbb külön nem root Unix-identitással indította a valódi
   telepített Python alkalmazást; ellenőrizte a konfigurációt,
   a lokális HTTP 401/200 válaszokat, a rossz CSRF tiltását,
   az **újra fel nem használható** HMAC-nyugtát, a folyamat
   megszűnését és a **8767-es port tényleges felszabadulását**.
3. A hoston létrehozott egy saját, nem root
   `linux-mcp-operator` szolgáltatásfelhasználót, amely
   különbözik a távoli MCP-t utánzó CI runner felhasználótól.
   Privát 0700 állapotkönyvtár és 0600 operátori
   hitelesítő/HMAC-fájlok. A CLI `--check` valódi
   identitással és konfigurációval PASS.
4. A már meglévő `deploy/systemd/linux-mcp-operator.service`
   szigorított referenciaegységet a tesztgép
   **csak ideiglenes** `/run/systemd/system/m15c-operator-smoke.service`
   helyére regisztrálta. `systemd-analyze verify`,
   `systemctl start` és `systemctl is-active` PASS.
   Érvénytelen HTTP Basic hitelesítésre 401, helyesre
   200; a tartalom nem tartalmazza a HMAC-secretet.
5. `systemctl stop` után a tesztszolgáltatás megszűnt;
   az átmeneti systemd-egységet leállította/törölte,
   a daemon konfigurációját újraolvasta, és a pontos
   M15-B root-owned inaktív telepítést
   **ellenőrzött rollback** eltávolította.
6. A Pi éles FieldWork/M12 és Docker környezete
   **nem része** a GitHub tesztnek. Nincs távoli
   telepítés, Pi-s sudo, éles tunnel-restart,
   konténerstop, volume törlés vagy SSH-parancsmásolás.

## Feltárt valós hibák és javításuk

- **Python import az izolált indításnál:** a korábbi
  `-I` elrejtette a telepített szomszédos modulokat.
  A külön `-s` indítás már korábban javítva.
- **Tesztindító árva gyermekfolyamata:** a `runuser`
  szülőfolyamat megszüntetése nem állította le feltétlenül
  a mögöttes HTTP Python-folyamatot. A natív teszt
  `setpriv` közvetlen `exec` indításra váltott,
  és külön megköveteli a port felszabadulását.
- **Valós systemd EADDRINUSE / errno 98:** a rövid HTTP
  kapcsolatok utáni TCP TIME_WAIT miatt az
  `allow_reuse_address=False` gyors szolgáltatás-
  újraindításkor blokkolt. A helyi szerver
  `SO_REUSEADDR`-t enged, de
  **`SO_REUSEPORT` továbbra is tiltott**.
  Külön HTTP negatív teszt bizonyítja, hogy két
  egyidejű szerver nem hallgathat ugyanazon a porton,
  viszont azonnali újraindítás lehetséges.
- A journal diagnosztikája csak a numerikus OS errno-t
  írja ki, nem naplózza a privát tervet, kulcsot
  vagy hitelesítő adatot.

## CI bizonyíték, releváns hatókör

| Kapu | Státusz |
|---|---|
| [M15-C natív systemd futtatás](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41230921612) | **PASS ARM64 + x86-64** |
| [M15 hordozható archívum](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41230921565) | **PASS két architektúra / byte-identikus** |
| [Teljes biztonsági teszt](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41230968083) | **792/792 PASS** |
| [M14 natív frissítőkapu](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41230964457) | **PASS ARM64 + x86-64** |
| Valós Raspberry Pi/Orange Pi telepítés | **NOT RUN** |

**Figyelmeztetés:** a CI-jóváhagyás szintetikus.
Nem bizonyítja, hogy az ember fizikailag jelen volt,
és nem tartalmazott éles forrásfrissítést.
A CI gépen külön UID-k voltak, de a runnernek lehetett
Docker root-ekvivalens hostképessége. Ezért az OS
szétválasztás tesztje **nem helyettesíti**
a valódi Pi független UID/GID/sudo/Docker auditját.

## Éles aktiválás blokkolói

- A már működő M12 távoli MCP jelenlegi host
  csoportjait, Docker socketjét, sudo-jogát és
  más root-ekvivalens útvonalait nem sikerült még
  függetlenül bizonyítani vagy korlátozni.
  A 36 MCP-funkció stage/sandbox regresszióját
  e jogok megvonása előtt el kell végezni.
- A publisher/commit külső megbízhatóságát,
  a valódi user-owned credential provisioningot
  és a helyi approver/executor közötti OS-biztonsági
  határt **nem** bizonyítja az M15-C szolgáltatásteszt.
- A localhost-only HTTP Basic sem biztonságos
  telefonos jóváhagyásra önmagában; külön TLS/auth
  proxy, device pairing és re-auth szükséges.
- A jelenlegi M12 36 eszköze között nincs
  általános host-bootstrap, és az inert
  `artifact_*` tárolás nem távoli host-executor.
  A biztonsági kapuk megkerülésére nem használjuk.
- Eltérő Linux rendszereken (systemd nélküli
  disztribúciók) külön supervisor adapter kell;
  a közös Python-mag ARM64/x86-64-en hordozható.

**Következő műszaki feladat:** a Pi valódi
host privilege auditja, külön szűk stage/sandbox
helper integráció és a **helyileg, egyszer
jóváhagyott** service bootstrap release-gate,
a működő M12 megőrzésével.

A felhasználó célja továbbra is az, hogy a
**későbbi frissítésekhez ne kelljen ZIP-eket és
SSH-parancsokat bemásolni**. M15-C most az
elkülönített systemd szolgáltatás natív működését
bizonyítja, még nem az éles no-copy frissítést.
