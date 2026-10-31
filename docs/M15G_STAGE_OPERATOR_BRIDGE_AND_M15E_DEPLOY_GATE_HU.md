# M15-G – operátori UID-hez kötött, meglévő stage-konténer végrehajtó

**2026-10-31. Csak GitHub Draft PR / CI, nem telepített Pi szolgáltatás.**

## Miért nem telepíthető még az M15-E élesben?

Az M15-E (`updater/linux_approval_redeemer.py`) tesztelt,
de nem host-telepítő: a külön operátori UID/HMAC-kulcs és
Docker-segéd szerepkörök még nincsenek hitelesen elkülönítve a Pi-n.
Az élő FieldWork Pi MCP 36 megengedett művelete között nincs
új systemd-service telepítésre/aktiválásra alkalmas jóváhagyott
host API. A `fieldwork_artifact_*` műveletek csak **inert**
bájtátvitelt és forrásvalidálást tesznek lehetővé, végrehajtást nem.
Nem nevezhető telepítésnek az, ha M15-E forrást csak átmásolunk.

A rendszer biztonságos sorrendje:
1. külön, root által rögzített host-felmérés a valódi M12 UID/Docker/sudo
   jogosultságokról és a helyi HMAC-titok elérhetetlenségéről;
2. izolált, nem privilegizált operátori UID/szolgáltatás,
   valódi, ember által kifejezetten engedélyezett **egyetlen**
   bounded host bootstrap; M15-E *inactive* telepítés és ugyanabban
   az eljárásban rollback + helyi integritásellenőrzés;
3. külön Docker helper próba, az M12 összes eszközének regressziója;
4. csak utána az éles no-copy frissítési útvonal aktiválása.

Az M15-E CI-kód Python könyvtár, nem kész, önálló
`systemctl enable` telepítő; a rendszernek hiányoznak a
valódi publisher trust és operátori UI kapui.

## Mit készítettünk most?

`updater/linux_m15g_stage_operator_bridge.py`:

- **Csak AF_UNIX `SO_PEERCRED` kernelazonosítás.**
- Három, egymástól eltérő nem root UID: `operator`,
  `mcp`, `helper`. Kizárólag az előre ismert operátori
  UID indíthat szűken rögzített akciót. A távoli MCP UID,
  root UID és helper UID kérését elutasítja.
- Bejövő kérésben nincs tetszőleges konténernév,
  projekt, Docker parancs, image, útvonal vagy
  mount; csak az előre helyben rögzített és
  exact SHA-hoz kötött tervlenyomat.
- A meglévő, külön tesztelt `linux_stage_existing_lifecycle.py`
  M14-E kódját használja a **három, már létező**
  `fieldwork-stage-api/db/nginx-1` konténer
  Docker ID/címke/pre-state ellenőrzésére,
  `start`/`stop` műveletre és
  `PREPARED→APPLYING→COMMITTED/ROLLED_BACK`
  naplózásra.
- A helper tesztben saját, csak az eljáráshoz használt
  HMAC-jegyet készít az OS-UID-gate után. Ez
  **nem az M15-E teljes integrációja, és nem
  bizonyítja a fizikai kezelő jelenlétét**.
  Docker-hoz kapcsolódó helper általános rootful
  Docker hoston továbbra is root-egyenértékű.
- A régi `stage_manager.py` / `runtime_runner.py`
  és a Docker proxyt használó szolgáltatások
  továbbra is változatlanok. Nincs használatban
  éles MCP endpointként; a távoli MCP funkciók
  nem kerültek át a bridge-re.
- **Nem támogat** `docker compose build/up`,
  nem hoz létre konténert, hálózatot, volume-ot.
  Sandbox `docker run`/takarítás és 36/36 end-to-end
  migráció továbbra is hátra van.

## Ellenőrzési terv

`tests/test_linux_m15g_stage_operator_bridge.py`:
pozitív háromkonténeres `stop`, tartós journal,
távoli/rossz/root UID, dupla JSON-kulcs, extra
mező, hamis/lejárt plan, megváltozott Docker ID,
sikertelen Docker és rollback, replay,
valódi Linux `socketpair SO_PEERCRED` negatív
tesztek. A Docker itt memóriában szimulált;
nincs éles Pi Docker-mutáció.

Natív GitHub ARM64 és x86-64 unit/regresszió,
illetve teljes korábbi biztonsági suite:
`.github/workflows/m15g-stage-operator-bridge.yml`.

## Döntési kapu

**Nincs Pi-re telepített M15-E és M15-G**, nincs
systemd/socket/user/group/permission módosítás,
production/staging konténer-, adatbázis- vagy
tunnel restart.

M15-H valós kvalifikációhoz előbb a Docker
jogosultságok különválasztása, jóváhagyott
host-integritás, valódi helyi user approval,
teljes stage/sandbox-regresszió és rollback
szükséges. Addig a Draft PR marad DRAFT.


## M15-E telepítőcsomag – új, bizonyított inaktív kvalifikáció

Az M15-E tényleges Python-forrásmodulja
(`updater/linux_approval_redeemer.py`) bekerült a
`updater/m15_portable_bundle.py` exact allowlistjébe.
A meglévő `linux_upgrade_gate.py` függősége is a csomag
része. Az M15-B root-owned, inaktív telepítője külön,
rögzített Git commit + külső SHA256 + helyi admin-jóváhagyás
mellett telepítheti a validált modult az
`/opt/linux-mcp-operator/linux_approval_redeemer.py`
fájlba, **a szolgáltatás bekapcsolása nélkül**.

A `tests/test_m15e_inactive_bundle.py` 4 negatív/pozitív
esetet fed le: determinisztikus archívum,
exact forráslenyomat, hiányzó vagy hamisított M15-E
elutasítása, jóváhagyás nélküli inaktív install STOP.

**Valódi, de NEM Pi telepítés:** GitHub Actions
[#41234739074](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41234739074):
ARM64 és x86-64 natív Linuxon root-owned,
írásvédett M15-E fájl és a hozzá tartozó manifest
egy ideiglenes `/opt/linux-mcp-operator` célkönyvtárba
való telepítése, SHA egyezése, hamis rollback pin és
idegen fájl elutasítása, végül a jóváhagyott pontos
rollback: **mindkét architektúra PASS**.

**Bájtra reprodukálható csomag:** GitHub Actions
[#41234739146](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41234739146):
mindkét natív architektúrán egyezik a csomag.
A konkrét, `6bbf02a082622cc52486582130ab6d0ac4e5f605`
Git commit CI-verziójának archívum SHA256-ja:
`bf997550d86fcc16ac9ce60c6a4e42ae7269b431832c46e1b23b1d4de01b6ca9`.
Ez az SHA **nem automatikusan bizalmi publisher signature**,
és későbbi commitnál újra kell számolni.

**Teljes aktuális regresszió:** GitHub Actions
[#41234739062](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41234739062):
`832` updater + `12` bootstrap = **844/844 PASS**.
M15-G natív teszt [#41234739071](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41234739071):
**10/10 PASS** mindkét architektúrán.

**Mi marad blokkolt?** A Pi oldali MCP csak inert
artifactátvitelt támogat; az M15-B telepítő gyökérszintű
helyi terminál/jóváhagyás nélkül nem hívható meg
biztonságosan. Nincs független Pi-host audit, telepített
operátori UID vagy systemd service, még nem készült
a telefonos helyi jóváhagyás, nincs M15-E éles
aktiválás. Az élő Pi `/opt/fieldwork` és Docker
továbbra is változatlan.
