# M9 – FieldWork ARM64 offline test-appliance és privát Git-bázis

**2026-10-31. Állapot: GitHub PR #2 / CI-only jelölt, nem telepített.**

## Cél

A legutóbb jóváhagyott, változtathatatlan FieldWork Git-commitból
és az új `transfer_id`-hoz tartozó privát stage-ből egy valódi
frontend+backend ellenőrzés előkészítése, az éles FieldWork,
PostgreSQL és Docker-folyamatok módosítása nélkül.

Az eddigi Pi `cfb10c47...` staging `FULL_TEST_PASS` és
`STAGE_HEALTH_PASS` **régebbi release bizonyíték**. Nem alkalmazható
az új artifacthoz. A `/opt/fieldwork` munkakönyvtár piszkos;
annak nem commitolt fájljait soha nem használjuk release-bázisként.

## Elkészült GitHub komponensek

- `updater/canary_appliance_build_plan.py`: kizárólag olvasási,
  pontos SHA256-hoz kötött BuildKit **parancsterv**, nem futtat Docker-t.
  Csak tiszta, külön privát Git checkout és előre ellenőrzött, fix
  `appliance/` Dockerfile és script fogadható el. A Node 24 Bookworm
  és PostgreSQL 18 Bookworm alapképeinek teljes registry digestje
  kötelező (nem `:latest`, nem csak változó tag).
- `appliance/Dockerfile`: kizárólag négy source-manifest fájlt
  másol a privát Git-bázisból (frontend package.json/package-lock.json,
  két backend requirements). A tesztbelépő script külön ellenőrzött
  BuildKit kontextusból érkezik. A három függőségfájl és a script
  pontos SHA256 egyezését az image build előtt és közben igazolni kell.
- `appliance/fieldwork-test-suite`: fix öt tesztfázis:
  frontend typecheck, lint, Vitest, build; backend pytest ideiglenes
  PostgreSQL 18 alatt. A PostgreSQL csak a konténer loopback
  interfészén él. A forrás csak olvasható, teszt közben minden
  munkafájl és DB a konténer `/work`/`/tmp` tmpfs-ére kerül.
  `nss_wrapper` kezeli a host UID/GID és a PostgreSQL nem-root
  használatát ARM64/amd64 platformon.
- `updater/canary_appliance_image.py`: a helyi Docker által
  kiadott tényleges `sha256:<64hex>` image ID, platform,
  profile/deny címkék, három függőséghash és végrehajtható
  belépőscript-hash *független*, csak olvasási összevetése.
  Ez **nem helyi jóváhagyás**.
- `updater/canary_test_runner.py` minimális javítása: elfogad
  hashhez kötött, valóban helyben megépített Docker image ID-t
  registry push nélkül; a backendhez a `/tmp` tmpfs-t
  is előírja. A régi SHA256 RepoDigest formátumot nem töröltük.
  Minden régi korlát megmaradt: `--network=none`,
  `--pull=never`, `--read-only`, `--cap-drop=ALL`,
  `--security-opt=no-new-privileges`, rögzített
  `--user`, CPU/memória/PID-korlát, kizárólag
  `/source` read-only bind, Docker socket nélkül.

## Kötelező kiadási lánc

```text
EXPLICIT LOCAL APPROVAL
  -> clean pinned private Git base (NOT /opt/fieldwork worktree)
  -> immutable Node + PostgreSQL base-image digests
  -> reviewed Dockerfile and script SHA256
  -> BuildKit image (build may access package repositories)
  -> local image ID + content-label independent verification
  -> private canary stage SHA256
  -> 5 suites, offline networkless test containers, isolated PG
  -> independent HMAC proof for exact transfer_id/tree/base/image
  -> M8 READINESS_EVIDENCE_COMPLETE_NOT_DEPLOYABLE
```

**Nem történt meg** az ARM64 Docker build és a fenti valódi
FieldWork-tesztek futtatása a Pi-n. A GitHub offline Python és
shell-szintaxis tesztjei nem helyettesítik a natív tesztet.

## Kötelező előfeltételek a Pi-n történő első használathoz

1. Helyben ellenőrzött, tiszta, privát Git-bázis, pontos HEAD SHA
   és külső trusted pin. Az éles checkout marad olvasási forrás
   csak a *követett Git objektumokhoz*, a working tree módosításait
   nem másoljuk.
2. BuildKit, ARM64 Node/Postgres alapképek **valódi** digestjei,
   az immutable PR SHA és a két policy fájl SHA256 értéke.
   Digestet nem találunk ki.
3. Az épített image csak akkor használható, ha a helyi
   `docker image inspect sha256:...` kimenetéből vett
   ID/platform/dependency/script SHA egyezés igazolt.
4. A Pi adminja külön, explicit jóváhagyja az adott image ID-t
   és a privát teszt-nyugtához tartozó helyi HMAC kulcsot.
   Jelszó, privát kulcs, `.env` vagy kliensadat nem kerül GitHubra.
5. A valós canary ZIP `base_commit` és `previous_sha256`
   értékei a tiszta privát bázisból származnak.
   A korábbi, szintetikus `aaaaaaaa...` base_commit
   nem használható release-re.
6. Az első tényleges Pi-futtatáskor ellenőrizni kell az
   `npm ci` ARM64 kompatibilitást, Python csomagokat,
   a PostgreSQL initdb-t, az admin-rotation és migration
   backend teszteket, valamint az OOM/timeout hibakezelést.

## Kockázatok és döntés

- **Build nem offline**: az egyszeri függőségépítés csomagforrásokat
  igényelhet; a kész image öt tesztjét már networkless futtatjuk.
- **Nem bitazonosan reprodukálható build**: bár a Node/Postgres
  image digest és source-manifest SHA-k rögzítettek, az
  `apt` és Python transzitív csomagok kiadási változása
  befolyásolhatja a buildet. A végső image ID ezért külön
  jóváhagyandó, később SBOM/package lock szigorítás kell.
- **Meglévő backend stage újrahasznosítása**: továbbra is
  alternatíva. Az új, egykonténeres teszt-appliance
  *nem kapcsolódik automatikusan* a legacy stage projekthez.
  Csak akkor választjuk, ha a valós natív teszt bizonyítja,
  hogy kevesebb és kezelhetőbb üzemeltetési kockázatot ad.
- **Nem telepítő**: a fejlesztés nem ad hozzá új live MCP-eszközt,
  nem indít konténert, nem állít át nginxet, nem hoz létre tunnelt,
  nem változtatja meg az éles `/opt/fieldwork` checkoutot
  vagy PostgreSQL-t.

## M9 elfogadási feltétel

A GitHub CI offline szerződés- és negatív tesztjei PASS,
utána natív Raspberry Pi ARM64 build és mind az öt valódi
tesztsuite PASS az **új privát stage-en**. Ezt követheti
egy külön, helyileg jóváhagyott MCP-adapter,
canary start, smoke, rollback és fix LAN-only DEV gateway.
**Canary deploy és production deploy jelenleg BLOCKED.**
