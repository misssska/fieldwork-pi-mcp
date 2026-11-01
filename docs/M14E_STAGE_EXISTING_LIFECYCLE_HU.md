# M14-E – Stage meglévő konténerek engedélyezett lifecycle, sandbox migrációs határ

Dátum: 2026-10-31. **GitHub / CI prototípus PASS; Raspberry Pi / Orange Pi deploy NEM történt.**

## Ellenőrzött kiindulási tények

Az aktív Pi M12 `stage_manager.py` forrásának csak olvasható,
kitakart AST-jéből és SHA256-jából ellenőriztük:

- `stage_manager.start` a hitelesített stage release-en
  `docker compose ... up` jellegű, az adott stage roothoz
  kötött műveletet hajt végre;
- `stage_manager.stop` a meghatározott stage Compose
  projektet állítja le;
- `runtime_runner.test_sandbox` és
  `sandbox_command.run_command` külön Docker-hálózatokat,
  adatbázis- és tesztkonténereket hoznak létre és
  takarítanak el (`docker run`, `docker network ...`,
  `docker rm`). Nem ekvivalensek a stage lifecycle-lel.
- A forrásreview azonosítói változatlanok:
  `stage_manager.py` SHA256
  `0a04c40a00ccc940e50d590cf6b01f75c7a803dd228cb24b916fad44e046a7e6`,
  `runtime_runner.py`
  `ae0387aed34768a7260cf01e6c1ff9d4620c506c37e7ae2a74706f661ee2db6c`,
  `sandbox_command.py`
  `5a4a6ba775f7fd16d0660a654eb3ab8724659ff1ac72fd1427ed3c9eadb797f5`.

**Kritikus következtetés:** az M14-D read-only Docker proxyba
NEM tehetők át a mutáló Docker-műveletek általános
`command` paraméterrel. A második, külön lifecycle
helper saját operátori jóváhagyást és szűk szerződést kap.

## Elkészült forráskód

`updater/linux_stage_existing_lifecycle.py`:

- A művelet pontosan `start` vagy `stop`, és **csak**
  a `fieldwork-stage` projekt három **már létező**
  `api`, `db`, `nginx` konténerét kezeli.
- Docker inspektálás pontos név és
  `com.docker.compose.project=fieldwork-stage`,
  `com.docker.compose.service`, valamint
  `com.docker.compose.container-number=1`
  címkék alapján. Kizárólag a **teljes 64 karakteres,
  immutable Docker konténer-ID** használható a
  stop/start parancsban.
- Mindhárom konténernek azonos, előre várt
  `running` / `exited` állapotban kell lennie.
  Eltérő ID, címke, állapot, hiányzó konténer
  vagy részleges projekt esetén **STOP**.
- A helyi jóváhagyás HMAC-kel kötött a konkrét
  gépazonosítóhoz, projekthez, művelethez, a
  három teljes ID-hoz és kezdeti állapotukhoz,
  rövid lejáratú és egyszer használatos nonce-szal.
  A `local_operator_present` tesztparaméter
  **nem bizonyítja** önmagában az emberi
  jelenlétet; a tényleges operátori UI és a
  külön OS-identitás kötelező.
- Az executor fix Docker CLI argumentumokat
  használ (`container inspect/start/stop`).
  NINCS `docker run`, `rm`, `compose`,
  network/volume művelet, tetszőleges image,
  fájlelérési útvonal vagy konténernév-paraméter
  a felhasználói requestben.
- Privát 0700 helyi állapotkönyvtárban
  atomi 0600, fsync-elt egyszer használatos
  `PREPARED → APPLYING → COMMITTED` auditnyugta.
  Ha bármelyik művelet hibázik, megpróbálja
  visszaállítani az eredeti három állapotot.
  Az utolsó pillanatban Docker-timeout **után**
  is ellenőrzi a tényleges állapotot.
  Csak bizonyított teljes visszaállás esetén
  `ROLLED_BACK`, egyébként
  `ROLLBACK_UNCERTAIN` és **további
  műveletek letiltása** helyi manuális
  egyeztetésig.
- Az eredmény pontosan külön kezeli a
  staging konténerváltoztatást és a
  **production/volume változatlanságot**.
