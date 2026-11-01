# M13 – Univerzális Linux MCP-agent: közös motor, gépspecifikus adapterek

Döntés dátuma: **2026-10-31**. Ez a felhasználó által jóváhagyott
célarchitektúra, **nem** már telepített Orange Pi-s szolgáltatás.

## Elsődleges cél

Egyetlen karbantartható, korlátozott jogosultságú Linux MCP-alap,
amely Raspberry Pi, Orange Pi, ARM64 SBC és x86-64 Linux hostokon
változtatás nélkül vagy vékony hardver-/disztribúciós adapterrel
használható. A FieldWork- és Home Assistant-funkciók nem kerülnek
a közös alapkódba.

**NEM ígérünk minden eszközre vagy minden Linux-verzióra automatikus
kompatibilitást.** A konkrét architektúra, kernel, userspace, Docker
és jogosultságok capability-detection ellenőrzésen mennek át.

## A jelenlegi Pi rendszer és határa

- Raspberry Pi FieldWork MCP v0.6.1 + aktív M12: 36 eszköz;
  `fieldwork_mcp_source_inventory`, `fieldwork_mcp_source_review`,
  `fieldwork_mcp_docker_inventory` tényleges Pi-hívása 3/3 PASS.
- **Nincs általános host shell, nincs jogosultság a tetszőleges
  Docker-projektek leállítására, nincs unattended aktiválás.**
- Éles FieldWork és stage három-három konténeres, megőrzendő.
  Az M12 telepítés pontos forráshash-eit és a korábbi nyugtákat
  nem írjuk át; meglévő plugin/tunnel működése megmarad.

### 2026-10-31 – valós takarítási állapot

A felhasználó saját gépén, egyetlen `docker stop`
paranccsal leállította a `fieldwork-plan-m2` és
`fieldwork-parity-m3/m4/m5` négy különálló
háromkonténeres tesztprojektjét. A ChatGPT az aktív,
csak olvasási Pi MCP-vel **utána újra ellenőrizte**:

- Docker leltár **26 konténer, 6 running és 20 exited**
  (korábban 18 running és 8 exited).
- Mind a 12 kijelölt `plan/parity` konténer
  `exited` állapotú.
- Mindhárom éles `fieldwork-api/db/nginx` konténer
  `running`; `/api/health` és `/health`: HTTP 200.
- Mindhárom `fieldwork-stage-api/db/nginx` konténer
  `running`; `STAGE_HEALTH_PASS`.
- Ez **nem** bizonyítja, hogy pontosan mennyi CPU/RAM
  szabadult fel: a jelenlegi MCP-nek nincs `docker stats`,
  `/proc` memória- vagy folyamatonkénti CPU-mérő eszköze.
- Nem történt volume törlés, nem futott `docker rm`
  vagy `docker system prune`.
- Az aktuális Docker-leltár azonosító SHA256:
  `f3a4921ddc83b216b69c6fe86d17c105c0159b8dcbf092bcce2a8522a5973215`.

**Kritikus különbség:** konténerleállítás nem jelenti
a tárolt kötetek vagy DB-adatok törlését; a következő
`docker compose up` elvileg újraindíthatja ezeket,
ha a megfelelő project/config rendelkezésre áll.

## Célarchitektúra

```text
ChatGPT
   | MCP, hitelesített kapcsolat (eszközönként külön)
   |
   +-- Linux MCP Core (ugyanaz a Python csomag)
       |-- Capability registry / Linux kernel + arch check
       |-- Allowlisted /proc telemetry (CPU / RAM / load / swap)
       |-- Optional cgroup v2/v1 process/container view
       |-- Optional read-only Docker inventory + bounded stats
       |-- Audit receipts, per-host policy, bounded responses
       |-- Local approval gate for narrowly scoped mutations
       |
       +-- Raspberry Pi / FieldWork adapter
       |      `fieldwork` és `fieldwork-stage` megőrzése
       |      project-specifikus tesztelés / jóváhagyott lifecycle
       |
       +-- Orange Pi / Home Assistant adapter
       |      HA Docker szolgáltatások és konfiguráció read-only
       |      HA adatbázis és titkok módosítása nélkül
       |
       +-- Generic Debian/Ubuntu/Linux adapter
              nem feltételez FieldWork-, HA- vagy Docker-jelenlétet
```

### Platformfüggetlen mag

- Python 3.11+ (javasolt első támogatási alap); stdlib,
  Linux `/proc`, opcionális `/sys/fs/cgroup`.
- Első támogatandó architektúrák: `aarch64/arm64`,
  `x86_64/amd64`. Az `armv7l` és egyéb célok
  mérés, CI és telepítési teszt nélkül **EXPERIMENTAL**.
- Docker hiánya **nem** platformhiba:
  `docker=UNAVAILABLE`, a CPU/RAM mérés attól még működik.
- Nem tételezünk systemd-t minden Linuxon.
  A `systemctl` csak opcionális, engedélyezett adapter;
  OpenRC/runit/egyéb init külön feature flag.
- Hiányzó hardware szenzorok: `UNSUPPORTED`
  (nem hamis `0°C`). Hőmérséklet, feszültség,
  ventilátorvezérlés gépspecifikus és külön adapter.
- Linux `/proc/meminfo` RAM-számítás:
  **MemAvailable**, nem `MemFree`. A felhasználói
  panelen látott `0.67 / 0.88 GB` nem biztos,
  hogy a teljes host fizikai RAM-ja; forrás-scope
  nélkül ezt nem szabad annak nevezni.
- CPU-terhelés: **két külön időpontban** olvasott,
  monotón `/proc/stat` számlálóból; egyetlen pillanatnyi
  CPU számláló **nem** ad %-os kihasználtságot.
