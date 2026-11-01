# M14-D – Docker-jogosultságok szétválasztása: read-only proxy és átállási kapu

Dátum: 2026-10-31. **Offline fejlesztői/CI-elfogadás PASS; Raspberry Pi / Orange Pi deployment NEM történt.**

## Mérnöki döntés

A régi FieldWork Pi MCP v0.6.1/M12 tetszőleges
host shellt **nem** kínál, de a saját belső
eljárásaiból közvetlenül használja a
`/var/run/docker.sock` végpontot.
A szokásos rootful Docker daemon socketjének
hozzáférése **gyakorlatilag host-root szintű
jogosultság** még akkor is, ha az MCP API-n
csak olvasó funkciók láthatók.

**Nem biztonságos** csupán egy külön
`linux-mcp-operator` fiókot létrehozni,
miközben a távolról meghívható MCP továbbra
is a Docker-csoport tagja vagy sudo-joggal
rendelkezik. A privilege gate emiatt
**BLOCKED**, és tényleges Pi UID/csoport
és sudo/socket audit nélkül nem tekinthető
felszabadítottnak.

## Elkészült, valóban tesztelt M14-D komponensek

- `updater/linux_docker_read_proxy.py`:
  kizárólag AF_UNIX, kötelező Linux
  `SO_PEERCRED` UID-ellenőrzés.
  A helyi, hiteles konfiguráció rögzíti a
  megengedett MCP kliens UID-t, ami
  **nem egyezhet** a külön Docker-segéd UID-jával.
  Legfeljebb 512 bájtos, egy soros JSON input.
  Kizárólag két, **fix, paramétermentes**
  művelet létezik:
  `inventory` és `resources`.
  A távoli kliens nem adhat meg tetszőleges
  Docker parancsot, konténernevet,
  filtert, image-et, hostot, mountot vagy pathot.
  A válasz sanitizált, legfeljebb 240 KiB;
  sérült vagy jogosulatlan kérés
  `DOCKER_PROXY_DENIED`.
  A `docker_inventory({})` meglévő M12
  és a `docker_stats({})` M13 fix
  read-only implementációjára épül.
- `updater/linux_docker_read_proxy_service.py`:
  nem root segéd, helyi, szűk konfiguráció,
  os.geteuid alapú ellenőrzés és
  kizárólag systemd-től örökölt
  egyetlen AF_UNIX listener FD=3.
  Nem nyit internetes vagy LAN-portot.
- `updater/linux_docker_read_proxy_client.py`:
  a jövőbeli nem privilegizált MCP
  csak a `/run/linux-mcp-docker-proxy.sock`
  rendszer által létrehozott sockethez
  kapcsolódik; nem kell közvetlenül
  a Docker sockethez férnie.
  A két műveleten kívül minden input elutasított.
- `deploy/systemd/linux-mcp-docker-proxy.socket`:
  csak referencia, nincs élesítve.
  `SocketGroup=linux-mcp-client`,
  `SocketMode=0660`, `Accept=no`,
  helyi Unix socket. **Nem** osztja
  meg a Docker csoportot a távoli MCP-vel.
- `deploy/systemd/linux-mcp-docker-proxy.service`:
  külön `linux-mcp-docker-helper` fiók,
  amely **azonban maga továbbra is
  Docker-csoport tag és ezért a standard
  rootful Docker hoston root-ekvivalens**.
  A szolgáltatás kódja root tulajdonú,
  csak olvasható telepítésben, szűk
  systemd-védelmekkel, internetes socket
  nélkül és fix parancsokkal működhet
  majd. Ennek betartását valós Pi-n
  még külön ellenőrizni kell.
- `tests/test_linux_docker_read_proxy.py`
  és `tests/test_linux_docker_proxy_service.py`:
  köztük **valós AF_UNIX socket**, Linux
  peer-credential pozitív és negatív tesztek,
  más UID, JSON mező-injektálás,
  duplikált mező, hibás művelet,
  túlméretes kérés/válasz, symlinkes
  konfiguráció elutasítás,
  read-only dispatch, kliens-socket
  integráció és szűkített systemd konfiguráció.

## Független CI bizonyíték

- [Teljes teszt](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41224188577):
  **714 updater + 12 bootstrap = 726/726 PASS**.
