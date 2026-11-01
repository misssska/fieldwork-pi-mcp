# M14-A – történeti fázis; az új jóváhagyó UI már elkészült

Az alábbi dokumentáció az M14 induló állapotát mutatja.
A korábban hiányzó **offline, localhost-only böngészős jóváhagyó**
és az aláírt helyi átadás már elkészült. Aktuális részletek:
[M14-B helyi böngészős jóváhagyó](M14B_LOCAL_BROWSER_APPROVAL_HU.md).
Az önálló, külön OS-felhasználóként futó és
biztonságosan távolról elérhető szolgáltatás
továbbra sincs telepítve.

---

# M14 – SSH-másolgatás nélküli, gépenként jóváhagyott Linux MCP-frissítések

Állapot: **GITHUBON FEJLESZTETT ÉS TESZTELT BIZTONSÁGI MAG.**
A Raspberry Pi-n jelenleg továbbra is az M12 aktív. A külön M13
CPU/RAM-mérő még nincs telepítve. Ez az M14 csomag jelenleg
**nem regisztrál új MCP-eszközt, nincs még operator UI, daemon,
telepítés vagy automatikus Pi-újraindítás**.

## Cél és a valódi probléma

A cél nem az újabb SHA256-parancssor generálása.
A jövőbeli általános Linux MCP-hez tartozzon **egyszer
telepített**, helyi policy-val korlátozott frissítő, amely után
egy új változat létrehozása, ellenőrzése, Pi-re juttatása
és jóváhagyott aktiválása nem igényel minden alkalommal
ZIP-letöltést, kézi Python-kódot vagy SSH-másolgatást.

Nem használhatunk a jelenlegi FieldWork Pi MCP v0.6.1/M12
eszközeivel tetszőleges host shellt vagy önmódosítást:
ezek nem részei a jelenleg engedélyezett MCP szerződésnek.
A `fieldwork_artifact_*` upload csak **inert feltöltési
tárhely**, nem telepítési és nem végrehajtási felhatalmazás.
Nem szabad kerülőútként alkalmazni.

## Biztonsági protokoll (M14)

```text
ChatGPT (távoli, NEM megbízható telepítő)
    | csak javaslat: pontos host_id + immutable commit +
    | SHA-256-tal megadott MCP Python modulok
    v
MCP oldali, korlátozott javaslat-inbox
    | immutable 0600 manifest, maximum 12 fájl,
    | pontos policy allowlist, ttl < 1h, audit
    | itt sem letöltött kód, sem aktiválás nem fut
    v
HELYI APPROVER (külön OS-felhasználó / biztonsági kör)
    | a felhasználó a teljes változtatást ellenőrzi
    | és külön helyi jóváhagyást ad
    | helyben védett HMAC kulcs, nem látható az MCP-nek
    v
HELYI INSTALLER (nem MCP-eszköz)
    | check source hash + Python AST + receipt + lock
    | atomic backup / write / restart+health / rollback
    | csak az előre kijelölt, user-owned MCP-modulok
    v
Raspberry Pi, Orange Pi vagy más támogatott Linux MCP
```

Ez a kód **nem helyettesíti a helyi approver UI-t**:
a `operator_present=True` argumentum önmagában nem
bizonyít valódi emberi jelenlétet. A production
telepítéshez az operátori döntést valódi, külön
hitelesített UI-n és külön OS-védelmen keresztül
kell megszerezni.

### Elkészült forráskomponensek

1. `updater/linux_upgrade_gate.py`
   - Géphez kötött `host_id`, 40-hex Git commit,
     pontos korábbi/új SHA256, szigorú fájlnévlista,
     egyező aktív bájtlenyomat, lejárat és tiltott
     extra request mezők ellenőrzése.
   - Másik gépre készített javaslatot elutasít.
   - Állapot `LOCAL_REVIEW_REQUIRED`, nincs távoli
     aktiválás.
   - Az exact javaslat SHA256-jához és host ID-hoz
     kötött HMAC jóváhagyás, lejárat, egyszer használatos
     nonce; a titkos kulcs csak a helyi approver
     birtokában lehet.
2. `updater/linux_upgrade_inbox.py`
   - Csak privát, már létező, helyileg kiválasztott
     0700 könyvtárba írható, 0600 és atomi,
     megváltoztathatatlan manifest.
   - Nem tárol jelszót, privát kulcsot vagy
     forráskódbájtokat. Nincs öntelepítés.
   - Idempotens ismételt javaslat, symlink
     és hamisított receipt elutasítása.
