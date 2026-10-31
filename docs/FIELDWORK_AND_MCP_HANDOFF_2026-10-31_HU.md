# FieldWork + FieldWork Pi MCP – hitelesített átadási checkpoint
**Dátum:** 2026-10-31 (Europe/Budapest)  
**Működési elv:** előbb mért tény, utána becslés/terv; production írás/restart/deploy nélkül.  
**TÁROLÓ:** ez a dokumentum az `misssska/fieldwork-pi-mcp` **Draft PR #2** fejlesztési ágán található. Nem a teljes FieldWork-alkalmazás forrásmentése.

## 0. Folytatáshoz szükséges fix referenciák

- MCP repository: `misssska/fieldwork-pi-mcp`.
- Fejlesztési branch: `feat/artifact-inbox-no-manual-copy-20261030`.
- Draft PR: https://github.com/misssska/fieldwork-pi-mcp/pull/2 — **nem merge-elni, nem release-elni automatikusan**.
- M15J3/J4 kvalifikált *kód* alapcommit: `47ba4f976a0021606a6eaea8864f6900a0977fd3`. Ez a checkpoint hozzáadásakor már új commit keletkezik; a két commit szerepe különbözik.
- Részletes M15-J célarchitektúra és natív tesztek: `docs/M15J_REAL_PI_ROOTFUL_DOCKER_MIGRATION_HU.md`.
- FieldWork alkalmazás Pi munkakönyvtár: `/opt/fieldwork`, helyi `main` branch, **nem tiszta Git-munkafa**; ennél a mentésnél nem commitoltuk, nem stash-eltük és nem írtuk át.
- Az alkalmazás saját GitHub remote-ja **NINCS IGAZOLVA**; a felhasználó GitHub-repository keresésekor a `fieldwork-pi-mcp` jelenik meg, külön FieldWork-alkalmazás-repo nem azonosítható. Nem szabad a helyi `/opt/fieldwork` fát a publikus MCP-repositoryba feltölteni.

## 1. 2026-10-31-én ténylegesen, read-only MCP-n mért Pi-állapot

| Ellenőrzés | Eredmény |
|---|---|
| Aktív MCP | `v0.6.1`, production read-only, sandbox és engedélyezett fix staging műveletek |
| FieldWork production HTTP | `/api/health` 200 `{"status":"ok"}`; `/health` 200 |
| Staging | `fieldwork_stage_smoke: STAGE_HEALTH_PASS`; `fieldwork_stage_status: STAGE_RUNNING_CHECK` |
| Docker produkció | `fieldwork-{nginx,api,db}-1` mind running |
| Docker staging | `fieldwork-stage-{nginx,api,db}-1` mind running |
| MCP source | `fieldwork_mcp.py` SHA256 `ee218971079b988e1e85b3790dd50228847e5e911e2e688b3df77972ad78b532`; `mcp_modified=false` |
| App helyi Git | `main`, **módosított tracked + untracked**; a diff és az eltérések eredete még nincsenek auditálva |

A production és staging státusz egy adott pillanatban lett ellenőrizve, nem jelent jövőbeli uptime-garanciát. A Git-munkafa már a felméréskor piszkos; ettől nem következik, hogy az MCP-kör módosította.

**Biztonság:** sem a GitHub-checkpoint mentése, sem az MCP read-only lekérdezései nem engedélyeznek production deploy-t, adatbázisírást, host shellt, Docker-csoportmódosítást vagy service-restartot.

### Alkalmazás saját dokumentációja – régi, NEM aktuális készültségi százalék

A `/opt/fieldwork/docs/PROGRESS.md` és `docs/REFERENCE_PARITY.md` **2026-07-20** dátumú. Az ott szereplő **34,5%** a júliusi validáció, **nem bizonyított 2026-10-31-i aktuális készültség**. Az októberi staging fejlesztések miatt a kézi feladat-, dokumentum- és UI-folyamatokat újra kell validálni; a régi százalékot nem szabad mechanikusan továbbvinni.

A tényleges referencia: `reference/fieldwork-22.html`. Ez egy kliensoldali UI/workflow minta, **nem** production jogosultsági vagy DB-architektúra minta.

## 2. 2026-10-30-as/31-es, korábbi felhasználói funkcionális bizonyíték és korlát

- Stagingre telepített, elérhető FieldWork: belépés, projekt és alprojekt létrehozása, kép/PDF upload és előnézet felhasználói próbában működött.
- A feladat-létrehozás kezdeti hibáját külön TaskFix körben javítottuk; az akkori felhasználói visszajelzés `működik minden`. Ez **nem teljes, aktuális automata E2E paritás**.
- A ReferenceTaskBoard / PlanWorkspace integrációkor frontend strict TypeScript/ESLint/teszt PASS volt; a korábbi backend izolált kapu egyik körben FAIL volt. A friss end-to-end app-validáció ennek ellenére **PENDING**.
- Minta vizuális és funkcionális reprodukció, **többfelhasználós jogosultsági alap** a felhasználói cél. A későbbi extrák ezt követik.
- Nem állítható, hogy a teljes 85 KB-os referencia, annotáció, team-jogok, offline sync, naptár, PDF-rajzolás és összes workflow már paritásban működik.

## 3. Pi host jogosultság – független helyi audit, aktiválás blokkolva

A felhasználó a Pi saját SSH termináljában, helyi adminnal mért:
- root `dockerd` (eUID 0), `/var/run/docker.sock` UID 0 / Docker GID / mode 0660;
- `fieldwork-pi-tunnel.service` `admin` UID 1000, az MCP Python a tunnel gyermekfolyamata;
- `admin` Docker- ÉS sudo-csoporttagság; MCP Docker DAC write possible és Docker-csoporttagság;
- nincs releváns CapEff, `NoNewPrivs=true` — **nem elég** a rootful Docker hozzáférés ellen.
- M15-E `/opt/linux-mcp-operator/linux_approval_redeemer.py`: root UID0, `0444`, **csak telepített inaktív Python-forrás**.

**Döntés:** rootful Docker-sockettel a távoli MCP potenciálisan host-root-ekvivalens. `M15E_SERVICE_ACTIVATION=BLOCKED`; nincs HMAC titok, nincs külön operator/remote UID és aktív approval service, nincs 36/36 shadow migration. Nem szabad `admin` Docker/sudo csoporthoz, éles tunnelhez, production Compose-hoz vagy `/opt/fieldwork` DB-hez hozzányúlni csak azért, hogy egy gate átmenjen.

## 4. A GitHubon ténylegesen elkészült M15-J fejlődési lánc

