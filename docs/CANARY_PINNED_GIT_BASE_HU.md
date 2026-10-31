# FieldWork – elkülönített, rögzített Git-bázis és ZIP-alapú canary előellenőrzés

Állapot: GitHubon tesztelt, a Pi-n még NEM telepített. A meglévő négy MCP feltöltőeszköz továbbra is aktív.

## Miért nem az éles FieldWork checkout?

A Raspberry Pi `fieldwork_git_status` eredménye: az `/opt/fieldwork` `main` munkafája nem tiszta (többek között README.md és server/tests/test_admin_rotation.py módosítva, sok nem követett fájl). Nem lehet ezt automatikus kiadási alapnak tekinteni, és tilos ezek tisztításával vagy git resettel hozzáérni az éles rendszerhez.

## Egyetlen előkészítési lánc

1. A `fieldwork_artifact_finalize` már bizonyítja a fogadott csomag méretét és SHA256 értékét. Ezzel még nem válik végrehajthatóvá.
2. `canary_release_preflight.preflight_transfer` zárolja a konkrét, véglegesített transzfert. Nem fogad el szabadon megadott fájlrendszer-útvonalat.
3. `canary_archive_qualifier`: ZIP-taglista, allowlist, szigorú méretlimit és bounded read, manifest, korábbi SHA-érték, Python AST ellenőrzés. A csomag bázis-commitjának valóságát nem feltételezi.
4. `canary_git_base`: kizárólag `~/.local/state/fieldwork-pi-mcp/canary-git-base` külön, saját tulajdonú, tiszta Git-munkakönyvtárára támaszkodhat. Ez a könyvtár jelenleg még nincs igazoltan létrehozva a Pi-n; nincs automatikus git clone vagy checkout a modulban.
5. Az `HEAD^{commit}` tényleges bázis SHA-ja kötelezően egyezzen az archívumban szereplő commit SHA-val. A Git csak `status`, `rev-parse`, `ls-tree`, `cat-file` olvasási műveleteket kap; symlink és executable Git fájlmode elutasítva. A bázis-HEAD értékét újraellenőrzi.
6. `canary_change_planner`: minden célfájlt megvizsgál; új fájl csak akkor hozható létre, ha a bázisban nem létezik. Felülírás csak akkor fogadható el, ha a régi fájl bájtjai pontosan egyeznek a manifest `previous_sha256` mezőjével.
7. Eredmény: `RELEASE_PREFLIGHT_PASS_NOT_TESTED_NOT_STAGED`, amely tartalmazza a módosított fájlok listáját és a terv hashét, de nem írja ki és nem futtatja a forrásbájtokat, nem indít konténert, és nem állítja, hogy települt.

## Tesztbizonyíték

A tesztek ideiglenes valódi Git-repozitóriumban ellenőrzik a változtatott, untracked és szimbolikus hivatkozású fájlok, executable filemode, hibás SHA és hibás commit elutasítását. Külön teszt védi a bármelyik gate-en meghiúsuló átvitel után megmaradó eredeti feltöltést.

## Hátralévő, nem megkerülhető kapuk

- A Pi-n a tiszta, pontos M5 fejlesztési bázis külön Git-tárolójának ellenőrzött létrehozása. Semmilyen éles fájl nem törölhető vagy resettelhető.
- Az előellenőrzött források atomikus írása csak új, saját tulajdonú izolált stage munkakönyvtárba, tartós nyugtával.
- Teljes frontend typecheck/lint/Vitest, backend pytest, külön ephemerális adatbázis, async munkafolyamat és hiba utáni helyreállítás.
- Canary indítás, health/auth smoke, állandó 18090 port és stabil fejlesztői DB/JWT. Jelenleg a 18090 NEM aktív.
- Az új Pi-MCP eszközök aktiválása csak egy helyileg jóváhagyott, visszaállítható közös frissítéssel; további kiadásoknál ennek már nem szabad rendszerfájl-módosítást igényelnie.

Ne jelentsünk teljes automatikus telepítést, amíg a Pi-n ténylegesen nem látunk `TESTS_PASS`, `CANARY_HEALTH_PASS` és `FIXED_ORIGIN_AUTH_PASS` bizonyítékot.
