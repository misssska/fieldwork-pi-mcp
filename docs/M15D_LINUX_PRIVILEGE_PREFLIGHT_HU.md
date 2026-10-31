# M15-D – lokális Linux privilege preflight (bizonyíték, nem jogosultság)

**Dátum: 2026-10-31. Állapot: Draft PR-only; Pi/Orange Pi telepítés nincs.**

## Döntés és hatókör

A külön Unix-felhasználóval futó M15-C jóváhagyó natív ARM64 és x86-64
systemd-tesztje PASS. Ez nem bizonyítja a **távoli M12 MCP** privilege
boundaryját, mert az a jelenlegi FieldWork hoston belső Docker parancsokat
futtathat, és a rootful Docker socket root-egyenértékű képesség lehet.

A `updater/linux_host_privilege_preflight.py` kizárólag **a futtató saját
folyamatáról** készít korlátozott megfigyelési jegyzőkönyvet. Nem enged
deployt, nem kapcsol ki szolgáltatást, nem használ Docker API-t,
nem futtat host parancsot és nem olvas tetszőleges fájlokat.

Az elérési út kizárólag `/proc/self/status` (max 16 KiB)
és a `/var/run/docker.sock` végpont `lstat` metaadata;
eUID/eGID/supplementary groups a kernelből. Az `lstat`
symlinket nem követ; ilyen vagy hozzáférhetetlen socket esetén
`UNVERIFIED_ACCESS_OR_SYMLINK` és fail-closed jelzés.

## Bizonyítható és NEM bizonyítható

- **Megfigyelhető:** jelenlegi effective UID/GID, effektív capability jelenléte,
  `NoNewPrivs`, socketfájl típusa és hagyományos Unix DAC szerinti
  íráslehetőség. A /proc és kernel UID/GID/GROUP eltérését elutasítja.
- **Nem igazolható ezzel:** a Docker daemon rootful/rootless volta;
  a sudoers vagy `sudo -l` tényleges szabályrendszere; POSIX ACL/LSM;
  örökölt nyitott Docker FD-k; más setuid/privileged helper-ek;
  user namespace host UID/GID mapping; cgroup/host namespace escape;
  más folyamat, különösen a Pi M12 tényleges jogai.
- A socketre vonatkozó `DAC_WRITE_POSSIBLE` önmagában nem bizonyítja,
  hogy a daemon rootful; **kockázati jelzés**, amely további vizsgálatot igényel.
- A kimenet mindig `activation_authorized:false`
  és `privilege_separation_verified:false`, még akkor is, ha
  a megfigyelt folyamat nem root és a socket nem látszik.

Az M15-D forrás külön létezik; **nincs az M15 hordozható
telepítési allowlistájában**, így nem bővül csendben a csomag vagy a Pi MCP.
A GitHub natív teszt egy disposable runner **saját folyamatát**
ellenőrzi: ez **nem Pi jogosultságaudit**.

## Elfogadási ellenőrzés

1. Fókuszált negatív unit tesztek hamis /proc UID, GID, Groups, capability,
   extra kulcs, duplikált mező, túl hosszú státusz, idegen fájl,
   symlink, különböző Docker socket DAC jogok esetére.
2. Valódi ARM64 és x86-64 GitHub runneren `collect()` és nem autorizáló
   géppel ellenőrizhető nyugta; hálózat/Docker/sudo használat nélkül.
3. Teljes meglévő security-tests PR kapu; korábbi M15-C natív elfogadás
   a saját SHA-jához kötött, ettől nem válik élessé.
4. Pi helyi privilege auditot csak későbbi, **független, helyben
   jóváhagyott**, reprodukálható telepítési úttal szabad futtatni;
   távoli MCP socket vagy artifact upload nem használható erre.

## Következő kiadási blokkolók

Külön helyi főadmin audit az M12 tényleges UID/GID/groups, Docker socket,
sudoers és nyitott FD jogairól, majd stage/sandbox lifecycle helper
funkcionális paritás 36/36 toolnál, root-ekvivalens út megszüntetése,
publisher aláírás/approval IPC és rollback. **Éles M12, FieldWork,
DB, Docker és tunnel változatlan.** A PR DRAFT marad.