- **J1:** pontos 36/36 MCP-tool lista / 4 forrás SHA pin. Besorolás: 26 no Docker, 5 Docker read-only, 3 staging Compose write, 2 sandbox write. Negatív felvételi gate, **nem** cutover approval.
- **J2:** OCI-digest-pinned, network none/read-only/nem root, valós Docker create/start/wait/owner+ID inspect/cleanup. ARM64/x86-64 natív CI PASS.
- **J3:** külön, csak CI-beli internal network + PostgreSQL tmpfs DB + SQL-kliens, `SELECT 1`, label/full ID/foreign endpoint ellenőrzés, DB/test/network takarítás. ARM64/x86-64 valós CI PASS.
- **J4:** fix, helyben generált, háromszolgáltatásos (`api/db/nginx`) Compose fixture, pontos digestű image-ek, két valós image-build, HTTP proxy és SQL health, `docker compose down` + maradványellenőrzés. ARM64/x86-64 valós CI PASS. A buildnél talált `HOME=/nonexistent` probléma javítva.
- **Regresszió:** [MCP updater suite #41240057045](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41240057045) **901 updater + 12 bootstrap = 913/913 PASS**. A checkpoint előtti `47ba4f9...` commit összes kapcsolódó CI workflow-ja is sikeres.
- Bizonyíték: [J3 SQL CI #41240056912](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41240056912), [J4 Compose CI #41240056933](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41240056933).
- **Fontos**: ezek izolált teszt-*fixture*-ök; NEM a tényleges `/opt/fieldwork` app M12 stage/DB-migrációja, nem az MCP 36 funkcióját megőrző sandbox-helper, és NEM host privilege-separation. A Draft PR marad DRAFT.

## 5. Két külön folytatási szál

### A – FieldWork termék (elsődleges üzleti cél)

**Javasolt következő milestone: referencia-paritás a stagingben, funkcionális és vizuális teszttel.**
1. Read-only alapos állapot- és regressziófelmérés: júliusi docs vs októberi staging `cfb10c47...` release; a `/opt/fieldwork` piszkos `main` munkafa érintetlen. Sem a státuszból, sem a régies `PROGRESS.md`-ből nem szabad új feature-commitot feltételezni.
2. Kritikus felhasználói útvonalak end-to-end: auth, projekt/alprojekt CRUD, task CRUD, csatolt PDF/fotó feltöltés/megnyitás, feladat és tervnézet, többfelhasználós projektjogok, hibakezelés, mobil/desktop UI; a nem bizonyított funkciókhoz tiszta acceptance fixture kell.
3. A vizuális referencia és a valós staging összevetése modulonként, egyszerre **nagyobb mérföldkőben**: navigation, task-board, Plan workspace, viewer, upload progress, offline pending/sync, jogosultság. Ne csak CSS demonstráció legyen.
4. Módosítások kizárólag külön izolált staging/candidate munkakönyvtárba és egyértelmű, SHA-pinnelt rollback mellett. `/opt/fieldwork` production source, DB és konténerek **tiltott írási célok**.
5. Csak mért regresszió és felhasználói elfogadás után terv a későbbi release-re. A júliusi 34,5% és az októberi „működik” nem helyettesíti a teljes milestone teszteket.

### B – Linux univerzális MCP operátor (külön biztonsági munkaszál)

J5 következő valódi feladata nem újabb teszt-fixture, hanem az új **külön UID-es AF_UNIX Docker-helper** tényleges integrációja az eredeti stage/sandbox API mögé, teljes 36/36 shadow teszttel és helyben jóváhagyott rollbackkel. Az M15-E aktiválásig a távoli MCP Docker-socket kockázatát tudatosan fenn kell tartani; nincs automatikus privilegizált váltás.

## 6. Amit új chatben először kell tenni

1. Ezt a kanonikus checkpointot és a `docs/M15J_REAL_PI_ROOTFUL_DOCKER_MIGRATION_HU.md` tervet olvasd a jelenlegi GitHub branchből.
2. A valódi Pi `fieldwork_status`, `fieldwork_git_status`, `fieldwork_stage_status`, `fieldwork_stage_smoke`, `fieldwork_api_health`, source SHA, Docker inventory **read-only** ellenőrzése. A dátumhoz kötött PID/release/CI adatok nem örök igazságok.
3. **NE** kezdd automatikusan `git reset`, `git clean`, `git checkout`, `git stash`, `docker compose down`, `systemctl restart`, `apt install`, `chmod`, `gpasswd` vagy `sudo` host-művelettel.
4. Ne nevezz egy GitHub dokumentumot az app teljes source code backupjának. Külön FieldWork app GitHub remote vagy valóban ellenőrzött, privát forrásmentés szükséges (titkok, .env, DB, uploadok kizárva).
5. Folytatás **elsőnek a FieldWork termék staging-paritásával**, ha a felhasználó a FieldWork alkalmazást akarja fejleszteni; a generikus MCP helper külön, Draft PR munkaszál.

## 7. Mentés határa

Ez a GitHub commit **checkpoint/terv**, és csak az MCP repository dokumentációját módosítja.
Nem másolja a Pi helyi alkalmazás-kódját, DB-jét, dokumentumait vagy `/opt/fieldwork` változásait a GitHubra; nem emeli át a piszkos munkaállapotot, és nem zárja le az app saját git-ágát. Aki az egész appot akarja biztonságosan GitHubra menteni, előbb külön repo-/remote- és secret-review eljárást igényel.


## 8. FieldWork app – új, izolált naptárfunkció-javaslat (2026-10-31, APP UI)

**A korábbi alkalmazás-paritás munkaszál folytatása.** Nem MCP updater-fejlesztés.

A valódi Pi `/opt/fieldwork` tracked `main` forrásában a `frontend/src/components/CalendarView.tsx` még **csak listás, passzív** naptárt tartalmazott, miközben a felhasználói cél referenciaazonos teljes funkcionalitás. A Pi produkciós forrását nem írtuk át, és a korábban futó, külön staging `cfb10c47c1b3413c9adbd50e5c7249ef` release-t sem cseréltük le.

**Izolált változtatás kész:**
- `proposal_id=7eace13a5e854552b0abe55969b438fe`
- `patch_sha256=f5179b7203ef9a72e8cc20e6e3f6558b3ddf89d24a7dd37a5c8496df70c12823`
- `status=SANDBOX_STATIC_PASS`, `production_modified=false`
- `CalendarView.tsx` új SHA256 `5770d41460d7294b4f9b9443fccbf089052d7f8842beacf9517a254b3b06607d`
- `styles.css` új SHA256 `640c94622ef03c121e08949ef1626ba80ed1a534167755990afdfeb9f8c9ca45`
- `Layout.test.tsx` új SHA256 `40a6b5b030a68a3eec4abd929dbbb01002d3cf18c007529aac812ff1b446d547`

A csomag magyar havi/heti/lista naptár nézetet, hétfői hétkezdést,
naptári hónapváltást, mai napra ugrást, projektcímkézett feladatokat,
érvénytelen naptári dátumok kizárását, 3 elem feletti napi
összesítést és mobil CSS-t ad a **már jogosultság szerint szűrt**
`FieldworkContext` task adataiból. Négy React/Vitest UI-regresszió
került a már meglévő `Layout.test.tsx` állományba.

**Fontos tesztkorlát:** Az MCP `fieldwork_sandbox_apply`
csak forrás-/git-apply/Python AST ellenőrzést végzett. Ekkor a
`JS/TS syntax not checked` és `code_executed=false`.
A `fieldwork_sandbox_command` frontend Node/npm tesztet
**`PHOTO_SUITE_BACKEND_ONLY`** szabály miatt elutasította.
A négy teszt tehát **meg van írva, de NINCS lefuttatva**,
TypeScript/ESLint/Vitest PASS-t és UI-paritást még NEM szabad állítani.
Az első, csak CalendarView fájlt tartalmazó proposal
`833930f5e4ce456d8df189be12b8f538` szintén
SANDBOX_STATIC_PASS, de a 3 fájlos proposal a mérvadó.

**Tilos a jelenlegi staginget felülírni a régi `main` alapján**,
mert az októberi PlanWorkspace/ReferenceTaskBoard/TaskFix
változások nem feltétlenül szerepelnek a tracked `main` forrásban.

**Következő alkalmazáslépés:**
1. A fenti proposal teljes source diffjét és a futó staging release
   aktuális forrásfájljait a külön staging/candidate
   munkakönyvtárban összevetni – driftet/konfliktust jelölni.
2. Biztonságos, elkülönített Node/npm CI vagy sandbox
   `npm run typecheck && npm run lint && npm test`
   kaput bevezetni; lehetőleg külön CalendarView tesztfájl
   saját repo-ágon (az MCP patch policy jelenleg új fájlt tilt).
3. A referencia szerinti komplett feladat/tábla/terv UI
   további munkáját a ténylegesen futó októberi staging
   canonical source-ból folytatni; rollback és
   felhasználói elfogadás nélkül nincs staging cutover.
4. A Pi helyi `main` piszkos munkafáját, a production DB-t
   és az éles konténereket változatlanul hagyni.

**Állapot:** `FIELDWORK_CALENDAR_CANDIDATE_STAGED_STATIC_PASS`;
`FIELDWORK_UI_TESTS_NOT_RUN`; `STAGE_CUTOVER_NOT_AUTHORIZED`;
`PRODUCTION_UNCHANGED`.


### Független, korlátozott TS parser/type próba (kiegészítés)

A `CalendarView.tsx` pontos sandbox SHA256-jával egyező
forrást külön, izolált konténeres munkakönyvtárban ellenőriztük:
`sha256=5770d41460d7294b4f9b9443fccbf089052d7f8842beacf9517a254b3b06607d`.
A helyi **TypeScript 5.8.3** `transpileModule` parser **0 syntax diagnostic**,
és az azonos fájl önálló strict `tsc --noEmit`
fordítása **0 hiba** egy szűk, mesterséges React/FieldworkContext/Task típus-stub
mellett. Ez **NEM** egyenértékű az alkalmazás függőségeivel
végrehajtott teljes TypeScript/Vitest/ESLint/CI ellenőrzéssel;
a tesztfájl Vitest tesztjei továbbra is **NOT_RUN**.
Az eredmény csak a lefordítható TSX magra ad bizonyítékot,
nem a referencia-paritásra vagy a működő stagingre.


## 9. FieldWork app – naptár v2 izolált működési regresszió és M5 lezárási akadály

**Dátum: 2026-10-31, elválasztva a production állapottól.**

### Naptár v2 – elkészült és megőrzött jelölt, nem staging release

- Az előző Pi MCP `7eace13a5e854552b0abe55969b438fe` háromfájlos, csak statikusan ellenőrzött **v1** jelöltet további, független **v2** munkacsomagban fejlesztettük.
- `CalendarView.tsx` v2 SHA256 `9dd99d17472e0d2bf099d14ea00206e844022b2ccb24c3520789889f7df1be02`. Havi (42 cella), heti (7 cella), lista, hétfői hétkezdés, magyar dátumtartomány, érvénytelen/törölt napok kizárása, napi többletfeladatok **megnyitható** részletes listája, időszakváltáskor bezárás, ARIA rácssorok.
- `FieldWork_Calendar_v2_isolated_candidate_20261031.zip` SHA256 `4d333d1a1814256398d134bcaf5448da25aa875eeb2ceeb2212206083565d8f7`: felhasználó **ChatGPT Library `/FieldWork/...` könyvtárában** feltöltve és visszaigazolva. Tartalmazza a TSX forrást, **kiegészítő** CSS-t, test-only React/FieldworkContext stubokat, saját offline logikai tesztet, magyar README-t. **Nem** kell a v2-t egyből telepíteni.
- 2026-10-31 offline, független Node22 + TypeScript 5.8.3 mock környezet: **8/8 dinamikus JSX/hook naptárlogikai teszt PASS**, és külön **strict tsc --noEmit PASS**, de ez helyettesítő React/FieldworkContext típusokra épül. **Valódi alkalmazásfüggőségek, Vitest, ESLint, Playwright, pixelpontos referencia, staging E2E NEM FUTOTTAK**. A Pi MCP `fieldwork_sandbox_command` jelenleg `PHOTO_SUITE_BACKEND_ONLY` hibával tagadja meg a frontend Node/npm hívást. A v2 a Pi korábbi sandboxjába **nem lett érvényesen egyesítve**; a production/staging változatlan.
- **Kritikus funkcionális rés:** a kanonikus 1:1 referencia `R08 calV/assignToDay` **naphoz rendelést, napkijelölést, új és meglévő feladat napra szerkesztését** is elvárja. A mostani naptár v2 csak jobb megjelenítő. A `R08 FULL PARITY` még **BLOCKED**; a teljes referenciáról a felhasználói Library `FIELDWORK_REFERENCE_1TO1_SPEC_HU_M6_BOVITETT.md` dokumentuma rendelkezik.

### M5 fotókomment canary – integritás PASS, funkcióteszt BLOCKED

- A Library meglévő `FieldWork_Paritas_M5_FotoKomment_Canary_20261030.zip` csomagját izoláltan ellenőriztük: SHA256 `9afc910e945d386a51286888842ac5cb70d41b5a48a99d7151ff36e622232d9f`, saját `verify.py`: `M5_PACKAGE_INTEGRITY_PASS 10 files`, Python `compileall`: PASS.
- Korábbi M5 natív frontend kapu: **99/100**, egy `DocumentViewer.test.tsx` FAIL: `Unable to find role="img" and name "Terv one"`; a nézet `Dokumentum betöltése…` állapotban maradt. Pontos gyökérok **nem bizonyított**; lehetséges aszinkron React mock/függőséghiba, de nincs újabb teljes Vitest futás.
- Az M5 package `launch_canary.sh` pontos `parity-m4.d2DIn9Zr` bázist és `fieldwork-parity-m5` külön test projectet követel, külső M5 stage csak teljes frontend + backend kapu után indulhat. Az M5 csomag `integrate.py` külön `parity-m5.*` útvonalat használ; **ne** írja át az `/opt/fieldwork` forrást.
- A Library kanonikus M6 spec alapján az **M6 egyetlen átfogó** teljes feladatszerkesztő és foto-/team-/terv-/naptár-jogosultsági mérföldkő, amit csak M5 teljes PASS után szabad lezárni. Nem szabad a hiányzó R08 vagy M5 miatt újabb félkész GUI-t productionnek nevezni.

### Konkrét folytatás / ellenőrzési korlát

1. Az előző M5 `DocumentViewer.test.tsx` hibát **valódi** izolált frontend Vitest buildgel reprodukálni ugyanazon kandidátuson; aktív test-hiba vs időzítés különválasztása, javítás minimális diffel és 100/100+ full suite bizonyítékkal.
2. A valódi októberi staging release forrását ellenőrizni, mert az MCP `fieldwork_stage_status` **nem** állít bizonyított UI source-hash paritást, a tracked `main` viszont régi.
3. A R08 `assignToDay` teljes mutációs UX-et a közös M6 TaskEditor API és jogosultsági guard mentén integrálni; dátum és korábbi task projekthatár + idempotent mutation tesztje kötelező.
4. A `/opt/fieldwork` produkciós source, DB, Docker változatlan, külön app GitHub repository/forrásmentés továbbra sem igazolt.

**M5 és M6 deployment=BLOCKED; M15-E/operator cutover=BLOCKED; FieldWork production healthy az utolsó valódi read-only lekérdezésnél.**


## 10. FieldWork alkalmazás – M5 R2 fotókomment idempotencia/nyugta javítás (2026-10-31)

**Mérnöki eredmény:** az eredeti M5-ös `PhotoGallery.tsx`
a POST-válasz után vakon `setTotal(previous => previous + 1)` műveletet
használt, annak ellenére, hogy a backend ugyanazzal a
UUID v4 kommentazonosítóval elküldött hálózati újrapróbálkozást
egy korábbi mentés visszaadásával teljesíthette.
Így a frontend és a tartósan tárolt kommentek száma
eltérhetett; a korábbi M5 teszt az azonosság/összesítés
bizonyítására nem volt elég.

**Elkészült az M5 R2 külön, áttekinthető, de nem kiadott javítócsomag:**
- `FieldWork_M5_R2_Idempotency_Receipt_Gate_20261031.zip`.
- SHA256: `567df3d472de743749cd0dfbaa5a49fa52b774ea70fcb2b6da03141231f0240f`.
- A felhasználó Library `/FieldWork/FieldWork_M5_R2_Idempotency_Receipt_Gate_20261031.zip`
  helyén **sikeresen feltöltve**, a feltöltési nyugta visszaigazolta.
- 11 fájl SHA256-ját tartalmazó belső manifest; `verify.py`
  `M5_PACKAGE_INTEGRITY_PASS 11 files` és ZIP CRC ellenőrzés PASS.
- A módosított M5 router `POST /photos/{photo_id}/comments`
  `created: bool` (új vs azonosítóval újraküldött korábbi)
  és szerveroldali SQL COUNT alapján `total: int` nyugtát ad,
  **idempotens retryra nem számol új kommentet**.
- A módosított `PhotoGallery.tsx` csak az aktuális
  `pending.current.id`-hez tartozó, formailag érvényes
  választ fogadja el; `total` megjelenítése a DB-beli
  darabszámot követi, nem `previous + 1`.
  A korábbi kliensbizonytalanságoknál továbbra is ugyanazt
  az idempotens requestet küldheti újra.
- Módosított `test_photo_comments_m5.py` és
  `PhotoGalleryM5.test.tsx`, valamint új, független
  `isolated_backend_contract_smoke.py` tesztparancs.

**Tényleges ellenőrzések:**
- Valódi FastAPI `TestClient`, SQLAlchemy és csak memóriabeli
  SQLite, az **új valódi M5 routerkódot** minimális helyettesítő
  modellekkel és szűkített, mock auth/permission függvényekkel
  végigtesztelve: `15/15 PASS` (első mentés/COUNT,
  idempotens második POST/COUNT, eltérő body konfliktus,
  második komment, listás összesítés, viewer deny,
  anonymous/cross-project deny, üres/hibás UUID és törölt fotó).
- Python AST fordítás: PASS, a bundle 11 fájlos SHA
  manifest-ellenőrzése: PASS.
- Valódi TypeScript 5.8.3 `transpileModule` parser:
  `PhotoGallery.tsx` és `PhotoGalleryM5.test.tsx`: 0 szintaxishiba.
- **NINCS** teljes alkalmazás-szintű Python/migrációs regresszió,
  npm `tsc` a FieldWork függőségeivel, Vitest,
  Playwright vagy Pi M5 stage E2E: ezek **BLOCKED**,
  nem PASS. A jelenlegi munkakörnyezetből
  `npm view` hálózati hiba `EAI_AGAIN`,
  nincs rendelkezésre álló telepített FieldWork
  frontend node_modules; a Pi MCP jelenlegi
  frontend parancsfuttatása `PHOTO_SUITE_BACKEND_ONLY`.

**Kritikus fennmaradó hibák / szabályok:**
- A korábbi `DocumentViewer.test.tsx` 99/100 frontend kapuhiba
  továbbra is **nyitott, root cause NOT_VERIFIED**.
  A M5 R2 ezt **nem** állítja javítottnak.
- Az R08 naptár meglévő/új feladat naphoz rendelése
  továbbra is hiányzik; M6 referencia-paritás nem teljes.
- A `launch_canary.sh` továbbra is csak a korábbi
  pontos M4 alapforrást, teljes tesztkaput és
  külön `fieldwork-parity-m5` stage projektet enged.
  Az új csomag kizárólag izolált candidate, **nem futott a Pi-n**.
- `/opt/fieldwork`, éles DB, Docker production és staging
  konténerek, tunnel és MCP felhasználók **nem módosultak
  az M5 R2 csomag készítése során**.
- A külön, privát teljes app GitHub repository/forrásbackup
  még nem igazolt; ez a dokumentum csak MCP-repós checkpoint.

**Állapot:** `M5R2_LOCAL_FASTAPI_SQLITE_15_PASS`;
`M5R2_BUNDLE_SHA_MANIFEST_PASS`;
`M5_FULL_FRONTEND_BACKEND_GATE_NOT_RUN`;
`DOCUMENT_VIEWER_FAIL_PENDING`;
`M5_STAGING_CUTOVER_BLOCKED`;
`M6_PARITY_BLOCKED`.


## 11. FieldWork app – M5 R3 DocumentViewer tesztstabilizálás és kiadási blokkolók (2026-10-31)

**Elkészült: `FieldWork_M5_R3_DocumentViewer_Test_Gate_20261031.zip`**
a privát ChatGPT Library **`/FieldWork/`** könyvtárában
(a feltöltést visszaigazolta az aktuális Library nyugta).
A megosztható ZIP SHA256:
`6adfa4328ff05bc0be34d7ae347abd632fb94c03b77adb15c45f1eccf2fb375f`.

**Mi változott az M5 R2-höz képest?**

1. A valódi `DocumentViewer.test.tsx` meglévő, hibára futó tesztje a **teljes globális `URL` konstruktor helyébe objektumot** állított. Az új izolált tesztváltozat megőrzi a konstruktor működését (alapvető jsdom kompatibilitás), csak a `createObjectURL` / `revokeObjectURL` statikus mockokat cseréli és minden teszt után helyreállítja a globális cserét.
2. A fájlbetöltést külön `waitFor` igazolja, és a kép megjelenése explicit 5 s várakozást kap, így megkülönböztethető a fetch-meghívás hiánya és a React/jsdom renderelési késés. **Ha a kép ténylegesen hiányzik, továbbra is FAIL lesz**, ez nem félrevezető zöldítés.
3. Az M5 R3 `integrate.py` a külön `stage-v06/parity-m5.*` jelöltbe bármilyen írás előtt ellenőrzi a régi teszt SHA256-ját; az opcionális tesztjavító kizárólag ebben a jelöltben, pontos bájtokból dolgozik. `launch_canary.sh` már a jelölt létrehozása előtt SHA+negatív contract preflightot futtat. Production forrás-/Docker-/DB-módosítás **NEM** történt.
4. A csomag tartalmazza a teljes M5 R2 idempotencia számláló-/nyugta-javítást, a rögzített M5 migrációs kódot és a régi teszteket. Nem támaszkodik új, távoli kódfeltöltésre a Pi-n.

**Valós bizonyítékok:**
- Pi MCP `fieldwork_stage_patch` proposal
  `d0e4d925e4f440edb2ee58644432ea5b`, patch
  `b8f63033e3506df41630a4d4301f6ef83467cd56dd0a455b6fa6ca5647daa3e7`
  **SANDBOX_STATIC_PASS**, produkció változatlan.
- Kiinduló tényleges teszt SHA256:
  `5e802a79179f9a171ed06160258bab0f31400045f7b615a85fcea37c04d6abef`.
  Az izolált sandboxból függetlenül visszaolvasott új SHA256:
  `9a111123e5cb23e74bbe82a2a9d6c033e55e15643d7607222730cb56b4d4ec08`.
- Csomag 13-fájlos manifest és integritási ellenőrzés:
  `M5_PACKAGE_INTEGRITY_PASS 13 files`.
- A Python negatív patch- és forrásvédelmi szerződéspróbák:
  **4/4 PASS**; `bash -n launch_canary.sh` PASS; Python AST:
  PASS.
- A tényleges M5 R2 `photo_comments_api.py` FastAPI
  TestClient + SQLAlchemy / in-memory SQLite próba
  **15/15 PASS** újrafuttatva.
- A frontend valódi `npm ci + typecheck + lint + full Vitest` **NEM
  FUTHATOTT LE** ebben a futtatási környezetben:
  a helyi npm registry DNS `EAI_AGAIN`; a Pi MCP
  `fieldwork_sandbox_command` általános frontend tesztet
  `PHOTO_SUITE_BACKEND_ONLY` szabállyal blokkolja.
  Nem állítható, hogy a régi 99/100 FAIL okát sikerült
  bizonyítani vagy a teljes M5 frontend kaput átvinni.

**Következő kapu (kötelező):** az új M5 R3-at a pinelt
M4-snapshotból létrehozott külön `parity-m5.*` jelöltben
kell `npm ci`, TypeScript, ESLint, **összes Vitest**,
backend/migrációs E2E, `fieldwork-parity-m5`
18085 canary egészség és UI-átvétel mellett igazolni.
A telepítőt a jelen körben **nem futtattuk a Pi-n**:
nem áll rendelkezésre olyan korlátozott MCP tool,
amely ennek teljes frontend-telepítési workflow-ját
jóváhagyás és host Docker-kockázat nélkül tudná végrehajtani.

**Kritikus:** a korábbi M5 99/100 `DocumentViewer` FAIL
továbbra is **NOT_VERIFIED**, M5 deploy **BLOCKED**.
Az M6 közös TaskEditor és R08 naphoz rendelés
a teljes M5 PASS-ig szintén **BLOCKED**.
A Pi production API/staging MCP read-only lekérdezhető;
az aktuális `main` piszkos munkafáját nem írtuk át.


## 12. FieldWork app – M5 R4 teljes előellenőrzésű, rollbackelt izolált integrátor (2026-10-31)

**A folytatás első valóban bizonyított hibája a korábbi M5 R3 integrátorban:**
az `integrate.py` a `frontend/src/components/PhotoGallery.tsx` fájlt **már az
összes másik forrásfájl SHA-, anchor-, célútvonal- és DocumentViewer-teszt
ellenőrzése előtt felülírta**. Későbbi hibánál félkész M5 jelölt
maradhatott hátra. Ez a teljes canary kiadási folyamatot kockáztatta.

**Elkészült új R4 csomag, a korábbi R3/R2 változatok teljes tartalmával:**
- `FieldWork_M5_R4_Atomic_Candidate_Gate_20261031.zip`;
- SHA256 `45bda8f4b2714bbc1f8884e05ad21ac9fa2a0fb6f11885c907e7821cc764261b`;
- ChatGPT Library: `/FieldWork/FieldWork_M5_R4_Atomic_Candidate_Gate_20261031.zip`,
  a feltöltés nyugtája sikeres. **Nem került semmilyen app-forrás
  a nyilvános MCP GitHub repositoryba.**
- ZIP: 15 fájlos belső SHA256 manifest + verify.py; `M5_PACKAGE_INTEGRITY_PASS 15 files`.

**M5 R4 javítás:**
1. Új `m5r4_transaction.py` `CandidatePlan`: az összes meglévő és új
   célfájlt, az összes módosító anchort, kiinduló SHA256-ot,
   symlink/path/relatív útvonalat **memóriában előre ellenőrzi**.
   A két egymást követő módosítás ugyanazon fájlon
   láncolható, az eredeti fájlbyte-ok pedig változatlan
   összehasonlítási alapot képeznek.
2. A teljes `integrate.py` átírva erre a teljes terv-alapú
   modellre; **egyetlen app célfájl sem íródik a legutolsó
   DocumentViewer SHA/patch ellenőrzés befejezéséig**.
3. `CandidatePlan.commit`: újraellenőrzi az összes eredeti
   forrásbyte-ot, elhelyez `.m5r4-blocked` markert, majd
   ideiglenes, fsyncelt és `os.replace`-szel cserélt
   célfájlokat ír. Köztes hiba esetén az érintett
   fájlokon best-effort rollback fut; sikertelen rollback
   `ROLLBACK_INCOMPLETE` és **blokkoló marker marad**.
   Teljes siker után `.m5r4-ready.json` pontos
   forrás SHA256 nyugta keletkezik, a blokkoló marker eltűnik.
4. `launch_canary.sh` közvetlenül az integrátor után,
   **a Docker- és npm-futtatás előtt** újraellenőrzi
   az összes nyugtázott fájl hashét és a blocker hiányát;
   drift/bizonytalanság esetén STOP. Az eddigi
   front/back teljes tesztkapu feltételei megmaradtak.
5. Új `test_m5r4_atomic_integrator.py`: érvénytelen
   késői anchor, forrás SHA drift, több egymást követő
   változtatás ugyanarra a fájlra, szimulatív írási hiba,
   rollback hiba, production/symlink/path escape és
   receipt byte tamper negatív próbák.

**Tényleges izolált ellenőrzés a munkakonténerben:**
- `test_m5r4_atomic_integrator.py` **6/6 PASS**.
- A korábbi `test_documentviewer_patch_gate.py` **4/4 PASS**.
- A tényleges M5 fotókomment-routerrel, FastAPI TestClient
  és SQLAlchemy SQLite tesztmodellel futó
  `isolated_backend_contract_smoke.py` **15/15 PASS**.
- `bash -n launch_canary.sh` PASS;
  `python -m compileall` / `py_compile`: PASS.
- npm registry DNS: `EAI_AGAIN registry.npmjs.org`;
  **teljes FieldWork npm ci, TypeScript, ESLint, Vitest
  és valós PostgreSQL/Playwright még NEM futott**.
  A ZIP-es M4 csomag csak az M4 canary változásfájljait
  tartalmazza, nem a teljes FieldWork alkalmazás-forrásfát;
  ezért az R4 teljes M4→M5 integrációt az eredeti Pi
  M4-kandidátuson **NEM teszteltük**.
- A kiegészítés célja nem általános OS processz/UID/IPC
  privilege isolation; hirtelen crash/host shutdown
  esetén a fs tranzakció nem garantált, ezért a
  blocker + receipt ellenőrzés a kiadás feltétele.

**Go/no-go:** `M5R4_BUNDLE_VERIFIED`;
`M5R4_TRANSACTION_UNIT_6_PASS`;
`M5R3_NEGATIVE_4_PASS`;
`M5_R2_FASTAPI_SQLITE_15_PASS`;
`FULL_M4_TO_M5_INTEGRATION_NOT_RUN`;
`DOCUMENT_VIEWER_REAL_VITEST_FAIL_NOT_RECHECKED`;
`M5_DEPLOY_BLOCKED`;
`M6_PARITY_BLOCKED`.
A production `/opt/fieldwork`, DB, Docker és futó staging
nem került módosításra.


## 13. FieldWork app – M5 R5 kötelező teszteset-begyűjtési kapu (2026-10-31)

**Tényleges új hiba az M5 R4 `launch_canary.sh`-ban:** a backend
eredményét részben a teljes pytest `N passed` számával döntötte el.
Ha a tesztgyűjtésből az új `tests/test_photo_comments_m5.py` kiesett,
egy korábbi nagy, sikeres tesztcsomag (>90 teszt) továbbengedhette a
M5 canary kiadást **úgy, hogy semelyik M5 fotókomment teszt nem futott**.
Ez nem elfogadható, mert a M5 backend/permission regresszió
átugorható volt.

**Elkészült, izolált M5 R5 ZIP:**
- `FieldWork_M5_R5_Exact_Test_Collection_Gate_20261031.zip`;
- SHA256 `dc686147f61be0213d4b805216db7e998c77acb9a1ec0c017ba71b6ce23d02f9`;
- ChatGPT Library: `/FieldWork/FieldWork_M5_R5_Exact_Test_Collection_Gate_20261031.zip`,
  feltöltés ellenőrzött; **nem a nyilvános MCP repo alkalmazásforrása**;
- az összes korábbi M5 R4/R3/R2 fájllal és 17 fájlos,
  SHA256 alapú manifesttel: `M5_PACKAGE_INTEGRITY_PASS 17 files`.

**Új tesztkapu:**
- `m5r5_test_gate.py` standard-library-only, bounded,
  fail-closed, explicit logellenőrző, önmagában nem
  futtat alkalmazáskódot.
- A backend indító most `pytest -v tests` kimenetet készít,
  amelyből **név szerint mind az öt** új
  `test_photo_comments_m5.py` teszt `PASSED`
  eredménye kötelező; ha bármelyik hiányzik, ismételt,
  `SKIPPED`, `FAILED`, `ERROR`, `XPASS`, `XFAIL`,
  vagy a teljes teszteset-begyűjtés száma nem egyezik az
  egyetlen pytest összesítéssel: **STOP**. Nem lehet
  össztesztszám alapján kiváltani M5 specifikus bizonyítékot.
- Frontend `m5-frontend-test.log`: egyértelmű
  `Test Files N passed (N)` ÉS `Tests N passed (N)`,
  illetve a **`DocumentViewer.test.tsx` és
  `PhotoGalleryM5.test.tsx`** modulok explicit
  megjelenése kötelező. Hiány/failure/második összesítés
  STOP. Ez valódi Vitest logot igényel az M5 canary
  build során, nem a mostani szintetikus tesztlogot.
- A korábbi forrás SHA-, tranzakciós/rollback-,
  canary-isolation- és M15-E biztonsági tilalmak
  változatlanok. A minta `launch_canary.sh` **nem futott a Pi-n**.

**Valóban futtatott izolált tesztek:**
- `python -m unittest -q test_m5r5_test_gate.py
  test_m5r4_atomic_integrator.py test_documentviewer_patch_gate.py`
  **26/26 PASS**. Tartalmazza a régi 100+ tesztes,
  de M5 modul nélküli hamis PASS elutasítását.
- `isolated_backend_contract_smoke.py` **15/15 PASS**
  valódi FastAPI TestClient és SQLAlchemy in-memory
  SQLite, de **minimális modelljogosultság-helyettesítőkkel**.
- `verify.py`: 17-fájlos ZIP manifest PASS;
  `bash -n launch_canary.sh` PASS;
  Python AST/compile PASS.
- A lokális gépen npm registry nem elérhető;
  a Pi MCP nem engedi általános frontend npm futtatását,
  az M4 teljes app-forrás hiányzik a jelen munkakörnyezetről.
  **Valódi teljes frontend Vitest, valódi M4+M5 PostgreSQL
  pytest/migrációs kapu, port 18085 canary NEM FUTOTT.**
- Az új M5 backend helyspecifikus tesztnapló feldolgozása
  valós M4 CI tesztkimenet alapján még nem validált;
  ha egy jelölt más pytest formátumot használ, fail-closed STOP.

**Következő tényleges blokk:** a teljes,
fájlonként pinelt `stage-v06/parity-m4.d2DIn9Zr`
**létezésének és forrásintegritásának független
read-only bizonyítása**, majd a külön `parity-m5.*`
R5 jelölt és az alkalmazás-függőségekkel végzett
TypeScript/ESLint/összes Vitest + backend/migráció/HTTP
canary kiadási kapu. Az éles `/opt/fieldwork`,
production DB, Docker és a működő staging írás nélkül maradt.

**Állapot:** `M5R5_EXACT_FIVE_TESTS_GATE_READY`;
`M5R5_NEGATIVE_26_PASS`;
`M5R5_FASTAPI_SQLITE_15_PASS`;
`M5_FULL_REPO_PARITY_NOT_RUN`;
`DOCUMENTVIEWER_ROOT_CAUSE_NOT_PROVEN`;
`M5_DEPLOY_BLOCKED`;
`M6_PARITY_BLOCKED`.


## 14. FieldWork app – M5 R6: kommentbeküldési versenyhelyzet + valódi tesztmodul-nyugta javítás (2026-10-31)

**Új valódi kliensprobléma, izolált forráselemzéssel az M5 R5-ben:**
- A `PhotoGallery.tsx` POST folyamat alatt nem tiltotta a megjegyzés inputot. Új gépelés a `pending.current` UUID-t törölhette, amikor a szerver már elfogadta az eredeti kommentet; későbbi válasz „nem igazolt” hiba, majd új UUID-val retry esetén duplikált hozzászólás keletkezhetett. R6-ban a POST indításakor **immutábilis {id,text} snapshot**, input `disabled={submitting}` és az eredeti id/fotó/szöveg, `total`, `created` szigorú server receipt összevetése szerepel.
- A `PhotoGalleryM5.test.tsx` ugyanúgy egyszerű objektummal helyettesítette a teljes `URL` konstruktort, mint a korábban hibás DocumentViewer teszt; R6-ban a URL konstruktor osztály marad, csak a Blob URL statikus API mockolt, `vi.unstubAllGlobals()` helyreállítással.
- Az M5 R5 frontend logellenőrző **csupán szövegként keresett fájlneveket**: egy figyelmeztetésben szereplő `DocumentViewer.test.tsx` vagy `PhotoGalleryM5.test.tsx` hamis bizonyítékká válhatott. R6-ban csak a tényleges, pozitív Vitest `✓ src/components/...test.tsx (N tests)` sorok fogadhatók el, a sorok száma és az egyes fájlok tesztösszege a teljes pass-summaryval is egyezik. Duplikált, hiányzó vagy eltérő számú sor **STOP**. Ez a rögzített Vitest default reporterhez kötött; eltérő formátum fail-closed, nem automatikus átengedés.

**Elkészült teljes, előző M5 R5-re épülő izolált csomag:**
- `FieldWork_M5_R6_Comment_Submission_And_Vitest_Gate_20261031.zip`
- SHA256: `9c9a53a82413c8bc56a79c370b5bae89d78f9c96a66c0b4ab4341766a5bb0392`
- ZIP CRC PASS, **18 fájl** SHA256-manifest `M5_PACKAGE_INTEGRITY_PASS 18 files` (a ZIP-ben 19 bejegyzés van manifesttel együtt).
- Sikeres Library feltöltés: `/FieldWork/FieldWork_M5_R6_Comment_Submission_And_Vitest_Gate_20261031.zip`, nem került application source a publikus MCP GitHub repóba.
- Célzott Python szerződéspróbák: **31/31 PASS**, beleértve a 26 meglévő R5/R4/R3 és 5 új R6 log/source-regressziós tesztet.
- A tényleges M5 `photo_comments_api.py` routerrel izolált FastAPI TestClient+SQLAlchemy SQLite próba: **15/15 PASS**, minimális modellhelyettesítőkkel.
- TypeScript **5.8.3** `transpileModule`: `PhotoGallery.tsx`, `PhotoGalleryM5.test.tsx`: **0 parser diagnostic**; Bash `launch_canary.sh` és Python AST/compile PASS.
- A kapu-parser valódi, ténylegesen futtatott pytest `-v` formátumon ellenőrizve: 5 M5 nevű egyszerű teszt + 17 kontrollteszt **22/22 PASS** esetben pozitív receipt, 1 `SKIPPED` teszt esetén **BLOCK**. Figyelem: ez nem a FieldWork teljes DB-/jogosultsági tesztrendszere, hanem *reprodukálható szintetikus tesztfunkciókkal futtatott valódi pytest*, kizárólag a log-parser kompatibilitásának bizonyítására.

**Éles Pi read-only tények az M5 R6 után:**
- `fieldwork_mcp_docker_inventory`: 26 konténer; `fieldwork-parity-m4-*` és `fieldwork-parity-m5-*` **exited**, `fieldwork-stage-{nginx,api,db}` és `fieldwork-{nginx,api,db}` **running**.
- `fieldwork_stage_smoke`: `STAGE_HEALTH_PASS`, MCP `v0.6.1`; `/opt/fieldwork` Git-munkafája változatlanul dirty.
- A korábbi pontos M4 `stage-v06/parity-m4.d2DIn9Zr` könyvtár **fájlonkénti integritását a jelen MCP toolokkal nem tudtuk host oldalon ellenőrizni**: a docker inventory önmagában nem bizonyítja a forrásfájlok jelenlétét.
- A Pi MCP `fieldwork_sandbox_command` továbbra is korlátozott (`PHOTO_SUITE_BACKEND_ONLY`); az artifact inbox a ZIP-et biztonságosan átvehetné, de **nem ad engedélyt host parancsra/Compose buildre**.
- A **teljes FieldWork frontend Vitest, valódi M4→M5 integráció, PostgreSQL migráció, 18085 canary E2E nem futott**. Tilos R6-ot kész produkciós release-nek nevezni vagy a Pi production Docker/DB-t módosítani.

**Állapot:** `M5R6_BUNDLE_SHA_PASS`; `M5R6_31_UNIT_PASS`; `M5R6_FASTAPI_SQLITE_15_PASS`; `M5R6_REAL_PYTEST_FIXTURE_PASS_SKIP_BLOCKED`; `M5_FULL_APP_CI_NOT_RUN`; `M5_CANARY_NOT_DEPLOYED`; `PRODUCTION_UNCHANGED`.

**Valódi következő milestone:** ne növeljük tovább csak tesztkapu-javítások miatt a verziószámot. Külön jóváhagyott, jogosultságában szűkített **Pi frontend M5 teszt-végrehajtó** kell (`npm ci/typecheck/lint/vitest` fix, rögzített M4 snapshotban, biztonságosan korlátozott Docker helperen), vagy a teljes FieldWork app **privát GitHub repo** CI-je. Jelen 36 MCP tool egyikével sem igazolható a teljes frontend anélkül, hogy a meglévő host/Docker privilege boundaryt megkerülnénk.


## 15. M5 R6 CI-kompatibilitási JAVÍTÁS – teljes frontend tesztfájlleltár (2026-10-31)

**Bizonyított új gyökérok a korábbi `M5_R6_Comment_Submission_And_Vitest_Gate` csomagban:** a
`m5r5_test_gate.py` `FRONT_PASS_FILE` reguláris kifejezése csak
`src/components/*.test.tsx` tesztfájlokat fogadott el. A Pi tényleges
`frontend/vite.config.ts` beállítása azonban
`include: ['src/**/*.test.{ts,tsx}']`, és a Pi read-only forrásleltára
**ténylegesen tartalmaz** `src/api/client.test.ts`,
`src/auth/AuthContext.test.tsx`,
`src/data/FieldworkContext.integration.test.tsx`
és más könyvtárak alatti teszteket is.

Az eredeti R6 parser a 6 tesztfájlból álló, 34
sikeres tesztet tartalmazó, FieldWork-könyvtárszerkezetet
modellező naplót **tévesen elutasította**:
`STOP M5R6_EXACT_VITEST_SUCCESS_ROWS_REQUIRED`.
Ugyanezt a naplót a javított parser elfogadta:
`M5R5_FRONTEND_VERIFIED`, `test_files_passed=6`,
`tests_passed=34`, `cutover_authorized=False`.

**A javítás nem új M5-funkcióváltozat:** az R6 korrekciója.
A teljes ZIP külön, változatlan fájlnévvel és SHA256 pinekkel
átadásra került:
- `FieldWork_M5_R6_CI_Compatibility_Fix_20261031.zip`
- **SHA256 `36486e9965057bfa9811014e63dbb370c28707d7f5c5ef3da2da89a44c2f025c`**
- `/FieldWork/FieldWork_M5_R6_CI_Compatibility_Fix_20261031.zip`
  – privát ChatGPT Library feltöltés sikeres és nyugtázott.
- 18 alkalmazásváltozás- és ellenőrző fájl pontos SHA256
  manifesttel, ZIP CRC ellenőrzéssel.
- A parser immár `src/**/<filename>.test.ts` és
  `src/**/<filename>.test.tsx` tesztfájlokat ismer fel,
  teljes relatív útvonallal, és megköveteli a 2 konkrét
  M5 test file pozitív eredményét, a teljes file/test
  darabszámot és a két egyértelmű összesítést.
  Figyelmeztetésben szereplő név, duplikált név,
  hiányzó darabszám, `..` útvonalszegmens
  vagy kétes log továbbra is **STOP**.

**Tényleges teszteredmények a javított ZIP forrásával:**
- `python verify.py .` ⇒ `M5_PACKAGE_INTEGRITY_PASS 18 files`.
- `unittest` ⇒ **34/34 PASS** (korábbi 31 + 3 valós
  teljes tesztútvonal kompatibilitási negatív/pozitív teszt).
- `isolated_backend_contract_smoke.py` ⇒ **15/15 PASS**
  (FastAPI + SQLAlchemy in-memory SQLite helyettesítő modellel).
- `PhotoGallery.tsx` és `PhotoGalleryM5.test.tsx`
  TypeScript 5.8.3 parser ⇒ 0 hiba.
- `bash -n launch_canary.sh` ⇒ PASS.
- A **valódi** FieldWork összes Vitest-, ESLint-,
  TypeScript-, PostgreSQL-, migrációs- és 18085 canary
  tesztje **TOVÁBBRA SINCS LEFUTTATVA**.
  A 34/34 kifejezetten Python szerződésellenőrzés,
  nem teljes frontendteszt.

**Forrás-/futtatóhozzáférés igazolt korlát:**
- GitHub kapcsolaton a `misssska` tulajdonban **nincs**
  önálló FieldWork alkalmazás-repository.
- A Library teljes M4 ZIP helyett csak M4 változáscsomagot
  tartalmaz; npm/Vitest függőségek sincsenek telepítve ebben
  a konténerben.
- Pi MCP: a teljes alkalmazás `fieldwork_tree` leltározható,
  de nincs engedélyezett, tetszőleges frontend npm teszt
  runner vagy az M4 `stage-v06/parity-m4.d2DIn9Zr`
  teljes forrásfájljait hitelesen átadó/ellenőrző eszköz.
  A korábbi Docker-konténerek `exited` állapotban vannak.
- **Ne** próbáljuk meg a Pi korlátozó MCP szabályát
  megkerülni; olyan helyileg jóváhagyott, privát
  CI-végrehajtó vagy külön privát GitHub repository kell,
  amely a teljes eredeti M4 forrást és npm lockfile-t
  biztonságosan eléri.

**Kanonikus kiadási állapot:** a régebbi R6 ZIP
`9c9a53a8...` **tesztkapuja elavult**, használandó
helyette a fent SHA-pinnelt `R6_CI_Compatibility_Fix`;
`M5_FULL_APP_CI_NOT_RUN`; `M5_CANARY_NOT_DEPLOYED`;
`M6_PARITY_BLOCKED`; `PRODUCTION_UNCHANGED`.
