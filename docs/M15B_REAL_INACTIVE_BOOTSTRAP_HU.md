# M15-B – ellenőrzött inaktív Linux bootstrap és visszaállítás

Állapot: **GitHub-hoston valódi telepítés és rollback PASS**, de
**Raspberry Pi / Orange Pi telepítés, szolgáltatásindítás és
jogosultsági leválasztás továbbra is BLOCKED**.

## Elkészült

- `updater/m15_inactive_bootstrap.py`: kizárólag root Linux
  rendszeren és fix `/opt/linux-mcp-operator` célkönyvtárba
  telepíthet az M15 ellenőrzött archívumából.
- Telepítés előtt **függetlenül megadott** konkrét 40-hex commit
  és külső 64-hex SHA256, belső archívumintegritás,
  pontos fájllista, Python AST/compile, root-owned nem
  csoportosan írható `/opt` ellenőrzése.
- Nem hajt végre forráskódot, nem hoz létre felhasználót,
  nem telepít/engedélyez/indít systemd unitot, nem kezel
  Docker-konténert, nem írja az M12 MCP-t vagy a FieldWork
  forrásait/adatbázisát. Csak a neve szerint megengedett
  Python modulok és a manifest másolhatók a fix célba,
  read-only root-owned fájlokkal. A végső
  `.complete.json` nyugta a sikeres fájltelepítés után jön.
- A CLI éles telepítési módja root és valós helyi TTY
  mellett külön `INSTALL_INACTIVE_M15B` beírását
  igényli. **Ez manuális helyi adminbeavatkozás,
  nem kriptográfiai bizonyíték a jelen levő emberről.**
  Nem távoli MCP művelet, nincs auto-activate.
- `rollback_inactive`: csak akkor távolíthatja el
  a FIX cél összes telepített fájlját, ha a könyvtár
  pontosan az ismert készletet tartalmazza,
  a nyugta/manifest forráspinja egyezik,
  minden hash változatlan és nincs egyetlen idegen
  fájl/symlink sem. **Nincs rekurzív törlés** és
  nem távolít el aktív szolgáltatást.
  Egy idegen fájl vagy eltérő hash esetén fail-closed,
  kézi lokális egyeztetés szükséges.
- Hibás/részleges telepítéskor a private 0700
  könyvtár szándékosan megmarad és az új
  install kísérlet megakad: nincs néma felülírás.

## Natív bizonyíték – 2026-10-31

[GitHub M15-B real root filesystem acceptance #41229491541](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41229491541):
**x86-64 PASS, natív ARM64 PASS**.

Mindkét ideiglenes Linux runneren:
1. normál userként offline M15 csomag preflight,
2. a tesztgépen külön, root jogosultságú, valós
   `/opt/linux-mcp-operator` fájltelepítés,
3. negatív rollback hamis külső SHA-val,
4. negatív rollback idegen fájllal,
5. pontosan egyező készlet visszaállítása,
6. végül `/opt/linux-mcp-operator` nincs jelen;
   service és Docker változtatás NINCS.

Az első két CI próbán a valódi host eltérő
`PosixPath` típusa és a GitHub runner
írásra megnyitott `/opt` könyvtárjogosultsága
kiváltotta a fail-closed ellenőrzést.
A típuskezelést javítottuk. A jogosultságokat
kizárólag a *disposable GitHub runneren*
állítottuk helyre root-owned, nem írható
szülőkönyvtárra. **Nem lazítottuk a
production könyvtárbiztonsági ellenőrzést.**

[Security suite #41229496378](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41229496378):
az automatikus negatív tesztek részeként
ellenőrzi a hibás forrás SHA-t, a rossz
commitot, az érvénytelen Python AST-t,
a hiányzó helyi jóváhagyást és a root-only kaput.

## Mi a következő TÉNYLEG szükséges release-gate?

A fenti bootstrap **csak inaktív telepítés**:
nem hoz létre a jelenlegi távoli M12 MCP-től
független, bizonyítottan elszigetelt operátori
Linux-felhasználót, és nem indít tényleges
systemd service-t. A külön account natív
`runuser`/systemd/loopback autentikációs
elfogadása még **NOT VERIFIED**.

Az élő FieldWork Pi-n a jelenlegi M12
`fieldwork_mcp.py` SHA256
`ee218971079b988e1e85b3790dd50228847e5e911e2e688b3df77972ad78b532`
és a Docker sockethez kapcsolódó
lehetséges root-ekvivalens jogosultságok
miatt nem lehet megbízható operátori
HMAC kulcsot vagy automatikus frissítő
szolgáltatást távoli oldalról telepíteni.
A jogosultságok valós független auditja,
tényleges publisher signature/trust,
a saját OS-principal, a fix-scope helper,
service smoke, rollback és M12
36-eszköz regresszió szükséges.

**A meglévő M12 `fieldwork_artifact_*`
csak inert feltöltési felület:** soha nem
használható host-script telepítési kerülőútnak.
A Pi-n sem az M13, sem az M14/M15 még
nincs telepítve. A GitHub a készülő
mérnöki forrás, nem távoli telepítő.

Várt végcél: egyszeri helyi, ténylegesen
jóváhagyott bootstrap, majd frissítések
távoli kérelemmel és **helyi jóváhagyással**,
ZIP/SSH másolgatás nélkül.