3. `updater/linux_upgrade_local_transaction.py`
   - **CSAK HELYI** transaction engine, nem
     MCP handler, nem telepítve a Pi-n.
   - Exact approval, új forráshash és Python AST
     ellenőrzés; kizárólag helyileg kijelölt MCP
     install- és state-könyvtárak, futó éles
     FieldWork alkalmazás és DB nélkül.
   - Processzszintű `flock` zárolás, durable
     0600 backup és nonce ledger, hash-szel
     rögzített `PREPARED → APPLYING → APPLIED`
     nyugták, negatív health esetén rollback.
   - Félbeszakadt tranzakcióra külön
     `recover_unfinished`; csak várható old/new
     bájtokkal és egyező manifest/journal digest
     mellett. **Minden target preflight-ja megtörténik
     bármely rollback-írás előtt**.
   - Semmilyen programkódot nem hajt végre a
     `source_bytes` tartalmából, csak AST-t/compile-t
     ellenőriz. A külön felhatalmazott lokális
     adapternek kell kizárólag a fix MCP service-t
     újraindítania és ellenőriznie.

### Ami még nincs kész és nélkülözhetetlen

- A **helyi, hitelesített jóváhagyó UI**,
  amely telefonon/böngészőn keresztül
  elérhető, de nem enged kihasználható
  LAN/Tunnel/CSRF utat. Jelenleg nincs ilyen
  M14 UI megvalósítva és hitelesítve.
- A **külön OS-biztonsági tartomány**
  létesítése. A jelenlegi MCP admin-felhasználóként
  a Docker sockethez is hozzáférhet. Az MCP
  folyamat és az approver titkos kulcsa nem
  osztozhat védelem nélkül ugyanazon a Unix
  felhasználón. A külön userhez viszont
  szűk, helyi fájljogosultság és csak az
  engedélyezett MCP service restart kell.
  Ezt a működő M12/tunnel regressziója nélkül
  kell bevezetni.
- A trust/publisher-döntés: SHA256 és
  HMAC a forrásbájt-egyezést, valamint a
  helyi jóváhagyást bizonyítja, **nem**
  a letöltött Python-kód jószándékát.
  Kiadásonként CI, code review, változáslista,
  pontos fájlhashek és visszaállítás szükséges.
- A távoli inbox MCP-regisztrációja, lokális
  manifest átadás a privilegizált helpernek,
  reboot utáni restore-gate, health és
  a valós Pi/Orange Pi natív elfogadás.
- A teljes M13 kód és M14 upgrade agent
  egyszeri, helyben jóváhagyott bootstrappel
  kerülhet majd először a Pi-re.
  A **már aktív** M12 nem jogosult saját
  maga kibővítésére: jelenleg nincs
  eszközhívás, amellyel ezt SSH nélkül
  megtehetnénk. Emiatt a még hiányzó
  bridge-et nem állítjuk késznek.

## Teszt/elfogadás

A GitHubban külön negatív tesztek vannak:
`tests/test_linux_upgrade_gate.py`,
`tests/test_linux_upgrade_inbox.py`,
`tests/test_linux_upgrade_local_transaction.py`.
A suite a pontos host ID-eltérést, a fájl-/parancs-
injektálást, a replayt, a lejáratot, a hibás
HMAC-et, a hash/AST driftet, a symlinkeket,
a sikertelen health-et, az atomikus rollbacket
és a crash recoveryt vizsgálja. A teszt-Python
fájlok csak izolált `TemporaryDirectory`
könyvtárakat módosítanak, nem éles szolgáltatást.

Előírt M14 kapuk:
- GitHub Linux x86-64 és **valódi ARM64** CI PASS.
- Kizárólag offline helper, éles Pi és Orange Pi
  változtatás nélkül.
- Helyi operator UI külön hitelesítés és
  privilege-boundary biztonsági audit.
- Egyszeri, explicit helyi bootstrap, atomic
  backup és rollback natív host teszt.
- Későbbi frissítés már csak egy helyben
  jóváhagyott UI-műveletet igényel:
  **ne legyen újabb parancs- vagy ZIP-másolás**.

A készülő univerzális agentnél nem használunk
tetszőleges shellt, általános Docker stop/rm-t,
production DB-hozzáférést vagy jóváhagyás nélküli
host self-update-et.