- Méret-, idő-, processz- és output-limit.
  Minden PID-re korlátozott, anonimizált adat,
  nincs `/proc/*/environ`, argv, token, .env vagy
  konfiguráció-kiszivárgás.

### Jogosultság és fenyegetésmodell

- Az MCP-transport (tunnel/hálózat) **nem**
  azonos az adminisztrátori jogosultsággal.
- Minden gép külön azonosítóval, kapcsolati hitelesítéssel
  és eltérő cél-policy-val rendelkezik.
- Alap: read-only, non-root, fix fájl-/Docker parancs
  allowlist, `shell=False`, symlink/path-traversal elutasítás.
- A veszélyes Docker lifecycle **nem** általános
  `docker stop` host shell: explicit project-scope,
  előzetes kötetcímke, függőségek, Compose-fájl
  és aktív feladatok ellenőrzése; a cél-ID-kre
  vonatkozó helyi, időkorlátos jóváhagyás.
- Stop ≠ remove; **soha nincs**
  automatikus `rm -v`, volume prune, image prune,
  container/image network tömeges tisztítás.
- `production`, `stage`, `homeassistant`,
  `mosquitto` stb. külön védett profil, nem
  automatikusan leállítható.
- Audit log: who/what target, SHA, időpont, elő-/utóállapot,
  rollback és siker/FAIL külön.
- Egyszerre nem adunk általános root vagy Docker socket
  write-hozzáférést az MCP chatoldali eszközeinek.
  A priv. műveletek külön lokális, minimális helper
  és operator approval útvonalon történnek.

## Elkezdett kód – a működő Pi MCP-t még nem módosítja

`updater/linux_telemetry.py`: tiszta Linux, ARM/x86-semleges
`/proc/meminfo`, `/proc/stat`, `/proc/loadavg`
bounded parser és nem mutáló snapshot collector.

`tests/test_linux_telemetry.py`: MemAvailable/cache,
swap és CPU-sample numerika, hibás számlálók,
szimbolikus linkek, tiltott proc path és túlméretes
adat elutasítása. **Ez még nem regisztrált MCP eszköz**:
Pi-n és Orange Pi-n sem települt, jelenleg GitHub
feature foundation és a CI teszteli.

## Mérföldkövek / elfogadási feltételek

1. **M13 – Core read-only telemetry**: unit + negatív
   tesztek; Raspberry Pi/Orange Pi read-only proc
   adatokkal későbbi hiteles mérés, cgroup-scope
   egyértelmű jelentése. Újabb operátori SSH
   másolgatás helyett megoldott MCP tool registration.
2. **M14 – Capability-based MCP core**:
   önazonosítás, arch/disztribúció capability detection,
   typed request/response, log-korlát, forráshash;
   adapterek nélkül is önállóan tesztelhető.
3. **M15 – Orange Pi / HA integráció**:
   valós ARM64 Pi/Orange Pi teszt,
   read-only Home Assistant health/Docker/status,
   erőforrásszint- és processz-top kimutatás
   titkok nélkül. Eltérő HA Docker host/környezet
   külön mérendő, nem feltételezett.
4. **M16 – Safe lifecycle**:
   helyileg jóváhagyott *konkrét* Docker tesztprojekt stop/start
   és rollback, production tiltás, logolt nyugta;
   helyi engedély hiányában nem teljesül és
   nem kerül chatből közvetlenül meghívásra.
5. **M17 – Többgépes ellenőrzés**:
   host-id, útvonal, verzió és eltérő policy;
   egyetlen ChatGPT-utasítás nyomán mindkét Pi
   snapshot, CPU/RAM és health külön részjelentése,
   hiba esetén izolált degradáció.

**Elfogadás:** nincsenek újabb napi SSH/Python parancsmásolási
körök a normál diagnosztikához; nem áll le
véletlenül a FieldWork, HA vagy MQTT; a valós
Raspberry Pi és Orange Pi adatokat azonos kliensoldali
sémával lehet összevetni, külön hostazonosítással
és measurement-scope-pal. A tesztelt CI **nem**
helyettesíti a valós eszközön végzett elfogadást.

## Visszaállítási stratégia

A jelenlegi M12 aktív Pi MCP, annak fájljai és
tool discoveryje változatlan. A platformfüggetlen
M13 kód csak a GitHub fejlesztői ágán létezik:
rollback egyszerű Git revert. Bármilyen későbbi
telepítéshez a pontos telepített MCP-forráshash,
helyi jóváhagyás, atomikus backup, health-gate
és automatikus rollback kell.

## M13 kódvalidáció – első ellenőrzött alap

A `updater/linux_telemetry.py` és a
`tests/test_linux_telemetry.py` első változatainál
az offline teszt megtalált egy hordozhatósági hibát:
`type(root) is Path` Linuxon `PosixPath` esetén
tévesen false. Ezt `isinstance(root, Path)` ellenőrzésre
javítottuk; a `/proc/stat` felső beolvasási határát
256 KiB-ra emeltük nagyobb magszámú szerverekhez.
A negatív API-ellenőrzés a megjegyzésekben előforduló,
de nem meghívott `sudo` szót sem tekinti végrehajtásnak.

A [CI #41215604196](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41215604196)
**555 updater + 12 bootstrap = 567/567 PASS**, Python
compile PASS; a CI GitHub Linux x86_64,
**nem** Raspberry Pi vagy Orange Pi.
A korábbi fejlesztői CI próbák PASS-ig javításra kerültek,
nem rejtettük el őket.

A kód továbbra is **csak új, offline telemetria alap**,
nem regisztrált MCP eszköz és nem változtatott
a 6 futó Pi Docker konténeren.
