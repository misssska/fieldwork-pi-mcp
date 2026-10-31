# M10 – Raspberry Pi Docker sandbox orphan-audit (2026-10-31)

**Állapot:** GitHub PR #2, CI-ben tesztelt, a Pi hoston NEM telepített
és NEM futtatott, kizárólag olvasási jelölt.

## Kiinduló bizonyítékok (élő MCP v0.6.1)

- `fieldwork_sandbox_command_status`:
  - `proposal_id=cfb10c47c1b3413c9adbd50e5c7249ef`
  - `run_id=b901aaabbbcccdddeeefff0000000020`
  - `status=RUNTIME_CLEANUP_FAILED`
  - `runtime_output=DOCKER_TIMEOUT`
  - `test_container cleanup ok=false`, külön DB/network/source cleanup true
  - `production_modified=false`, `production_mounts=false`
- A későbbi `c0ffee00000000000000000000000001` timeout
  `test_container cleanup=true` nyugtája **NEM** bizonyítja az előző
  azonosítójú konténer eltávolítását.
- Az éles `/api/health` és `/health` HTTP 200, a
  `fieldwork-stage` `STAGE_RUNNING_CHECK`. Ezek a saját Compose
  projektjeik állapotára vonatkoznak. A `fieldwork_compose_ps`
  **nem globális Docker konténerleltár**.
- Az aktív MCP `fieldwork_status` szerint host shell nincs, a
  sandbox parancsok **eldobható Docker-konténerben** futnak; ezért
  ugyanazzal az eszközzel nem lehet megbízható hostszintű Docker
  orphan-auditot végezni.

## GitHub-jelölt

`updater/pi_sandbox_orphan_audit.py`

- Egyetlen rögzített, helyi, csak olvasási `docker container ls --all
  --no-trunc --format '{{json .}}'` lekérdezés;
  `unix:///var/run/docker.sock` hostra szűkítve, a távoli
  `DOCKER_HOST` környezeti útvonalak kizárva.
- Nem root futtatás; nem fogad tetszőleges Docker-parancsot, képet,
  konténernevet, kötetet vagy fájlrendszerutat.
- A teljes JSONL host-inventoryt legfeljebb 256 tételben és
  1 MiB méretig, szigorú JSON-/64 hex ID-ellenőrzéssel értelmezi.
- A megadott, teljes, 32 hex karakteres `run_id` név-/címke
  egyezéseit jelöli; nyers Docker nevek, címkék, portok,
  env változók, mountok nem kerülnek a válaszba.
- Eltérő/hiányzó run marker esetén **nem állítja**, hogy a
  korábbi sikertelen takarítás helyreállt. A lehetséges eredmény:
  `HISTORICAL_CLEANUP_UNVERIFIED_NO_EXACT_MATCH`.
- Pontos marker találatkor az állapot
  `HISTORICAL_ORPHAN_CANDIDATE_FOUND_REVIEW_REQUIRED`; **akkor
  sem ad eltávolítási jogot**. A jelölt konténer lehet álnevesített
  vagy éles munkához tartozó; automatikus törlés nem megengedett.
- `historical_cleanup_receipt_resolved=false`,
  `sandbox_test_retry_authorized=false`,
  `container_removal_authorized=false`, a `production_modified`
  mindig false.
- Docker hiba, timeout, nem UTF-8 kimenet, duplikált vagy nem teljes
  container ID, túl sok sor esetén fail-closed.

`tests/test_pi_sandbox_orphan_audit.py`

- Negatív és biztonsági tesztek: pontos ID és label felismerés,
  félbevágott/hamisító azonosítók, prod-/stage konténerek
  téves jelölése, rejtett label adatok, hibás JSON és túl nagy
  inventory, csak olvasási fix Docker argv, nincs `rm` vagy
  `stop` futtatás.
- Docker-hívások a CI-ben mockoltak, ez **nem** valódi Pi-host audit.

## Miért nincs még tényleges takarítás?