- [Natív ARM64 és x86-64 socket/UID teszt](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41224184762):
  **mindkettő PASS**.
- [Valódi, elkülönített Docker-daemon adatlekérdezés](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41224236700):
  **PASS** – a `inventory` és `resources`
  fix proxy-műveletek valódi, CI-ben létrehozott
  konténerre lettek lefuttatva. Ez **nem**
  a tényleges systemd socket service próba
  a Raspberry Pi-n, és nem bizonyítja, hogy
  a root-ekvivalens helper nem kompromittálható.
- A régebbi hibás CI-ket kijavítottuk,
  egy regressziós tesztben a tiltott UID
  azonnali elutasítása miatt keletkező
  `BrokenPipe` versenyhelyzetet
  teszt-műveleti sorrenddel korrigáltuk.
- **M12 éles MCP változatlan**, az M13
  host CPU/RAM továbbra sincs a Pi-n
  regisztrálva; egyetlen rendszerfelhasználót,
  socketet vagy systemd-egységet sem
  telepítettünk a valódi hostra.

## Döntő regresszió- és migrációs korlát

A fenti segéd csak **olvasási** Docker-kéréseket
szolgál ki. Az M12 meglévő
`fieldwork_stage_prepare/full_test/start/stop`,
sandbox és runtime teszt funkciói
Docker **mutáló** műveleteket igényelnek.

Ezeket nem lehet egyszerűen a fenti proxyba
„beengedni”: tetszőleges konténer- vagy
hostműveletet lehetne általa végrehajtani.
Külön, szűk scope-olt, helyben jóváhagyott
**stage és sandbox lifecycle helper**
szükséges, saját engedélyezett
projektnevekkel/azonosítókkal, tartós
jóváhagyási ledgerrel, elő- és utóállapottal,
rollbackkel és negatív tesztekkel.

**Szigorú migrációs kapuk:**

1. A Pi OS-/Docker-jogosultságainak
   hiteles, csak olvasási preflightja:
   MCP UID/GID/groups, sudoers,
   Docker/rootless/Podman és egyéb
   helyi segédek, host namespace-ek;
   jelenleg **NOT VERIFIED**.
2. A read-only proxy valódi, külön Unix
   identitásos systemd tesztje a Pi-n,
   **nem** az éles M12/socket leváltása;
   health/log, socket mód, szükséges
   csoportok és funkcióteszt.
3. M12 leltár, stage és sandbox
   **shadow/parallel regressziós teszt**
   kizárólag izolált környezetben;
   az eredeti éles M12 változatlan.
4. A stage és sandbox mutáló műveletek
   dedikált, csak helyben engedélyezett
   lifecycle helperbe helyezése,
   a meglévő 36 MCP-eszköz tesztjével.
   Különösen az éles `fieldwork` és
   a `homeassistant` konténerek
   nem kaphatnak általános stop/remove
   jogosultságot.
5. **Csak ezután** vonható meg a távoli
   MCP közvetlen Docker socket/sudo joga,
   bizonyított M12 funkcionalitás mellett.
6. Külön UID-n futó, HMAC kulcsot tartó
   operator UI és szűk lokális updater
   bevezetése, biztonságos telefonos
   auth/tunnel, end-to-end approval,
   post-deploy health és rollback.
7. Orange Pi/HA natív regressziós teszt
   azonos közös Linux-maggal, külön
   célpolicy-val. Nem feltételezzük
   hogy minden Linux systemd-t használ:
   általános adapterekhez más init
   külön további mérföldkő.

**Felhasználói elfogadás:** a normál
diagnosztikához és a későbbi frissítésekhez
ne kelljen ZIP-et, hosszú Python/SSH
parancsot másolni. Ez még cél,
**nem** már kész éles képesség.

## Rollback állapot

Minden új fájl kizárólag a PR draft
fejlesztői ágában létezik. Nincs új
helyi Pi szolgáltatás, socket, Docker
restart, user/group változtatás.
Git revert egyetlen PR-beli
fejlesztési fájlt sem érintő helyi
M12 rollbacktől független. A
telepített M12 változatlanul a
korábbi HASH-pin és funkcionalitás
alatt működik.