- Az executor jelenleg modulból tesztelhető,
  NINCS aktív MCP eszközként regisztrálva,
  és NINCS Pi-n futó lifecycle helper service.

## Tesztbizonyíték

| Kapu | Bizonyíték | Állapot |
|---|---|---|
| Teljes GitHub suite | [#41225139726](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41225139726) | **727 updater + 12 bootstrap = 739/739 PASS** |
| Native ARM64 és x86-64 | [#41225101095](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41225101095) | **Mindkettő PASS** |
| Valódi Docker stop → start | [#41225136183](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41225136183) | **PASS** izolált GitHub runneren |
| Production-fixture változatlan | [#41225136183](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41225136183) | **PASS**, külön `fieldwork-api-1` |
| Élő Pi M14E | — | **NOT RUN** |

Negatív tesztek: idegen host/projekt,
hamis Compose-címke, konténer-ID csere,
rossz pre-state, hiányzó jóváhagyás,
eltérő HMAC, lejárt terv, replay, tiltott
Docker verb, root futás, rossz állapotkönyvtár,
Docker-timeout a végrehajtás UTÁN,
részleges rollback, függőben maradt
`APPLYING` nyugta.

## Miért NEM cseréljük még le az M12 stage és sandbox útját?

1. **A jelenlegi stage start Docker Compose telepítés/build.**
   Az M14E csak létező konténerindítás és
   -leállítás, nem hoz létre hiányzó
   konténert, networköt vagy volume-ot.
   Nem állítjuk, hogy az összes stage funkciót
   regresszió nélkül kiváltja.
2. **A sandbox külön, dinamikus konténer- és
   hálózat-életciklus.** A mai runtime kód
   `docker run` és `rm -f` műveleteket
   használ. A történeti cleanup-sikertelenség
   `b901aaabbbcccdddeeefff0000000020`
   nyugtája továbbra sem minősül
   utólag sikeresnek; a sandbox
   eljárást külön, ID- és ownership-alapú
   szerződésre kell átvezetni.
   A régi név/label egyezések még nem
   megbízható tulajdonjog-bizonyítékok.
3. **Docker socket privilege:** a helper
   az általános rootful Docker hoston
   továbbra is root-ekvivalens. A jelenlegi
   M12 távoli MCP UID/group/sudo-jogai
   a valós Pi-n még nincsenek függetlenül
   igazolva. A helyi HMAC titok jelen
   prototípusban egy helperben ellenőrizhető;
   az éles kiadás előtt külön, biztonságos
   helyi approver/executor IPC és
   OS-level izoláció szükséges.
4. **Az esetleges áramkimaradás utáni
   automatikus crash recovery** még nincs
   kész. A durable `APPLYING` nyugta
   *megakadályozza* az újabb műveleteket,
   amíg az operátor helyileg nem rendezte.
   Ez tudatos fail-closed limit.

## Következő, release előtti kapu

- Stage Compose teljes, forráshashhez
  és engedélyezett release-hez kötött
  lifecycle kérések a külön helperben,
  preflight és rollback, produkciós
  Compose hatókör elérésének kizárásával.
- Sandboxból az ownership címkék
  bevezetése és `run_id` → konténer-ID /
  network-ID pozitív bizonyítéka.
  Minden `docker rm -f` és network
  lifecycle csak a lokális, rövid élettartamú
  jóváhagyott sandboxhoz kötötten;
  ne legyen általános delete.
- Pi eredeti 36 MCP eszközének regressziós
  shadow tesztje és a Docker socket
  jogosultságai előbb felmérve,
  utána változtathatók.
- Független helyi approver, UID/cgroup
  scope, service/handoff, és
  egyszeri operator-engedélyes bootstrapping.
- Orange Pi/HA saját host policy és
  élő ARM64 teszt; Home Assistant és
  MQTT konténerek semmilyen stage
  lifecycle művelet célpontjai nem lehetnek.

A felhasználónak a normál üzemhez
**ne kelljen ZIP-et, scriptet vagy SSH-parancsot
másolnia**. M14E jelenleg GitHubon tesztelt
kód, nem ez a már aktivált funkció.
