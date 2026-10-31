# M14-F – Stage Compose-konfiguráció és sandbox-tulajdonjog ellenőrzése

Dátum: 2026-10-31. **Új forráskód és offline tesztek a draft PR #2 fejlesztési ágában.**
**NINCS Raspberry Pi / Orange Pi telepítés, Docker-módosítás vagy tunnel-restart.**

## Döntés: két külön engedélyezési tartomány

Az M14-E csak meglévő, pontosan ismert staging konténerek start/stop
műveleteit képes kezelni. Az M12 jelenlegi stage eljárása ezzel
szemben Docker Compose build/up folyamatot is futtat. A sandbox
önálló `docker run`, hálózat és adatbázis életciklust használ.
A két külön munkafolyamat összevonása egy általános
`docker command` végpontba **tilos**.

Az M14-F két, még **nem végrehajtó** biztonsági kaput készít:

### 1. Stage Compose admission

`updater/linux_stage_compose_contract.py`

A külön, helyileg hitelesített folyamatból származó
`docker compose config --format json` kimenetet
**memóriában**, Docker- vagy fájlmódosítás nélkül elemzi.

Csak a pontos `fieldwork-stage` projekt és három
`api/db/nginx` szolgáltatás engedélyezhető.
A Compose forrásának rögzített SHA256-jának egyeznie kell
a tényleges forráslenyomattal. A lokálisan rögzített
image-listában minden szolgáltatás **immutábilis
`@sha256:` OCI digesttel** rendelkezik.

Korlátozások:
- csak név szerint rögzített belső `fieldwork-stage_default`
  hálózat és külön `fieldwork-stage_data` named volume;
- nincs Docker build, privileged, host network/PID/IPC,
  device, extra capability, extra service, bind mount,
  hostkönyvtár, környezeti jelszó vagy tetszőleges entrypoint;
- root nélküli user, capability drop, read-only
  konténerfájlrendszer az API és nginx esetén,
  tiltott privilege escalation és konkrét resource limit;
- csak az nginx kaphat portot, **127.0.0.1:18081**
  célra (ez jelenleg **NEM** egyenértékű a régi
  LAN-on elérhető staginggel; biztonságos proxy később);
- DB csak a külön stage adatkötethez férhet hozzá;
  sem `/opt/fieldwork`, sem production DB kötet
  nem érhető el a szerződésből;
- a validátor **nem állít elő futtatható parancsot**,
  `activation_authorized=false`,
  `release_publisher_verified=false`.

**Fontos:** a jelenlegi M12 stage Compose buildet és
konfigurációspecifikus értékeket használ, ezért **nem
kompatibilis automatikusan ezzel a szigorú, új mintával**.
Megbízható image build/publikálás, image source attestation,
stage adatok migrációja, API elérés és diff review szükséges.
Nem cseréljük le az éles staginget egy szintetikus
Compose-szerződés alapján.

### 2. Sandbox ownership / cleanup preflight

`updater/linux_sandbox_ownership_gate.py`

Egy **új, későbbi** sandbox helperhez tartozó
létrehozási bizonylat struktúráját és HMAC-azonosságát
ellenőrzi. A futtatás `run_id` és `proposal_id`
32-hex azonosítóhoz, a hosthoz, a kiadási időhöz,
rövid lejárathoz, valamint a Docker objektumok
teljes 64-hex ID-jához kötött.

A megengedett logikai erőforrások:
- csak tesztkonténer (DB nélküli sandbox);
- vagy pontosan egy belső hálózat, egy teszt-DB és
  egy tesztkonténer (DB-s sandbox).

Minden erőforráshoz pontos szerep-/run-/proposal-label,
teljes Docker-ID és expected név kell. A külön
helyi Docker-segédnek *saját létrehozási naplójából*
kell kiadnia a titkos kulccsal aláírt nyugtát,
majd **független** élő Docker-inspect lekérdezésekkel
igazolnia az aktuális objektumokat.

Különösen: hálózattörlés előtt nem lehet idegen
konténer csatlakoztatva. Bármilyen mismatch, Docker
daemon/probe hiba, hiányzó HMAC vagy lejárt nyugta
esetén **STOP**.

A mostani implementáció kizárólag **in-memory
preflight**: nincs Docker create/rm/network remove,
nincs explicit jóváhagyást kiváltó távoli eszköz.
A válasz sikeres ellenőrzés mellett is
`cleanup_authorized=false`,
`container_removal_authorized=false`.

**Nem lehet** a korábbi M12 sandbox nyugtákat az új
formátumra visszamenőleg aláírni, vagy meglévő
konténert puszta név-/label-egyezés miatt törölni.
A historikus `b901aaabbbcccdddeeefff0000000020`
sikertelen cleanup nyugta változatlan.

## Tesztek és elfogadási kapuk

- `tests/test_linux_stage_compose_contract.py`:
  build/privileged/host mount/port/image drift,
  másik projekt, helytelen hálózat, mutable tag,
  extra titkos mező, túlméretes/hibás JSON,
  eredeti forráshash eltérés, success without activation.
- `tests/test_linux_sandbox_ownership_gate.py`:
  külön helyi HMAC, idegen/duplikált ID,
  más host, idegen konténer a hálózaton,
  hamisított Docker-megfigyelés, rossz label,
  régi/lejárt manifest, DB nélküli mód,
  következő delete jog tiltása.
- A teszteket az M14 közös CI és a natív
  ARM64/x86-64 workflow is futtatja.
- A régi M14-E teljes, korlátozott stage start/stop
  integrációja továbbra is csak a GitHub
  elkülönített Docker-runnerén bizonyított.

**Nem állítunk teljes Compose deploy, sandbox run/cleanup vagy
eszközön futó M14-F PASS-t.** Ezekhez az éles M12
forrás- és jogosultságképességeinek teljes migrációja
és helyi, egységes tranzakciós adapter kell.

## A valódi következő release-mérföldkő

Az újabb policy-modulok számának növelése önmagában
nem teszi használhatóvá a rendszert.
A továbblépés a meglévő M12 36 eszköze,
a stage és sandbox műveletek pontos host-oldali,
csak olvasási auditja után egy **külön, helyi,
egyszer telepített upgrade-helper / operátori
jóváhagyó** éles kvalifikációja. Docker UID/sudo
elkülönítés, publisher trust, pontos
forrásbájt-hash, valós ARM64 smoke, backup/
rollback és telefonos autentikáció nélkül
a telepítés **BLOCKED**.

A felhasználó által kért operatív cél változatlan:
**nem kelljen minden frissítéshez ZIP-et vagy
hosszú SSH-parancsot bemásolni.** Jelenleg
ehhez nincs telepített autorizált Pi helper,
ezért nem lehet ezt már késznek mondani.
