# M11 – Sandbox timeout/cleanup javítási jelölt, 2026-10-31

## Állapot

**M11 PATCH CANDIDATE + CI: PASS; VALÓDI PI-TELEPÍTÉS: BLOCKED.**

A felhasználó read-only, SHA256-mal ellenőrzött AST-leltárából a
**telepített** Raspberry Pi MCP v0.6.1 két forrása ismert:

| Fájl | Helyi SHA256 |
| --- | --- |
| `sandbox_command.py` | `5255968dac5c0bb8ac3a94eb72f3131ea2081b683974d97db6bb9ddc3d432615` |
| `runtime_runner.py` | `ae0387aed34768a7260cf01e6c1ff9d4620c506c37e7ae2a74706f661ee2db6c` |

A `sandbox_command.run_command` eredeti, kitakart AST-vezérlési
folyamata:

1. `r._run(..., timeout=r.MAX_SECONDS)` a tesztkonténerre.
   `r.MAX_SECONDS=180`.
2. `runtime_runner._run` a fix Docker binárist indítja
   `subprocess.run(..., shell=False, timeout=...)` módban;
   `subprocess.TimeoutExpired` esetén `ValueError("DOCKER_TIMEOUT")`.
3. `runtime_runner._test_args` a Docker `run --rm --name`
   paramétereket használja.
4. A `run_command` a finally ágon `docker rm -f <test>`
   műveletet indít, `timeout=12` másodperccel.
5. Ha az `rm` nem nulla kóddal tér vissza, a jelenlegi MCP egyetlen
   `docker inspect` eredményét vizsgálja; **bármely**
   nem nulla inspect-kódot „konténer nem létezik” jelzésnek vesz.
6. Ha az `rm` sikeres, nincs független ellenőrzés. Timeout
   esetén a `ValueError` cleanup=false nyugtát okozhat.
   Minden nem sikeres cleanup státusz `RUNTIME_CLEANUP_FAILED`.

### Megerősített hiba, de nem bizonyított egyedi kiváltó ok

A nem nulla `inspect` státusz **nem bizonyít hiányt** (Docker-daemon
elérhetetlenség, jogosultsági és kommunikációs hiba is lehet).
Ezenfelül a `--rm` és a külön `rm -f` műveletek között versenyhelyzet
lehetséges. A sikertelen 2026-10-31 13:58:51 CET-es
`b901aaabbbcccdddeeefff0000000020` futás konkrét belső
Docker-hibakódja nem áll rendelkezésre; **nem állítjuk, hogy
pontosan ez a versenyhelyzet történt.**

A későbbi, valódi Pi Docker-host leltárban 26 konténer volt, a
legújabb 2026-10-30 22:36:56 CET-kor keletkezett; nincs a hibás
futáshoz azonosítható jelenlegi sandbox árva. A történelmi hibás
nyugta változatlan. Éles/stage/plan/parity konténereket **nem**
törölünk.

## Javítási jelölt (GitHub fejlesztői ág, még nem telepített)

- `updater/sandbox_cleanup_overlay.py`: kizárólag a
  **pontos, fent rögzített SHA256-ú** telepített
  `sandbox_command.py` memóriában átadott bájtjain végez
  változtatást. A run_command `finally / if attempted`
  blokkjának AST alakját is ellenőrzi. Eltérő forrás SHA,
  más szerkezet, többszörös anchor vagy váratlan cleanup-ág
  esetén **STOP**.
- Kizárólag az eddigi `test_container` eltakarítási ágat
  cseréli ki; sem `test_database_guard`, sem
  `runtime_runner.py`, sem a stage manager/produkciós kód
  nem módosul.
- A Docker `rm -f` akár sikeres, akár sikertelen vagy
  timeoutos, az eredményt **két külön sikeres, pontos
  konténernévre szűrt** `docker container ls --all`
  ellenőrzés igazolja. Mindkettőnek nulla kóddal és
  **üres konténer-ID listával** kell végeznie.
- Docker-CLI/probe timeout, nem nulla kód, bármilyen
  jelenlévő konténer vagy nem üres/redaktált kimenet:
  cleanup=false (fail-closed).
- **Nem** módosítja a korábbi futási nyugtákat; a test-fail,
  timeout és full-test-run readiness külön marad.
- A transform `build(installed_source: bytes)` függvénye
  **nem olvas fájlt, nem futtat Docker-parancsot, nem telepít,
  nem restartol MCP-t vagy tunnelt**, és explicit
  `activation_authorized=false` jelzést ad.
- Az eredmény `candidate_source` csak fejlesztői jelölt,
  **nem jogosít a Pi automatikus átírására**.

## Tesztelt bizonyítékok

| Teszt | Eredmény | Korlát |
| --- | --- | --- |
| [Unit/contract CI #41209756010](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41209756010) | **515/515 PASS** (503 updater + 12 bootstrap) | A patch AST-tesztje szintetikus forráson fut, nem a Pi telepített fájlján |
| [Valódi Docker CI #41209753853](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41209753853) | **SUCCESS, 5 M11 invariáns PASS** | Valódi Docker daemon, de szintetikus izolált GitHub runner, nem Raspberry Pi |
| Python szintaxis/compile a teljes repón | **PASS** | Nem éles forrás-összeillesztés |
| Valódi Pi `sandbox_command.py` pontos SHA és AST | **ellenőrzött** (felhasználói kimenet) | A teljes, telepített eredeti bájtsorozat nincs a GitHub repóban |

A Docker CI a saját két percen belül eldobható konténerén teszteli
a sikeres törlést, a `--rm` által előre eltakarított konténert,
a szimulált rm-hibánál tényleg létező konténert, a hibás
Docker-lekérdezést és azt, hogy nem érinti a Pi-t.

### Maradék kötelező kapuk

1. **Valódi telepített SHA-pinned forrásra alkalmazott,
   csak olvasási patch-preview:** AST és candidate SHA256
   igazolása; a snapshot az operátori review-hoz szükséges,
   az eredeti forrás titkait nem kell megosztani.
2. **Pi ARM64 izolált integrációs próba** a megváltozott
   cleanup-ággal, a Docker daemon hibaágával és `--rm`
   versenyhelyzettel, a privát produkciós kód és DB nélkül.
3. **Egyetlen külön, pontos bájtokra szóló helyi jóváhagyás**,
   atomikus mentés, aktiválási és rollback-kapuk.
4. Live MCP tool discovery, helyi health/staging és új
   sandbox-futtatási tesztek, a korábbi hibás nyugta
   visszamenőleges módosítása nélkül.

**Az aktív Raspberry Pi MCP v0.6.1, a FieldWork produkció,
PostgreSQL, Docker és a meglévő tunnel változatlan.**
A PR #2 **draft**, nem release-kész. Az új javítás
biztonságos telepíthetősége a fenti kapukig **BLOCKED**.
