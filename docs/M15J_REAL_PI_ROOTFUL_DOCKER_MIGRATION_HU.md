# M15-J – valós Raspberry Pi rootful Docker-szétválasztási döntés és biztonságos átállási terv

**Dátum: 2026-10-31. Bizonyított valós Pi-mérés alapján. CSAK TERV; nem telepítés és nem engedély a jogosultságok módosítására.**

## 1. Mért tények (M15-I + Pi host stdout)

A felhasználó közvetlenül, a Pi admin SSH-termináljából mérte:

| Bizonyíték | Mért érték |
|---|---|
| Host | `fieldwork`, aarch64 Raspberry Pi |
| `/var/run/docker.sock` | valódi Unix socket, UID 0, GID 985, `0660` |
| `dockerd` | PID 1102, eUID 0 (root) |
| `containerd` | PID 1079, eUID 0 (root) |
| `docker info SecurityOptions` | `seccomp=builtin`, `cgroupns`; rootless nincs listázva |
| Tunnel systemd | `fieldwork-pi-tunnel.service`, `User=admin`, active |
| Tunnel PID | 2448065, PPID 1, eUID/eGID 1000 |
| MCP Python PID | 2448133, PPID 2448065, eUID/eGID 1000 |
| `admin` csoportok | `docker`, `sudo` és más rendszer-csoportok |
| MCP M15-I | `DAC_WRITE_POSSIBLE`, `docker_group_membership_observed=true`, `root_equivalent_indicator_present=true` |
| MCP CapEff, NoNewPrivs | eff. capabilities = 0, NoNewPrivs = true |
| MCP sudo policy | `SUDO_POLICY_LISTED_REVIEW_REQUIRED`; teljes sudoers felülvizsgálat hiányzik |
| M15-E forrás telepítés | `/opt/linux-mcp-operator/linux_approval_redeemer.py` root UID 0, `0444`, inaktív, nincs user/HMAC/service |
| Production API, stage | HTTP 200 / `STAGE_HEALTH_PASS` az utolsó ellenőrzéskor |

A rendszer nem rootless: a rootként futó Docker daemon `0660` socketét az MCP által is használt `admin` felhasználó eléri.
Az MCP korlátozott tool-végpontjai NEM bizonyítják, hogy nincs később kihasználható Python/processz-szintű sérülékenység. Ha a Docker socket elérhető, a tetszőleges Docker API-kérés root-egyenértékű lehet. `NoNewPrivs` nem teszi a Docker socketet biztonságossá.

**M15-E kulcs, approver, remote M12 cutover és docker group revoke: BLOCKED.**

## 2. Valóban meglévő funkciók / mi nem helyettesíthető

Az élő MCP v0.6.1 Python moduljai:
- `fieldwork_mcp.py` SHA256 `ee218971079b988e1e85b3790dd50228847e5e911e2e688b3df77972ad78b532`;
- `runtime_runner.py` SHA256 `ae0387aed34768a7260cf01e6c1ff9d4620c506c37e7ae2a74706f661ee2db6c`: izolált sandbox Docker (image, hálózat, DB, teszt / cleanup);
- `sandbox_command.py` SHA256 `5a4a6ba775f7fd16d0660a654eb3ab8724659ff1ac72fd1427ed3c9eadb797f5`: izolált caller-authored shell csak disposable konténerben, NEM host shell;
- `stage_manager.py` SHA256 `0a04c40a00ccc940e50d590cf6b01f75c7a803dd228cb24b916fad44e046a7e6`: tracked HEAD / stage build / full-test / stage lifecycle / logs / synthetic credentials.
- A legacy M12 `fieldwork-pi-tunnel.service` **ugyanazon admin UID alatt** indítja az MCP Python-folyamatot; kizárólag MCP Python UID váltására írni egy új systemd unitot NEM elég az egész remote folyamatlánc hiteles és működő cseréjéhez.
- Korábbi M14-D read-only Docker-proxy = részfeladat.
- Korábbi M14-E/M15-G = **csak három már létező** `fieldwork-stage` Compose-labelhez kötött konténer start/stop; nincs Compose up/build, Docker run/network/volume, sandbox paritás, és nincs integrált valódi M15-E emberi jóváhagyás. **Tilos teljes M12 helyettesítőnek nevezni.**

## 3. Célarchitektúra – nem ugyanaz, mint az éles állapot