A régi MCP v0.6.1 host-szintű jogosultsági szerződését nem
kerülhetjük meg egy másik sandbox-paranccsal. Egy élő, jóváhagyott
`fieldwork_sandbox_orphan_audit` csak külön, helyileg ellenőrzött
MCP-kiegészítőként telepíthető az operator kifejezett, arra a verzióra
szóló jóváhagyásával. Ez a PR önmagában nem telepít kódot.

A régi konténernevek és címkék nem igazoltan hordozzák a futás
teljes azonosítóját. **Puszta nulla egyezés nem bizonyít
orphan-mentességet.** Valódi helyi Docker-host leltár és a
problémás timeout után esetleg megmaradt konténer tulajdonosi,
mount-, hálózati, Compose-/image-ellenőrzése kell. Eltávolítás
esetén külön, egyértelműen azonosított konténerre szóló
helyi jóváhagyás és újraellenőrzött cleanup-bizonyíték szükséges.

## M10 elfogadási kapu

1. A read-only leltár a Pi-n sikeresen, az aktuális host Docker
   daemon ellen futott, és a rossz korábbi cleanup receiptet
   külön hivatkozza.
2. Minden potenciális árva és minden prod/stage erőforrás
   identitása dokumentált, ütközés nincs.
3. A konkrét régi futás cleanupja hostoldalon bizonyítottan
   rendezett; nem csak egy újabb futás cleanupja PASS.
4. A tiszta, privát Git-bázis egyszeri operator-jóváhagyása
   megtörtént, majd a teljes FieldWork valós tesztelése
   külön izolált környezetben sikeres.

**M10 host-audit jelenleg BLOCKED. Nincs kézi SSH-utasítás
vagy kockázatos automatikus takarítás. Nincs Pi deploy,
új tunnel, DB-módosítás, stage restart.**

## 2026-10-31 – valós Docker daemon ellenőrzés, GitHub CI (nem Pi)

Az [M10 Docker integration workflow](../.github/workflows/m10-docker-orphan-smoke.yml)
a GitHub által biztosított `ubuntu-24.04` hoston, **valódi Docker
daemonnal**, két kizárólag CI-ben létrehozott, nem futó és
`--network=none` állapotú szintetikus konténert alkalmazott.

