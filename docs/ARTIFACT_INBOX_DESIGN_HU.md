# FieldWork — ZIP nélküli MCP kiadásátadás

ÁLLAPOT: Inaktív fejlesztői komponens. NEM telepített Pi MCP-eszköz; nem jelent automatikus deployt.

## Megoldandó probléma

A ChatGPT felől közvetlenül továbbítható legyen a kiadás a meglévő MCP/tunnel kapcsolaton, a felhasználó általi letöltés, scp és SSH-s kódmásolás nélkül.

Az updater/artifact_inbox.py négy művelete: begin(transfer_id, size, sha256), append(transfer_id, offset, chunk_base64), status(transfer_id), finalize(transfer_id). A finalize kizárólag az átvitt bájtok méretét és SHA256-értékét ellenőrzi: nem csomagol ki, nem importál Python-kódot, nem futtat, nem telepít.

Határok: 32 MiB/artifact; 128 KiB/chunk; maximum nyolc lefoglalt transfer; a felhasználó saját .local/state/fieldwork-pi-mcp/artifact-inbox könyvtára; véletlen ID helyett pontos 32 karakteres hex ID. Tiltott az útvonal, általános shell, tetszőleges Docker-projekt és production-kötet megadása. SHA256-integritás önmagában nem kódbiztonsági igazolás.

## Mi hiányzik a végleges automatizáláshoz?

1. A futó Pi MCP főfájljának friss hash-pinningje és egyetlen helyi, pontosan körülhatárolt, rollbackelhető MCP-frissítés; nincs öntelepítés.
2. Négy dedikált, hitelesített és kvótázott MCP feltöltőeszköz, amelyek a fenti könyvtárfüggvényekre korlátozódnak.
3. Független, szigorú manifest-ellenőrző; a beérkező csomagokat csak a külön kiadáskezelő tekintheti át, és csak engedélyezett forráshelyekre használhatja.
4. Külön tesztkiadás: típusellenőrzés, lint, teljes frontend és backend tesztek, migrációk egy ideiglenes PostgreSQL adatbázison, kötelező HEALTH PASS.
5. Tartós tranzakciós napló, duplikált indítás elleni zár, előző canary megtartása, hibánál automatikus visszaállítás és negatív tesztek.
6. Éles kiadás kizárólag külön helyi explicit jóváhagyással, biztonsági mentéssel; nincs felügyelet nélküli éles deploy.

## Elfogadási feltétel

Nem elég a GitHub PR és a helyi teszt PASS. A feladat akkor kész, ha a Pi-n a dedikált új MCP-eszközök elérhetők, egy valódi kiadás ChatGPT felől manuális fájlmásolás nélkül átmegy, minden teszt sikeres, majd az új izolált canary egészségesen fut és rollbackkel ellenőrzött.

Jelenleg csak a transzport modul és az offline negatív tesztjei készültek el. A Pi MCP v0.6.1, production, staging, tunnel nem lett módosítva.
