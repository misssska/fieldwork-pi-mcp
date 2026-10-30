# MCP frissítési tranzakció — izolált hibainjektálási labor

## Elkészült

A `updater/transaction_lab.py` **csak tesztkönyvtárban** használható, két fájlra kiterjedő, tartós állapotú tranzakciós motor:

1. A meglévő `fieldwork_mcp.py` hashértékének ellenőrzése.
2. Tartós biztonsági másolat elkészítése, majd a tranzakciós napló rögzítése.
3. `APPLYING` állapot mentése **még a fájlcserék előtt**.
4. A `stage_async.py` és a főfájl atomikus fájlcseréje, könyvtár-`fsync` műveletekkel.
5. Váratlan megszakítás után az eredeti főfájl visszaállítása és a kiegészítő eltávolítása.
6. Az ismeretlen, időközben megváltozott fájlok automatikus felülírásának elutasítása.

**16/16 PASS** a ChatGPT izolált Linux tesztkörnyezetében, köztük külön Python-folyamatban előidézett összeomlás és másik folyamatban végrehajtott visszaállítás. A `python -m compileall` ellenőrzés PASS.

## Biztonsági korlát

A labor motorja kizárólag a rendszer átmeneti könyvtárában, `fieldwork-mcp-lab-*` nevű saját könyvtár `mcp` almappájában hajlandó működni. A tényleges Pi MCP-fájlokhoz, az `/opt/fieldwork` könyvtárhoz, Dockerhez vagy a tunnelhez **nem fér hozzá**.

A `mark_health_verified_for_lab()` csak tesztállapotot jelöl, **nem** végez valódi MCP health checket. A motor nincs bekötve az MCP távoli eszközei közé és nincs telepítési parancssori belépési pontja.

## Éles aktiválás előtt hiányzó elemek

- A Pi tényleges MCP-indítási és systemd/tunnel függőségeinek helyben igazolt feltérképezése.
- Helyben, egyértelműen jóváhagyott, egyszer használható aktiválási engedély; a távoli MCP-eszköz nem adhat magának ilyen engedélyt.
- Kizárólag az ellenőrzött, fix Pi-telepítési könyvtárra engedélyezett külön telepítőadapter.
- Tranzakciós zárolás több egyidejű kérés és versenyhelyzet ellen.
- Valódi szolgáltatás-újraindítás és readiness + MCP discovery, majd hibánál automatikus visszaállítás.
- Áramszünet-, lemezhiba-, szolgáltatás-hiba- és rollback-hibainjektálás az ARM64 környezetben.

Ezek nélkül a rendszer **nem alkalmas éles telepítésre**. A GitHubra feltöltött laborfájl szándékosan nincs a bootstrap manifestben, így a Pi nem tölti le frissítőkomponensként.
