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
