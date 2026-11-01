# M15-F – célzott Linux host-jogosultsági audit és kötelező STOP kapu

**2026-10-31 – kizárólag Draft PR + izolált GitHub CI. Nem Pi-telepítés.**

## Miért ez következik az M15-E után?

A natív M15-E már elválasztja az operátori HMAC-kulcsot a végrehajtótól,
de a valódi Pi-n az M12 közvetlenül indít Docker parancsokat a
`runtime_runner.py::_run` és `stage_manager.py::_run` függvényekben.
A Raspberry Pi MCP-forrás `fieldwork_mcp.py` pontos élő SHA256-ja
`ee218971079b988e1e85b3790dd50228847e5e911e2e688b3df77972ad78b532`.
A távoli MCP hozzáférhet egy rootful Docker sockethez; ez potenciálisan
root-egyenértékű képesség. A Docker-csoport vagy socket jogának
megvonása a meglévő stage/sandbox funkciók migrálása nélkül regressziót okozna.

## Fejlesztési eredmény

Az `updater/linux_m15f_host_boundary_audit.py` az M15-D saját folyamat
auditját egy másik, **helyben azonosított PID** megfigyelésével bővíti.

A helyi, független admin/szolgáltatáskezelő adja meg a PID, az elvárt
effective UID és a /proc/PID/stat 22. mezőjéből korábban megbízhatóan
rögzített `starttime` értékét. A modul kizárólag rögzített
`/proc/<PID>/stat`, `/proc/<PID>/status` és
`/var/run/docker.sock` **metaadatokat olvas**.

Kétszer ellenőrzi a `/proc/PID/stat` starttime mezőjét, hogy az
alapvető PID-reuse és versenyhelyzeteknél megálljon. A `comm` mező
szóközt és `)` karaktert is tartalmazhat; emiatt a parser az utolsó
lezáró zárójelet használja. Elutasítja a zombie/exit állapotot,
a sérült/túlméretes rekordot, PID/UID eltérést és a közben
megváltozott starttime-ot.

A Linux kernel státuszból csak az effective UID/GID, group lista,
CapEff és NoNewPrivs mezőket közli. A Docker alapértelmezett Unix socket
`lstat` és DAC írási jogát elemzi; **symlinket nem követ**.
A tényleges daemon rootless/rootful volta, ACL/LSM, sudoers, örökölt
nyitott FD, egyéb socket/Podman, systemd unit identitás,
publisher aláírás és helyi emberi jóváhagyás **nem vizsgált**.

## Szándékosan NEM adhat zöld jelzést

Bármi legyen az eredmény, a visszaadott nyugta:

- `status=HOST_BOUNDARY_AUDIT_INCOMPLETE`, vagy hibánál
  `HOST_BOUNDARY_AUDIT_DENIED`
- `isolation_verified=false`
- `safe_to_revoke_legacy_docker_access=false`
- `safe_to_install_operator_secret=false`
- `production_deployment_authorized=false`

A modul **nem** MCP tool, nincs az M15 hordozható bootstrap
allowlistjében, nincs rendszerbe telepítve, nem kér és nem hajt végre
sudo, `docker`, shell, chmod, chown, stage/production módosítást.

## Natív elfogadási feltételek

- `tests/test_linux_m15f_host_boundary_audit.py`:
  PID/UID drift, valós PID-reuse, zárójeles folyamatnév,
  zombi állapot, procfs symlink, sérült/duplikált státusz,
  sok csoport, Docker DAC, hiányzó/átláthatatlan socket,
  hamis aktiválási engedély negatív ellenőrzése.
- `.github/workflows/m15f-native-host-audit.yml`:
  valódi ARM64 és x86-64 disposable GitHub runneren ellenőrzi a
  **saját CI processz PID + starttime** kerneladatát, majd a
  non-authorizing nyugtát. A GitHub-on mért jogok **nem Pi-audit**.
- A PR teljes `security-tests.yml` visszamenőleges regresszió.
- Az auditban semmilyen production restart vagy Docker kapcsolat nincs.

## Az éles privilege separation egyesített, feltételes átváltási kapuja

1. Helyi, független, tényleges Pi-host admin: systemd/tunnel
   processz-azonosság és PID-starttime, UID/GID/groups, sudoers,
   capability-k, Unix socket ACL, egyéb API/FD, host user namespace.
   Csak saját, jóváhagyott host-telepítésből származó bizonyíték
   fogadható el; a távoli MCP nem igazolhatja önmaga elszigetelését.
2. A távoli M12 közvetlen Docker-jogát még meg kell őrizni a 36/36
   eszköz viselkedésének *shadow* teszteléséhez; új policy mellett
   előbb külön `read-only Docker proxy` és szűk, jóváhagyott
   stage/sandbox lifecycle executor szükséges.
3. Tényleges rootful Docker helper nem lehet általános Docker CLI,
   és nem férhet hozzá a helyi approval titokhoz.
4. Csak teljes, hashhez kötött regresszió, signer/publisher
   lánc, felhasználói jóváhagyás, konténerszintű rollback és
   újraindítás után következhet a Docker-csoport/sudo megvonása.
5. A Pi `/opt/fieldwork` módosított Git checkout-ja nem automatikus
   release-bázis; külön tiszta, commit-pinnelt workspace szükséges.

**M15-F önmagában nem aktiválja a no-copy deployt.** A következő
üzemi kapu az éles Pi helyben jóváhagyott auditorának és az
elkülönített Docker lifecycle helpernek összevont, visszaállítható
migrációja. Az Orange Pi-n külön natív regresszió kell. PR marad DRAFT.