- [GitHub Actions #41205255857](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41205255857): **SUCCESS**.
- `M10_REAL_DOCKER_HOST_READONLY_AUDIT_PASS`: a rögzített Docker
  parancs kimenete helyesen feldolgozható volt.
- `M10_CANDIDATES_PRESENT_BUT_NOT_CLEARED_PASS`: a megadott
  32-hex futási azonosítójú konténert megtalálta, de nem adott
  eltávolítási jogot és nem törölte a korábbi hibanyugtát.
- `M10_ZERO_MATCH_CANNOT_CLEAR_HISTORICAL_FAILURE_PASS`:
  ellenőrzött nulla találat sem állít elő hamis cleanup-PASS-t.
- `M10_AUDITOR_DID_NOT_MUTATE_CONTAINERS_PASS`: mindkét
  szintetikus konténer a *létrehozás utáni*, változatlan állapotban
  maradt az audit végén. A CI workflow a saját tesztkonténereit
  külön `EXIT`-trap segítségével eltakarította; **ez nem az
  auditor művelete**.
- Nincs GitHub/Pi kapcsolat, nincsenek hálózati címek, hitelesítő
  adatok, production DB- vagy volume mountok a szintetikus CI-ban.

**Ez a Docker-adapter valódi futásának igazolása, nem a Raspberry Pi
hostjának ellenőrzése.** A régi `b901aaabbbcccdddeeefff0000000020`
kísérlet `RUNTIME_CLEANUP_FAILED` nyugtája változatlan.

Az M10 host-AUDIT ACCEPTANCE továbbra is **BLOCKED**.
Az aktív Pi MCP 0.6.1 nem ad ki globális Docker inventoryt.
Egy helyben jóváhagyott, kizárólag olvasási MCP-képesség
kiadása és hoston való igazolása szükséges; ennek hiányában
nincs automatikus Pi audit, restart vagy konténereltávolítás.

## 2026-10-31 – Egyparancsos, integritásellenőrzött helyi audit

A korábbi GitHub-jelöltnek már van **fix, argumentummentes** belépője:
`python3 updater/pi_sandbox_orphan_audit.py`. Az auditori modul
továbbra sem regisztrált MCP-eszköz, és a ChatGPT továbbra sem
rendelkezik engedéllyel a Pi Docker-socketének hostszintű olvasására.

A korábbi futás neve és címkéje esetleg nem tartalmazza a teljes
run ID-t; ezért az új verzió az összes tárolt konténerből
**korlátozott, titokmentes osztályozást** is ad:
`recognized_compose_project_label_count`,
`unclassified_container_count`,
`unclassified_container_sample` (max. 16 db, csak 64 hex ID
és állapot), `unclassified_sample_truncated`.
A két ismert Compose-projekt címkéjét felismeri, de a címkék
önbevallott értékek, nem hiteles tulajdonjogi bizonyítékok.
Sem egy egyezés, sem a nulla találat nem ad törlési jogot.

**Integritásbizonyíték:** natív GitHub Actions
[CI #41206659441](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41206659441)
**468 updater + 12 bootstrap = 480/480 PASS**;
[Docker CI #41206655412](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41206655412)
**SUCCESS**, a rögzített CLI valódi Docker daemonon is
fail-closed működik.

- Rögzített commit:
  `17323aadb05a41cbebe41af19199c310bacbe93c`
- A `updater/pi_sandbox_orphan_audit.py` teljes, GitHub CI által
  kiírt SHA256:
  `92ac35f8246113db26eb1d89a5c081ff59ae89b73683d6fa832556cf9d573944`

**Egyetlen helyi operátori parancs**, amely nem ment ZIP-et,
nem telepít MCP-t, nem használ `sudo`-t, és kizárólag a fenti
SHA256-mal egyező forrást hajtja végre. Csak akkor szabad futtatni,
ha a Pi tulajdonosa kifejezetten jóváhagyja a
*csak olvasási Docker-host inventory* lekérdezést.

```sh
python3 -c 'import hashlib,urllib.request;u="https://raw.githubusercontent.com/misssska/fieldwork-pi-mcp/17323aadb05a41cbebe41af19199c310bacbe93c/updater/pi_sandbox_orphan_audit.py";b=urllib.request.urlopen(u,timeout=15).read(32769);assert len(b)<32769 and hashlib.sha256(b).hexdigest()=="92ac35f8246113db26eb1d89a5c081ff59ae89b73683d6fa832556cf9d573944","AUDIT_SHA256_MISMATCH";exec(compile(b,"sha256_verified_m10_audit.py","exec"))'
```

A fenti program csak olvassa a Docker host teljes listáját.
A letöltött és SHA-ellenőrzött forrást memóriából futtatja,
nem módosítja az éles FieldWork, Docker vagy MCP konfigurációt.
A telepített Python3 és a helyi felhasználó meglévő Docker-
lekérdezési jogosultsága szükséges. Ha a hozzáférés tiltott,
`AUDIT_BLOCKED` kimenetet ad; tilos automatikusan `sudo`-val
vagy új jogosultság adásával megismételni.

Az eredmény egyetlen, titokmentes JSON. Az operátor ezt
visszamásolhatja a ChatGPT-be további **kiolvasó elemzéshez**.
Amíg nincs a régi hibás runnal összeegyeztethető, független
hostoldali bizonyíték, a tesztkörnyezeti cleanup státusz
**BLOCKED** marad. Az audit NEM hajt végre takarítást.

**Helyi futási bizonyíték a Raspberry Pi-ről jelenleg nincs.**
A forrás és a workflow kizárólag a GitHub fejlesztői ágán van.

## 2026-10-31 – ELSŐ VALÓDI RASPBERRY PI HOST-LELTÁR (felhasználói nyugta)

A Pi tulajdonosa az előző fejezetben SHA256-tal rögzített
`pi_sandbox_orphan_audit.py` egyparancsos, csak olvasási ellenőrzését
**ténylegesen a Raspberry Pi hoston** lefuttatta. A teljes JSON-nyugtát,
majd ugyanott egy külön, olvasási `docker ps -a --no-trunc` Python
lekérdezésből a 20 kezdetben nem osztályozott konténer
nevét/állapotát/létrehozási idejét is visszaküldte. Nincs ismert
Docker-módosító művelet.

### Rögzített bizonyíték és megállapítás

- `inventory_source=local_docker_container_ls_all`
- `inventory_sha256=d1c0560c843b1d018f992d47da5bb54110e89650a94ddfd7125856647bf4adab`
- `inventory_container_count=26`
- `recognized_compose_project_label_count=6`
- `unclassified_container_count=20`; a 16 elemű mintából
  `unclassified_sample_truncated=true` volt, a későbbi teljes
  manuális névlista mind a 20-at azonosította
- A korábbi hibás runra `candidate_count=0`, nincs a név-/címke-
  mezőkben pontos teljes 32-hex egyezés
- A 20 elemből 12 `running`: `fieldwork-plan-m2` (3),
  `fieldwork-parity-m3` (3), `m4` (3), `m5` (3)
- A további 8 `exited`: korábbi `fieldwork-test` (1),
  `fieldwork-candidate-592c4be` (3),
  `fieldwork-review-test` (2), `hello-world` (2)
- A teljes leltár **legfiatalabb konténerei** 2026-10-30
  22:36:56 CET-kor keletkeztek, a problémás sandbox
  `b901aaabbbcccdddeeefff0000000020` nyugtája
  2026-10-31 12:58:51 UTC-kor, azaz 13:58:51 CET-kor.
  Tehát a leltárban nincs a sikertelen futás után létrehozott,
  akkor még fennálló konténer.
- `host_modified=false`, `production_modified=false`,
  `tunnel_modified=false`, `container_removal_authorized=false`.
- Az újraolvasott tartós régi nyugta **továbbra is**
  `RUNTIME_CLEANUP_FAILED`/`DOCKER_TIMEOUT`/
  `test_container cleanup=false`; nem hamisítunk
  visszamenőleges cleanup PASS-t.

**Következtetés:**
`CURRENT_HOST_INVENTORY_NO_RECENT_SANDBOX_ORPHAN_OBSERVED` –
ez az adott pillanatban érvényes, tényleges host Docker-listán
alapuló negatív megfigyelés. A történelmi cleanup receipt
státusz továbbra is FAIL; az újraindítandó tesztfuttató timeout/
cleanup viselkedését *külön* biztonsági hibaként kell vizsgálni.
Nem teljesített a `FULL_TEST_RETRY_APPROVED` kapu, mert a
futtató helyben auditált, hibát fail-closed módon kezelő javítása
még hiányzik.

**Érintetlen:** az éles `fieldwork`, a meglévő stage és mind a
négy másik, háromkonténeres FieldWork Compose projekt. A
`fieldwork-plan-m2` és `fieldwork-parity-m3/m4/m5` projektek
megszüntetése, konténereinek vagy köteteinek tisztítása NINCS
engedélyezve; ezek létjogosultságát külön projektgazdai döntés
nélkül nem szabad megkérdőjelezhetetlenül elavultnak tekinteni.

### Következő kapu

1. A futó Pi v0.6.1 sandbox-runner timeout + cleanup
   implementációjának **read-only source-review** és
   helyileg, elkülönítve ellenőrzött javítása (kifejezetten a
   `test_container cleanup=false` esetére).
2. A javított futtató telepítése csak pontos forráshash,
   célzott, szűk helyi engedély, backup, rollback és
   production-szeparáció után.
3. Csak ezután a valódi FieldWork backend és frontend teszt
   újrapróbálása külön, tiszta canary-snapshotból.

A Raspberry Pi-n most nincs új teszt, új MCP-telepítés,
Docker leállítás/törlés, adatbázis-/tunnel- vagy production
módosítás. A PR továbbra is **draft**.