1. `fieldwork-mcp` **külön új OS UID** a távoli tunnelen fogadott MCP request végrehajtására, amely sem `docker`, sem `sudo`, sem root/elevated helper-csoport tagja, és nem örököl Docker FD-t, rootful API TCP socketet vagy kulcsot. A tunnel-child indítását, service ExecStart / HOME / tunnel credential / restart és status működését előbb lezárt staging változaton igazolni kell.
2. `fieldwork-docker-helper` **másik UID**, szükség esetén root-equivalent Docker hozzáféréssel, de csak szigorúan verzionált, rögzített Unix AF_UNIX socket / SO_PEERCRED ügyfeleknek és teljes, explicit műveleti szabályokkal. A helper maga root-ekvivalens biztonsági határ; egy tetszőleges raw Docker CLI átjáró, Docker-socket bind-mount vagy unrestricted Compose YAML sem elfogadható.
3. `fieldwork-operator` **harmadik UID**, kizárólag helyi approval; nincsenek Docker/sudo jogai, sem remote MCP socketje. E UID saját privát állapotát/HMAC-ját a Docker-vezérlő helper potenciális root-ekvivalenciája miatt önmagában a DAC nem védi. A helper támadási felületét és éles forrásintegritását előbb fel kell mérni, a titkok elhelyezésére külön fenyegetési modellt és trust boundary-t kell érvényesíteni.
4. A read-only operations és diagnosztika a legkevesebb host jogot kapja; stage/sandbox írás csak fix, jóváhagyható projekten / kézzel ismert allowlisten, PID/ID/label/image/network/volume/race előellenőrzéssel.
5. Admin helyi SSH-joga megmarad, de a *távolról elérhető* tunnel/MCP már nem fut az `admin` UID-jén. **Nem távolítjuk el a dockert az admin csoportjaiból, amíg az új tunnel és összes stage/sandbox funkció nem bizonyított.**

## 4. Végrehajtási fázisok / rollback

| Fázis | Kiadandó eredmény | Kötelező PASS | Pi-éles módosítás |
|---|---|---|---|
| M15-J1 | 36 tool konkrét Docker függőségtérkép + preflight/risk | natív ARM64, x86-64 contract/unit; source hash | semmi |
| M15-J2 | korlátozott read-only proxy + stage/sandbox helper, fake Docker + Docker e2e éles forrás nélkül | teljes stage compose build/start/test/stop és sandbox run/test/cleanup, izolált hálózat és volume, rollback/replay | semmi |
| M15-J3 | inaktív, **helyileg egyszer jóváhagyott** új service/user/sockets kiadás, shadow smoke | tunnel csatlakozás, 36/36 tool szűkített működés + production read-only, no external Docker | csak jóváhagyott egységek |
| M15-J4 | explicit, előre mentett unit/credential/status rollbackkapus canary cutover | 36/36 PASS; PID/UID/PPID; rootful Docker direct DENY; host API health, stage health; reboot persistence | csak ekkor kontrollált tunnel váltás |
| M15-J5 | külön jóváhagyási titok és M15-E aktiválási kapu újraértékelése | független threat model, alt privileged channel, HMAC replay, end-to-end consent | nem automatikus |

**Negatív követelmények:** a nyilvános 36 MCP tool közül egy sem adhat raw Docker API-t, host shellt, host TCP listener socketet, általános fájlírást, service/privilege managementet vagy használható approval HMAC kulcsot. A privileged helper mindig elutasítja a véletlenszerű Docker parancsot, tetszőleges container ID-t/mountot/image-et, production labelt vagy hálózatot, hamis PID/UID-t, lejárt/replayelt tervet és minden forrás-/rendezéseltérést.

**Rollback:** előre pinelt és visszaállítható eredeti `fieldwork-pi-tunnel.service` unit/credential/source, helyi SSH admin hozzáférés, régi Docker/mount érintetlen. Nem állítjuk le a rootful Dockert és nem módosítjuk `/opt/fieldwork` production adatbázisát. Előbb új shadow unit; a régi tunnel leállítása/új aktiválása **csak explicit helyi engedéllyel**, konténer-/service-időkorlátokkal; sikertelen canary esetén megbízható helyi rollback, unit restore, korábbi tunnel újraindítás, production/status/health ellenőrzés. Ha rollback nem bizonyítható, fail-closed és STOP.

## 5. Döntés / amit NEM teszünk

