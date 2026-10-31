# FieldWork – közvetlen canary-forráscsomag protokoll

Állapot 2026-10-31: a négy Pi MCP adatátviteli eszköz működik, de az archívumfeldolgozó, tesztelő és kiadásváltó adapter még nem aktív.

## Kész és ellenőrzött

- ChatGPT -> Pi MCP: `fieldwork_artifact_begin`, `fieldwork_artifact_append`, `fieldwork_artifact_status`, `fieldwork_artifact_finalize` – aktív és ténylegesen tesztelt.
- 81 bájtos korábbi inert próba és 633 bájtos, ZIP+manifest formájú próba is `VERIFIED`; az utóbbi SHA256: `605b35b2db63fb5c07019d75dae3363f62567fd9b2b6d806b0b376f9b42077cc`.
- `canary_archive_builder.py`: meghatározott forrásbájtokból determinisztikus ZIP, amelyet saját maga a statikus minősítőn is átvezet.
- `canary_archive_qualifier.py`: csak olvassa a véglegesített, hashhez kötött ZIP-et, nem csomagol ki és nem futtat; pontos manifest, allowlist, 64 fájlos, 2 MiB/fájl és 24 MiB összes forráskorlát, maximált kitömörítés.
- `canary_archive_adapter.py` és `canary_archive_overlay.py`: jövőbeli ötödik MCP-eszköz, `fieldwork_artifact_qualify`, kizárólag statikus validáció. Jelenleg csak PR-ben tesztelt, a Pi-n még nem aktív.
- Utolsó GitHub Actions: run 41185019170, 271 updater unittest PASS, 12 bootstrap unittest PASS, syntax compile PASS.

## Archívumformátum

ZIP gyökér: `MANIFEST.json` és a manifestben név szerint felsorolt source fájlok, semmi más.
Manifest kulcsok pontosan: `schema=1`, `kind=fieldwork-canary-overlay-v1`, `base_commit` (40 hex; külön igazolandó valós bázis), `files` lista.
Minden fájlnál `path`, `size`, `sha256`, `previous_sha256`. Utóbbi null csak új forrásfájlnál, meglévő fájlnál a régi fájl tényleges SHA256 értéke; a későbbi isolated apply-nak ezt kötelező ellenőriznie.

Csak `frontend/src/**/*.ts|tsx|css|svg`, `server/app/**/*.py` és `server/tests/test_*.py` forrásfájlok engedélyezettek. Tilos az útvonalbejárás, abszolút út, symlink, ZIP extra tag, rejtett környezeti fájl, Dockerfile, általános shell, éles adatbázis és minden deklarálatlan fájl. Python AST ellenőrzés van; TypeScript teljes build/típusellenőrzés csak a későbbi izolált test-gate része.

## Életciklus – még fejlesztendő, nem megkerülhető

1. Az MCP `qualify` a teljes ZIP-et integritás alapján ellenőrzi. A `VERIFIED` még **nem** `QUALIFIED`, és a `QUALIFIED` sem `TESTED`.
2. Isolated stage: pontos M5 kiadásforrás, előző fájlhash és bázisazonosító ellenőrzése után külön privát munkakönyvtár. Éles `/opt/fieldwork` érintetlen.
3. Teljes frontend typecheck/lint/Vitest, backend pytest, izolált teszt-PostgreSQL, migrációs és regressziós próbák, tartós async receipt. Az input code csak elkülönített tesztkörnyezetben futhat.
4. Canary indítás előre jóváhagyott külön Docker project/port mellett, majd readiness, auth és adatmegőrzési smoke.
5. Dev gateway: tervezett fix LAN cím `192.168.22.13:18090`. A tunnel jelenleg `127.0.0.1:18080` portot használ; a fix 18090 port szabad voltát és teljes LAN-only védelmét éles váltás előtt ellenőrizni kell.
6. Az M5/M6 tesztadatok, a felhasználóazonosság és a JWT kulcs folytonossága kötelező kapu. Hibánál route rollback, adatbázis rollback csak explicit ellenőrzött tervvel.

## Fontos üzemeltetési korlát

Az aktív `artifact_inbox.py` legfeljebb 8 transzferkönyvtárat enged, és még nincs MCP-n keresztül biztonságos lezárási/takarítási művelet. A teszttranszferek is foglalnak helyet. Automatikus feltöltési ciklus előtt biztonságos retention/GC és készültségi receipt szükséges. Ne jelentsük a folyamatot véglegesnek, amíg ez nincs meg.

Az archivált, 633 bájtos próba `base_commit` értéke tesztazonosító, **nem** valós FieldWork Git commit; csak átviteli tesztre használható, telepítésre nem.
