# M9 – Valódi ARM64 konténeres próbafuttatás (2026-10-31)

## Eredmény: PASS, kizárólag szintetikus tesztforrásra

- Workflow: [ARM64 canary appliance real Docker smoke](../.github/workflows/appliance-arm64-smoke.yml)
- GitHub Actions: https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41202296664
- Vizsgált commit: `ea0e9f0ee09d0e751e4ea65922f2afb2d428a057`
- Futási környezet: `ubuntu-24.04-arm`, valódi `aarch64` gép.
- Docker BuildKit: valós image build, helyben megfigyelt registry digestekkel.
- Image: helyi `sha256:` azonosító, architektúra, dependency- és test-entrypoint-hash
  ellenőrizve az `updater/canary_appliance_image.py` modulon keresztül.
- Öt, az éles runner által szerkesztett pontos Docker-paranccsal indított
  konténeres teszt: **5/5 siker**.
- A backend fázisban tényleges PostgreSQL 18 futott a konténer ideiglenes
  tárhelyén, és a Python teszt `psycopg` kapcsolaton keresztül sikeres
  `SELECT current_database(), 1` ellenőrzést végzett.
- A frontend fázisok külön végrehajtottak és sikeresek; a szintetikus
  `package.json` feladatait futtatták, nem a FieldWork valódi
  TypeScript/ESLint/Vitest/buildufolyamatait.

## Mit bizonyít és mit NEM?

**Bizonyított:**
1. Az építési recept valódi ARM64-en összeáll, és az ellenőrzött
   Python/Node/PostgreSQL függőségek települnek.
2. A rögzített, hálózat nélküli, nem-root tesztindító konténerfázisok
   valóságosan lefutnak.
3. A PostgreSQL a konténerben elindul, a külön tesztadatbázis
   létrejön és elérhető.
4. A helyi image-ellenőrzés elutasítás nélkül validálja az image
   megfigyelt SHA-alapú metaadatait.
5. A teszt futása nem kapcsolódott a Raspberry Pi éles FieldWork
   konténereihez, adatbázisához vagy alagútjához.

**NEM bizonyított:**
1. Az éles FieldWork-tároló teljes és pontos, tiszta Git-bázisa.
2. A valódi FieldWork frontend typecheck/lint/Vitest/build PASS.
3. A valódi FieldWork backend teljes pytest/regresszió PASS.
4. A Pi-n végrehajtott új privát canary-snapshotból történő
   HMAC-aláírt M8 readiness-ellenőrzés.
5. Az új MCP-adapter telepítése, automatikus stage-start, routing és rollback.

A szintetikus CI teszt a Node/PostgreSQL alapimage tagjét a CI
környezetben digestté oldja fel. Ez nem helyettesíti a felhasználó által
függetlenül jóváhagyott, tartalomazonosítóval rögzített éles buildet.
Az image címkéi önmagukban önbevallott metaadatok; az eredetigazolást
külön, helyben ellenőrzött buildbizonyítékkal és pontos image ID
jóváhagyással kell összekötni.

## Pi-oldali diagnózis ugyanebben a körben

A régi `cfb10c47c1b3413c9adbd50e5c7249ef` staging
`FULL_TEST_PASS` nyugtája változatlan. Az élő MCP v0.6.1 csak a
korábbi, fix backend stage életciklushoz rendelkezik jóváhagyással.

Egy új, külön `fieldwork_sandbox_command` hívással indított valódi
`python3 -m pytest -q --disable-warnings --maxfail=1` futás
a `configure_test_database()` biztonsági kapun
`UnsafeTestDatabaseError` hibával állt meg. A kontrollált
környezetben a tesztjelző jelen volt, a helyi DB host és DB név
megfelelőnek látszott; az egyéb URL- és jogosultsági feltétel
eltérésének oka nem bizonyított. Nem állítjuk, hogy a FieldWork
tesztjei megbuktak, mert gyűjtés/import közben megállt a futás.

A backend tesztkonténer, külön PostgreSQL, hálózat és snapshot
cleanupja minden kísérlet után PASS; `production_modified=false`,
`production_mounts=false`. Nem történt éles DB-migráció vagy
tunnel-/Docker-indítás.

## Következő tényleges kapu

1. Egy helyileg jóváhagyott, tiszta, privát Git-bázis létrehozása
   a követett HEAD alapján, az éles módosítások megőrzésével.
2. A valódi forrásból előállított és SHA256-tal rögzített canary
   stage teljes frontend+backend tesztje natív ARM64-en.
3. A `transfer_id`, archive hash, base commit, stage tree,
   image ID és öt suite HMAC-bizonyíték összekapcsolása.
4. Az MCP v0.6.1 védelmi korlátait megőrző, konkrét műveletekre
   szűkített, helyileg jóváhagyott adapter. A jelenlegi MCP nem
   ad host-shell vagy Docker-build jogosultságot, ezért az új
   valós Pi-integráció **még blokkolt**.

A PR #2 marad `draft`. **Production deploy nincs.**