- **Ne:** `sudo gpasswd -d admin docker`, `deluser admin sudo`, `chmod 000 /var/run/docker.sock`, Docker daemon restart, `systemctl disable --now docker`, `docker compose down`, új approver-key, vagy M15-E service `enable`. Ezek jelenleg vagy megszakítanák a működő távoli kapcsolatot, vagy hamis biztonságérzetet adnának.
- A telepített M15-E `0444` **source only**, nem active authority.
- Rootless Docker általánosan reális alternatíva, de külön daemon/sock/context/port/network/storage migráció, production rootful Docker mellett önmagában nem védi a távoli MCP-t; most nem csúsztatjuk bele a FieldWork production útvonalába.
- A Pi hoston még hiányzik a `sudo -l -U admin` szabályok kontextusa, systemd tunnel `ExecStart`/cred tárolás és alternatív privileged socket/fd bizonyítéka. Ezeket csak megbízható helyi admin vizsgálatból, titkok kiírása nélkül szabad eldönteni. A mért PID-ek később változhatnak.

**Go/no-go:** 2026-10-31: `M15J_CUTOVER_BLOCKED_PROVEN_ROOTFUL_DOCKER`, `M15E_ACTIVATION_BLOCKED`, `PRODUCTION_UNCHANGED`.

Forrás: mért Raspberry Pi terminálkimenetek és az élő FieldWork Pi MCP read-only AST és Docker inventory. Folyamatadatot az MCP saját beszámolója nem igazolhat; a döntés alapja független helyi Linux kernel-/systemd-/Docker mérés volt.


## 6. M15-J1/J2 tényleges megvalósítási eredmények (2026-10-31)

**Két új, a valódi Pi-től szigorúan elkülönített fejlesztési eredmény.** Mindkettő
GitHub Draft PR-en van; egyetlen `/opt/fieldwork`, Docker-, host systemd-
vagy tunnel-műveletet sem hajtott végre a Raspberry Pi-n.

### J1 – 36/36 MCP-eszköz külön jogosultsági mátrixban

`updater/m15j_exact_mcp_contract.py` rögzíti a távolról ténylegesen
lekérdezett M12 v0.6.1 **pontosan 36 MCP-eszközét**, valamint a jelenlegi
`fieldwork_mcp.py`, `stage_manager.py`, `runtime_runner.py` és
`sandbox_command.py` SHA256-ját. A működési elosztás:
- `no_docker`: **26** eszköz; saját lokális állapot-/adatkezelés,
  sem általános Docker API, sem host rootful végrehajtás nem szükséges;
- `docker_read_proxy`: **5** eszköz; szűkített, csak olvasási Docker-adat;
- `stage_compose_helper`: **3** eszköz; full test, start, stop.
  A régi M14-E/M15-G háromkonténeres start/stop **nem elég**;
- `sandbox_helper`: **2** eszköz; runtime test és sandbox command.
  Hálózat, opcionális DB, konténerfuttatás, erőforrás-törlés,
  hiba/replay idempotencia mind szükséges.

`tests/test_m15j_exact_mcp_contract.py` **13** negatív és pozitív tesztje
érvénytelen toolkatalógus, duplikátum, rossz útvonal,
forrás-SHA drift, hiányzó shadow-nyugta, hamis PASS és
hiányzó OS privilege attestation esetén blokkol.
A teljes 36/36-os szintetikus nyugta **nem ad**
`cutover_authorized=true` értéket: ez nem
jogosultság-engedély, csak kompatibilitási ellenőrzés.

