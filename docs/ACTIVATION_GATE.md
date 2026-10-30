# Aktiválási biztonsági kapu – 2026-10-30

## Mi készült el?

Az `updater/activation_plan.py` egy **kizárólag olvasási, dry-run aktiválási tervet** állít elő. Nem telepít, nem állít le vagy indít újra szolgáltatást, nem futtat shell-parancsot, és nem érinti az éles FieldWorköt.

A terv kizárólag akkor készül el, ha a telepített MCP-főfájl hashértéke pontosan egyezik a `STATIC_QUALIFICATION_PASS` eredményben rögzítettel; a jelölt főfájl és a `stage_async.py` hashértéke is egyezik; a Git commit és a release-manifest pontosan azonos; nincs részlegesen telepített `stage_async.py`; nincs szimbolikus link és nincs más felhasználó által írható forrás.

**Az aktiválási terv semmilyen telepítési jogosultságot nem ad.** Az `activation_authorized` mindig `false`.

## Elvégzett helyi, offline tesztek

A jelenlegi fejlesztési körben a ChatGPT izolált munkakörnyezetében a `python -m unittest discover -s tests -v` futtatása az új `activation_plan.py` modulon: **12/12 PASS**. A tesztek vizsgálták a forráseltérést, jelölt- és bővítményhash-hibát, részleges telepítést, szimbolikus linket, hibás commitot és manifestet, túl nagy jelöltet, illetve az engedélyezési állapot megkerülését.

A Python-szintaktikai fordítás (`compileall`) PASS. A tesztek nem a Raspberry Pi-n futottak; a GitHub Actions eredményét külön kell ellenőrizni.

## Az aktiváláshoz még szükséges

1. A Pi tényleges `fieldwork_mcp.py` fájljának megbízható, csak olvasható forrásösszevetése.
2. A teljes MCP-csomag izolált tesztje a Pi környezetével kompatibilis függőségekkel.
3. Helyben, kifejezetten jóváhagyott aktiválás, nem általános távoli shell.
4. Atomi fájlcsere, tartós biztonsági mentés és megszakítás után is helyreállítható állapotgép.
5. A **meglévő** tunnel újraindítása, valódi readiness/MCP-discovery ellenőrzés, automatikus rollback.
6. A teljes telepítési és rollback-folyamat hibainjektálásos tesztje.

A fenti pontok teljesítése előtt a telepítés **TILOS**. A GitHubra feltöltött dry-run terv nem egyenlő működő önfrissítéssel.

## Élő állapot

A Pi v0.6.1 MCP elérhető, a fotófeltöltési javítás státusza `STAGE_PREPARED_NOT_TESTED`. Az éles `/opt/fieldwork`, a produkciós adatbázis és Docker, valamint a `fieldwork-pi-tunnel.service` nem lett módosítva ebben a fejlesztési körben.
