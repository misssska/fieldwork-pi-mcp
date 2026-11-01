# FieldWork M6 R9 – R5 izolált canary első indítás

**Állapot:** előkészített, szintaktikailag és offline/unit teszttel ellenőrzött, a Pi-n **még nem futtatott**. Production és a 18090-es DEV gateway nincsenek módosítva.

## Bemeneti bizonyíték

2026-11-01 Pi admin nyugta: `M6_R4_POSTGRES_BACKEND_95_TESTS=PASS`, `M6_R4_FRONTEND_PREVIOUSLY_VERIFIED_107_PASS`, `M6_R4_FULL_TESTS_PASS_NO_DEPLOYMENT`. M6-jelölt: `$HOME/.local/state/fieldwork-pi-mcp-v03/stage-v06/parity-m6._sdfbhky`. A R5 launcher ellenőrzi az előző tesztjelsorokat, a módosítások manifestjét és az R3/R4 tesztfájlok pontos SHA256-értékeit.

## Elkülönítés és korlátok

- Csak új `fieldwork-parity-m6-r9` Docker Compose projekt, csak `192.168.22.13:18086` publikus HTTP-kötés.
- A Compose belső DB hostja `db:5432`; külső hálózat, külső/nem projektazonosítós kötet, bind mount, privileged szolgáltatás, további publikus port elutasítva.
- A Pi-n már meglévő M6 jelölt eredeti `docker-compose.stage.yml` és `.env.stage` konfigurációját használja. **Ezek tartalmazhatnak a korábbi R8-cal közös DEV tesztbeállításokat és kezdeti belépési adatokat**; nem teszünk úgy, mintha a hitelesítés teljesen szeparált lenne. Maga az adatbázis és a kötet a külön Compose-projekt miatt különül el, ha a szigorú konfigurációs ellenőrzés PASS.
- A `FIELDWORK_DEV_ADMIN_ALIAS` nem kapcsolható be ebben az R5-ben; külön M6 fejlesztésben ellenőrizni kell a kanonikus e-mail címek és aliasok helyességét. `admin/admin` nincsen beállítva.
- **Nem másol R8 adatot**, nem biztosít token-/bejelentkezés-folytonosságot és nem telepít át semmit a 18090-re. A 18090 későbbi váltása külön adatmegőrzési és rollback-kapu.
- HTTP LAN-IP binding, nem HTTPS vagy tűzfal-ellenőrzés.
- Ha az első Docker indítás sikertelen, kizárólag a saját M6 Compose projekt konténereit állítja le `down`-nal, a névvel ellátott köteteket nem törli. A teljes log megmarad.

## Helyi végrehajtás

A Pi `admin` SSH termináljában csak az ellenőrzött forrással, helyi jóváhagyással:

`python3 -B launch_m6_canary.py --precheck` (semmi nem indul), majd `--launch` (saját canary konténer indul). A letöltési URL-t, commitot és SHA256-értéket csak a GitHub forrás pontos visszaellenőrzése után lehet kiadni.

Elvárt siker: `M6_R5_CANARY_18086_HEALTH_PASS=YES` és `M6_R5_URL=http://192.168.22.13:18086`. Eredmény után külön böngészőn ellenőrizni: admin login, új worker, project owner → viewer, GET engedett, POST 403, komment UI nem írható; R8 stable 18090 és production működő health. Ne állítsuk, hogy ez már megtörtént a tesztfutás előtt.

A Pi mért 107/107 frontend és 95/95 backend sikere **nem** helyettesíti az új canary böngészőből végzett szerepkör-/adatmegőrzési tesztjét.

## R6 fail-closed overlay manifest javítás – 2026-11-01

**Valós Pi STOP:** `STOP: M6_R5_STOP:M6_OVERLAY_FILE_SHA_DRIFT:server/tests/test_account_m6.py`. Nem történt canary-indítás; a 18090-es R8 érintetlen.

Gyökérok: az eredeti M6 `.m6-r9-source-receipt.json` a fájl R4 előtti, `85e275f12237cfd7c52b121140bc829d28d09566fdacef42dabbbb680aa8f3e7` SHA-ját tartalmazza. A sikeres R4 négy `@example.test` tesztadatot `@example.com`-ra cserélt, így a fájl pontos aktuális SHA-ja `d58df43a030610ce04a4192f4708099bff69afd87f9f761c43a8dfb1e1169d27`; ez **nem illegitim változás**. Az eredeti receiptet TILOS átírni.

R6 kizárólag `server/tests/test_account_m6.py` esetén engedi a receipt régi SHA-ját ÉS a telepített jelölt új SHA-ját együtt, a meglévő R4 eredeti backup, R3/R4 naplók, 107+95 PASS, négy különösen fontos backendteszt és minden más overlay pontos hash-ellenőrzése mellett. Minden eltérés STOP. Az alkalmazáskód, tesztek és gateway változatlanok.

- Változás **ugyanabban a draft PR #4-ben**, az eredeti első-canary indító helyén, nem külön alternatív belépési ponton.
- Indító (pin): GitHub `e1df766b76857b3aac94fd84439334a6e5459b9f` commit, `updater/fieldwork_m6r5_first_canary_18086.py`, **SHA256 `dca91fe17949dc6ff23212bea6e7fef405b65b4bfe80d1888d0fc5bfd5b501a4`**, Git blob `619ed3b9498c119388f1d38954fd6455e466245a`.
- Helyi teszt: 14 meglévő + 8 új manifest-tamper vizsgálat = **22/22 PASS**. Az eredeti R2 archívum valós fixture-fájljából származtatott R4 SHA-lánc külön PASS.
- [GitHub Actions #41318532396](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41318532396): x86-64 SUCCESS és ARM64 SUCCESS; [globális MCP unit #41318532478](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41318532478) SUCCESS.
- **Élő Pi `--precheck` és `--launch` még NEM történt meg az R6-tal.** 18086 M6 canary nincs igazolva, 18090 marad R8, production érintetlen.