[Native ARM64 + x86-64 J1 #41239151975](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41239151975):
**PASS mindkét architektúrán**.

### J2 – valós Docker konténeréletciklus elkülönített tesztgépen

`updater/m15j_disposable_docker_canary.py` **nem az éles Pi toolja**.
Egy kizárólag lokális CI-helperből hívható, rögzített
Docker CLI-argumentumokkal:
- csak pontos OCI digestből induló, `/bin/true` canary;
- `--network none`, read-only rootfs, `cap-drop ALL`,
  `no-new-privileges`, korlátozott CPU, RAM, PID,
  UID/GID `65534:65534`;
- sem `--privileged`, host mount, host port, host network,
  Docker-socket mount, eszközátadás, tetszőleges entrypoint,
  source- vagy shell-argumentum nincs;
- `create → (exact container ID+name+label inspect) → start →
  wait exit 0 → inspect → full ID/owner ellenőrzés → rm --force`;
- a konténerazonosság megváltozása esetén elutasítja a törlést;
  meg nem figyelhető Docker-létrehozási válasz/timeout
  után csak külön helyi admin rendezhet esetleges orphan canary-t,
  és **soha nem töröl ismeretlen vagy production konténert**.

`tests/test_m15j_disposable_docker_canary.py` **10** szerződéstesztje PASS,
köztük injection és idegen container ID törléstilalom.
`.github/workflows/m15j2-disposable-docker-canary.yml`
**tényleges rootful Docker daemonon, disposable Ubuntu ARM64 és
x86-64 GitHub hoston** végrehajtja az egészet, majd kizárja a
maradék `fieldwork-m15j-canary-*` konténert.

[Native real Docker J2 #41239152037](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41239152037):
**mindkét architektúrán PASS** a 10 teszt, tényleges
create/start/wait/delete, cleanup = PASS.

[Full security regression #41239152058](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41239152058):
**879 updater + 12 bootstrap = 891/891 PASS** az
`54d1ff1e6fb276f935d0a7ffea284cebbe105f36` fejlesztési HEAD-en.
Minden kapcsolódó M15B/D/E/F/G/H/I CI-kapu is SUCCESS.

**Kritikus limit:** J2 valós canary, de **még nem** az eredeti
M12 `stage_manager` Compose build/up/full-test/down életciklusa,
nem a `runtime_runner` hálózatos DB sandboxja, és nem a
`sandbox_command` tetszőleges (konténeren belüli)
felhasználói parancsfuttatása. Nincs M12/36 teljes
shadow parity, külön host user/socket, approval
redemption integráció vagy no-copy updater aktiválás.

Egy J2 helper rootful Docker sockettel változatlanul
host root-ekvivalens; a rögzített argv csökkenti
a támadási felületet, de egy kompromittált Python
folyamat ellen nem önálló privilege barrier.
Ennek megoldása a külön UID, kernel-szintű
korlátozás és a teljes migráció bizonyítása.
**Tilos most `admin` Docker-csoporttagságot módosítani
vagy M15-E-t bekapcsolni.**

### M15-J folytatása

A további M15-J2 fejlesztés sorrendje:
1. A *valódi* M12 staging Compose build/test/start/stop egy
   megbízható, immutábilis, exact source/image pinelt
   dedikált helperen, az éles `fieldwork-stage` kontextusától
   külön, ideiglenes GitHub Linux teszthoston;
2. a meglévő M12 sandbox teljes network/DB/test/cleanup
   funkciókiváltása ugyanilyen helperen, ID/label/receipt/
   crash-recovery/replay ellenőrzésekkel;
3. teljes 36/36 shadow-parity és csak ezt követően helyi
   admin által engedélyezett privilege-separated tunnel cutover.

**Állapot:** `M15J1_INVENTORY_PASS`;
`M15J2_DISPOSABLE_DOCKER_LIFECYCLE_PASS`;
`M15J_FULL_STAGE_SANDBOX_PARITY_PENDING`;
`M15E_ACTIVATION_BLOCKED`;
`PI_PRODUCTION_UNCHANGED`.


## 7. M15-J3/J4 – valódi PostgreSQL-sandbox és háromszolgáltatásos Compose-futtatás (2026-10-31)

Mindkét fejlesztés **kizárólag ideiglenes GitHub Actions Ubuntu Linux
ARM64/x86-64 teszthoston** futott. Az élő Raspberry Pi `/opt/fieldwork`,
Docker, tunnel, `/opt/linux-mcp-operator`, UID/csoport- és systemd-
beállításait semmilyen tesztművelet nem érintette.

### M15-J3 – izolált, ideiglenes PostgreSQL adatbázisos sandbox

`updater/m15j_ephemeral_postgres_sandbox.py`:
- GitHub runneren előzetesen letöltött, pontos OCI
  SHA256-digesthez kötött PostgreSQL image; nincs tetszőleges image/command.
- Egyedi, 128 bites helyi `run_id`-hez kötött név és label.
- `docker network create --internal` – nem publikál portot.
- A PostgreSQL felhasználó UID/GID 70, read-only rootfs,
  `cap-drop ALL`, `no-new-privileges`, korlátozott CPU/RAM/PID,
  ideiglenes **tmpfs** adatkönyvtár, nincs volume vagy host bind mount.
- A csak tesztcélú `POSTGRES_HOST_AUTH_METHOD=trust` kizárólag a
  belső, ideiglenes CI-hálózaton szerepel. **Nem alkalmas production DB-re**.
- Valós `pg_isready` és **külön klienskonténerben** végrehajtott
  `SELECT 1` és `exit 0` ellenőrzés.
- Teszt- és DB-konténer törlése előtt 64-karakteres container ID,
  pontos név és két local label ellenőrzése; hálózat törlése
  előtt `Internal=true`, ID/label és az idegen endpointok
  hiánya kötelező. Hiba után is megkísérli a szűkített rollbacket,
  de bizonytalan tulajdon vagy Docker timeout esetén
  **nem töröl idegen objektumot** és nem állít PASS-t.
- Nincs host Docker socket mount a tesztkonténerben; **maga a helper
  viszont továbbra is root-equivalent Docker jogú CI-felhasználó**.

`tests/test_m15j_ephemeral_postgres_sandbox.py` **12/12 PASS**
x86-64-en és ARM64-en; az internal hálózat, invalid run/image,
módosított ID/label, idegen endpoint, cleanup failure, indítási
hiba és root/untrusted caller mind tesztelt.

[Native M15-J3 #41240056912](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41240056912):
**mindkét architektúrán PASS** a valódi PostgreSQL, SQL,
DB/test/network cleanup és az üres maradványleltár.

### M15-J4 – külön háromszolgáltatásos Compose-teszt

`updater/m15j_disposable_compose_stage.py`:
- A Compose-fájlt **helyileg, rögzített Python-konstansokból**
  generálja; nincs bejövő YAML, Compose-paraméter,
  Dockerfile vagy tetszőleges host path.
- A két építendő teszt-image `nginx` **pontosan rögzített OCI digestből**
  épül; a harmadik, `db` PostgreSQL image szintén pontos digest.
- `db` (valódi PostgreSQL, tmpfs), `api` (helyi
  rögzített HTTP `/health` fixture) és `nginx`
  (valódi reverse proxy az API felé).
- Build, `up --detach --wait --wait-timeout 90`,
  a belső reverse proxyhoz intézett HTTP `ok` próba,
  valódi SQL `SELECT 1`, majd `down`.
- Nem publikál host TCP-portot, nem csatol host
  könyvtárat runtime, nincs production/named volume,
  `privileged`, Docker socket, host network vagy
  távoli felhasználói parancs.
- Takarítás előtt a Compose project labelhez
  tartozó konténernevek és szolgáltatáscímkék
  kizárólag `api/db/nginx` lehetnek; eltérésnél
  **STOP** és nincs ismeretlen erőforrás törlés.

Valós hibakeresés: az első natív build a
`HOME=/nonexistent` miatt hibázott
(`mkdir /nonexistent: permission denied`).
A CI-only Docker Compose számára meglévő,
írható GitHub runner HOME-ot használunk;
az azonosított hiba javítása után mindkét
architektúrán sikeres az image build és a teljes futtatás.

`tests/test_m15j_disposable_compose_stage.py`:
**10/10 PASS** ARM64 + x86-64.
[Native M15-J4 #41240056933](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41240056933):
**PASS mindkettő**, valós háromszolgáltatásos
Compose build/up, HTTP proxy + SQL, down,
és maradék konténerek/hálózatok hiánya.

[Teljes biztonsági regresszió #41240057045](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41240057045):
**901 updater + 12 bootstrap = 913/913 PASS**.

### Ami ezzel MÉG NEM teljesült

1. A Compose build csak változatlan, CI-only tesztforrást fordít,
   nem a valós FieldWork release-t, migrációkat,
   frontend-backend paritást vagy a 36 MCP-műveletet.
2. Az adatbázisos sandbox csak rögzített SQL-próba, nem
   `runtime_runner.py` és `sandbox_command.py`
   teljes (korlátozott, de dinamikus) teszt- és
   takarítási képessége.
3. Nincs létrehozva Pi-n külön `fieldwork-mcp` vagy
   Docker-helper UID, systemd socket, üzemképes
   AF_UNIX végrehajtási szerződés, auditált `SO_PEERCRED`,
   valódi helyi approval HMAC integráció, shadow 36/36,
   újraindításos cutover és visszaállítás.
4. Az M15-E változatlanul csak **inaktív, root-owned
   forrásfájl**, és nem javasolt a bekapcsolása.

**Release gate:** `M15J3_NATIVE_POSTGRES_SQL_PASS`,
`M15J4_NATIVE_COMPOSE_FIXTURE_PASS`,
`M15J_LEGACY_STAGE_SANDBOX_PARITY_PENDING`,
`M15E_NOT_AUTHORIZED`,
`REAL_PI_UNTOUCHED`.

A következő tényleges fejlesztési feladat a szűkített,
külön UID/AF_UNIX Docker-helper integrációja a
**valós, változatlan FieldWork-funkciókba**, nem a
teszt-fixture újabb változata. A Docker-jog megvonását
csak bizonyított rollback és paritás után lehet megkezdeni.
