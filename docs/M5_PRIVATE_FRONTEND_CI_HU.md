# FieldWork M5 – privát frontend CI-kapu, pontos forrás- és tesztleltár

**Állapot: elkészült, a publikus repo ARM64/x86-64 szerződéstesztjei bizonyítják a felvételi szabályokat. A teljes FieldWork M5 alkalmazás frontendje MÉG NEM FUTOTT ezzel a kapuval.**

## Cél és architektúra

A teljes FieldWork alkalmazás privát forrását **NEM** töltjük fel a nyilvános `misssska/fieldwork-pi-mcp` repositoryba, és nem adunk új távoli rootful Docker-/SSH-jogot a Raspberry Pi-n.

A nyilvános MCP-repo kizárólag az általános, **összetett (composite) GitHub Actiont** tartalmazza:

- `.github/actions/m5-private-frontend-gate/action.yml`
- `updater/m5_private_frontend_gate.py`
- `updater/m5_native_vitest_receipt_contract.py`
- `tests/test_m5_private_frontend_gate.py`

A privát FieldWork-repository a saját, **GitHub-hosted ideiglenes futtatóján** hívhatja az ellenőrzőt pontos commit SHA-val. A teljes alkalmazásforrás a privát checkoutban marad. A GitHub Action nem publikál release-t, nem használ Dockert, nincs Pi/csoport/jogosultság-módosítása és nem fér hozzá production DB-hez.

### Kiadási kapu

1. **Előfeltétel:** `github.event.repository.private == true`, `RUNNER_ENVIRONMENT=github-hosted`, `GITHUB_ACTIONS=true`. Nyilvános repo és self-hosted runner → STOP.
2. **Pontosan pinelt Git HEAD:** 40 karakteres SHA, tiszta munkafa, kötelező M5 tracked tesztforrások. A valós FieldWorkben meglévő `dev` és `test:e2e` npm parancsokat engedi, de a négy végrehajtott parancs definícióját pontosan ellenőrzi.
3. **Zárt forrásleltár:** tracked fájllista és SHA256 a `frontend/src/**/*.test.{ts,tsx}` tesztfájlokról, valamint `package.json`, `package-lock.json`, `vite.config.ts`, `PhotoGallery.tsx`, `DocumentViewer.test.tsx`, `PhotoGalleryM5.test.tsx`.
4. **Egyetlen fix végrehajtási sor:** `npm ci --ignore-scripts --no-audit --no-fund`, `npm run typecheck`, `npm run lint`, `npm test -- --reporter=default`, `npm run build`. Node 22. Minden hiba STOP. A csomagtelepítési lifecycle script tilalma miatt a valódi függőségek kompatibilitását külön bizonyítani kell, nem szabad a védelmet automatikusan kikapcsolni.
5. **Utóellenőrzés:** változatlan commit és SHA256 források, valódi Vitest 3.2.7 pozitív fájlsorok + pontos fájl-/tesztszám-összesítés. A Gitben nyilvántartott **összes** `frontend/src/**/*.test.{ts,tsx}` fájlnak szerepelnie kell. A `DocumentViewer` és `PhotoGalleryM5` modul sikeres futása külön kötelező. Kimaradt modul, hamis/nem teljes receipt, forrásdrift → STOP.
6. **Kimenet:** `M5_FULL_PRIVATE_FRONTEND_CI_PASS` csak a teljes frontendteszt-kaput igazolná; `backend_pg_migrations_tested=false`, `release_authorized=false`, `production_access=false`. A backend/jogosultság/migráció/18085 canary külön feltétel.

### Példa a KÉSŐBB létrehozandó privát FieldWork-repository workflow-jára

Az alábbi YAML **nem telepíthető most a Pi-re**. A példát kizárólag a saját privát FieldWork alkalmazás-repo `.github/workflows/m5-full-frontend.yml` fájljába szabad tenni, miután a forrás auditált és verziókezelt.

```yaml
name: FieldWork M5 full frontend (private only)
on: [push, pull_request]
permissions:
  contents: read

jobs:
  full-frontend:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-24.04, ubuntu-24.04-arm]
    runs-on: ${{ matrix.os }}
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: misssska/fieldwork-pi-mcp/.github/actions/m5-private-frontend-gate@10aab1c567d228418fbddceaffd21a998f84fbcd
        with:
          expected-commit: ${{ github.sha }}
```

**Fontos:** a példa pontosan pinelt MCP-kódot használ. A privát repo létrehozása előtt a Pi `/opt/fieldwork` helyi módosításait külön át kell tekinteni; semmilyen `.env`, titok, production DB, képfeltöltés, felhasználói adat vagy jogosultsági kulcs nem kerülhet GitHubra. A külön FieldWork app privát GitHub-repository jelenleg NINCS ellenőrzötten elérhető, ezért e workflow **még nem volt valódi alkalmazásforráson tesztelve**.

## Független ellenőrzési bizonyíték

- [M5 privát forráskapu – ARM64/x86-64 GitHub Actions](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41247060146): két architektúra **PASS**, mindkettőn 12/12 valódi ideiglenes Git-snapshot szerződésteszt és nyilvános repositoryból a composite action elutasítása. 
- A Pi valódi `frontend/package.json` forrásával végzett összevetés felfedte, hogy a `dev` és `test:e2e` extra parancsok miatt az eredeti egyenlőség téves STOP-ot okozott volna. Javítva: a négy kötelező script pontos definíciója szükséges, a többi script nem blokkol.
- [Korábbi valódi Vitest 3.2.7 riportteszt](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41246505731): ARM64 és x86-64 **PASS**, 34/34 szintetikus teszt 6 fájlban, pozitív/negatív riport-kapu PASS. Ez nem a FieldWork alkalmazás tesztje.
- A privát CI belépési pont maga nem indított teljes alkalmazásfuttatást és nem szerzett új Pi-host jogosultságot.

## Következő tényleges feladat

1. A Pi helyi, módosított FieldWork munkafájának biztonságos és auditált, **privát** Git-forrástörténete; titok/DB/uploadok kizárása, nincs reset/stash, és csak a megfelelő jóváhagyott másolási útvonalon.
2. A pontos M4 snapshot és M5 R6 kompatibilitási jelölt egyedi hash-pinnelése az új privát repo branchben.
3. A **teljes frontend CI-kapu** tényleges 2/2 PASS bizonyítása a valódi alkalmazáson, majd külön PostgreSQL backend+migrációs E2E és `fieldwork-parity-m5` izolált canary.
4. Production `/opt/fieldwork` source, DB, futó stage, tunnel, Docker-csoport **tilos módosítani** automatikusan.

**Kiadási státusz: M5_FULL_APP_CI_NOT_RUN; M5_CANARY_NOT_DEPLOYED; M6_PARITY_BLOCKED; PRIVATE_SOURCE_REPO_NOT_CONNECTED; M5_PRIVATE_CI_GATE_CONTRACT_READY.**
