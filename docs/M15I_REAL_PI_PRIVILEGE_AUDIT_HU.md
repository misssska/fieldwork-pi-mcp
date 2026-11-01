# M15-I – valódi Pi-host jogosultsági bizonyíték helyi root adminnal

**2026-10-31. GitHub Draft PR fejlesztői mérföldkő; telepítetlen, nem MCP tool.**

## Miért nem elég, hogy az M15-E fájl fizikailag telepítve van?

A felhasználó 2026-10-31-én a Pi helyi SSH/TTY munkamenetében
`M15H_INACTIVE_SOURCE_INSTALLED_ONLY` státuszt kapott az
`/opt/linux-mcp-operator/linux_approval_redeemer.py` forrásra,
`root:root`/UID 0 és `0444` fájljogokkal.
Az M15-E HMAC beváltó szolgáltatás **nem aktív**, nem regisztrált
systemd-unit és nincs telepített külön operátori identitás.

A működő távoli M12/v0.6.1 Pi MCP közvetlenül Docker parancsokat
futtathat. Ez normál rootful Docker hoston root-egyenértékű
lehet: távolról hívható MCP saját beszámolója nem
bizonyíthatja a saját jogosultsági elszigeteltségét.

## Elvégzett M15-I fejlesztés

`updater/m15i_local_privilege_audit.py`:
- csak a Pi-n **független, helyi root admin** által futtatható,
  `--audit` paraméterrel;
- `/proc` alapján fix méret- és processzszám-limit
  mellett `fieldwork_mcp.py` önálló parancsargumentumhoz
  tartozó jelölt PID-eket fedez fel;
- M15-F segítségével a folyamat PID/indulási kernel starttime
  dupla ellenőrzése, UID/GID, csoportok, eff. capability,
  NoNewPrivs és a `/var/run/docker.sock` egyszerű
  Unix-DAC (nem ACL) vizsgálata;
- a rögzített `fieldwork-pi-tunnel.service`,
  `fieldwork-pi-mcp.service`, `fieldwork-mcp.service`
  egységekből kizárólag szűkített `systemctl show`
  MainPID/User/ActiveState adatok olvasása;
- `sudo -n -l -U` kizárólag helyileg azonosított,
  passwdbeli felhasználóra, semmi szabad parancs;
  a sudo raw stdout/stderr SOHA nem kerül a jelentésbe;
- inaktív M15-E fájl root tulajdon és `0444`
  mód ellenőrzése; tartalma és publisher eredete
  ekkor még NEM függetlenül hitelesített;
- **nincs írás, Docker CLI/API, stop/start, chmod,
  useradd, systemd enable, service/host módosítás**;
  a `sudo -l` vagy `systemctl` azonban a host
  saját auditnaplójába írhat eseményt;
- JSON a képernyőre, nem perzisztens nyugta.
  A PID-jelek parancssori argumentumból jönnek, ezért
  csak jelöltek, nem végleges kóderedet-bizonyíték.

A jelentés mindig:
`status=M15I_HOST_PRIVILEGE_EVIDENCE_INCOMPLETE`,
`safe_to_activate_service=false`,
`safe_to_install_operator_secret=false`,
`safe_to_revoke_legacy_docker_access=false`.

## Korlátok

- Rootless Docker, ACL, SELinux/AppArmor/LSM,
  örökölt FD, user namespace, névtérből elérhető
  alternatív socket, teljes sudoers-policy nem
  igazolt pusztán a megfigyeléssel.
- A folyamat `cmdline` hamisítható; a
  `systemd_mainpid_match` csak pozitív kiegészítő
  jel, önmagában nem hitelesített executable code hash.
- Hiányzó processzjelöltből nem lehet arra
  következtetni, hogy az MCP nem fut, vagy
  hogy nincs más távoli root-egyenértékű elérési út.
- A read-only auditot végző root script forrását,
  a Git commitot és a tényleges lokális admin
  jóváhagyását a felhasználónak külön kell
  megbízhatóként elfogadnia.
- Az audit nem bizonyítja a 36 MCP-eszköz
  stage/sandbox-paritását; nincs M12 leállítás.

## Natív kvalifikáció

`tests/test_m15i_local_privilege_audit.py`:
hamis folyamatjelöltek, eltérő/duplikált systemd
mezők, különböző sudo-válaszok, root nélküli
tiltás, hiányzó MCP processz, Docker socket/csoport
kockázat, soha nem engedélyező eredmény.

`.github/workflows/m15i-local-host-audit.yml`:
valódi, disposable ARM64 és x86-64 GitHub Linux
runneren nem root tiltás, lokálisan sudo-val
futtatott Linux-kernel/systemd felmérés,
kötelező `safe_to_*=false` ellenőrzéssel.
**Ez még nem az éles Pi host auditja.**

## Következő valódi Pi-feladat

A felhasználó a Pi terminálján rögzített, változhatatlan
Git commitból, forrás review után futtatja a
`sudo python3 -s updater/m15i_local_privilege_audit.py --audit`
auditot, csak lokális /proc- és jogosultsági
metaadatokról JSON-t másol vissza.
Nem kerül át privát HMAC, SSH credential,
token vagy konfigurációs secret.

Ezután a mért UID/groups/sudo/Docker kép
alapján konkrét M15-J operátori- és Docker-helper
telepítési tervet választunk, ami nem veszélyezteti
a már működő MCP stage/sandbox/production-t.
