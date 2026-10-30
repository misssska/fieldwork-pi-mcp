# Helyi jóváhagyási protokoll – izolált ellenőrző

## Mi került a repositoryba?

Az `updater/local_approval_lab.py` a későbbi **helyben jóváhagyott** frissítés egyik biztonsági komponensének prototípusa. Egy lokálisan kiállított, HMAC-SHA256-al hitelesített, legfeljebb 5 percig érvényes bizonyítékot ellenőriz, amely pontosan a következő értékekhez kötött:

- Git commit SHA-1 (40 hex karakter)
- release manifest SHA-256
- telepített MCP-főfájl SHA-256
- jelölt MCP-főfájl SHA-256
- `stage_async.py` SHA-256
- 128 bites egyszer használatos nonce, kiállítási és lejárati idő, fix műveleti cél

Az `verify_and_consume()` egyetlen belépési pontban hitelesít és használ fel egy bizonyítékot, kizárólag a felhasználó privát `~/.local/state/fieldwork-pi-mcp/local-approval/used` könyvtárában. Az ismételt felhasználást `O_EXCL` védi. Az írás könyvtárfájl-leíróhoz kötött, a symlinkes útvonalak tiltottak.

**Ez nem telepítő, és nem teljes értékű jóváhagyási rendszer.** A repository **nem tartalmaz tokenkiállítót, titkos kulcsot, helyi jóváhagyási felületet vagy MCP-n keresztül hívható aktiválást**. Az ellenőrző sem a Pi-n, sem másutt nem ad telepítési jogot; a válaszban az `activation_authorized` mindig `false`. A `used` könyvtárat csak egy később elkészülő, helyben ellenőrzött komponens hozhatja létre.

## Tesztek és korlátok

A `tests/test_local_approval_lab.py` **17 új offline tesztesetet** tartalmaz: helyes bizonyíték, hibás HMAC, megváltoztatott tartalom, eltérő commit/jelölt hash, lejárt vagy túl hosszú időablak, jövőbeli kiállítás, hibás cél, váratlan mező, túl rövid kulcs, nonce ismételt felhasználása, hamis bizonyíték, eltérített célkönyvtár és szimbolikus linkes útvonalak.

A tesztkód GitHubra feltöltve. **A GitHub Actions futásának eredménye jelenleg nem igazolt; a tesztek PASS státuszát nem állítjuk.**

A későbbi éles verzió előtt szükséges: a Pi-n ténylegesen helyi jóváhagyáshoz kötött tokenkiállító, titkos kulcs izolálása a távoli MCP-től, jogosultságkezelés, többfolyamatos versenyhelyzetek és fájlrendszerhiba-tesztek, éles szolgáltatás-readiness, visszaállítás és teljes ARM64 integrációs teszt.

## Mit nem érintett?

- Éles `/opt/fieldwork`, PostgreSQL, Docker
- Futó Pi MCP és `fieldwork-pi-tunnel.service`
- GitHub bootstrap manifest: a prototípus **szándékosan nincs** a Pi-re letöltendő modulok között.
