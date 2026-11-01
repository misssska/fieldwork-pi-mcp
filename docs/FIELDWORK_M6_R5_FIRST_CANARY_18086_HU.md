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
