# Pi MCP – teljes frissítési folyamat izolált próbája (2026-10-30)

**Állapot: CI-tesztelt, offline labor. NEM Pi-telepítő, nem éles jóváhagyó és nem production release.**

## Elkészült

A `updater/lifecycle_rehearsal.py` egyetlen, négyfájlos tranzakciós
tesztfolyamattá köti össze a meglévő `local_approval_lab.verify()`
HMAC-ellenőrzést és a `LifecycleLabTransaction` fájlrendszeres
visszaállítási próbát:

1. Rögzített Git-commit, manifest, telepített forrás és jelölt fájlok SHA-256 ellenőrzése.
2. A három runtime-modul nevének és bájt-hashének domain-szeparált közös
   lenyomata a jóváhagyás `extension_sha256` mezőjében. Nem maradhat ki modul.
3. Tesztkulccsal előállított, aláírt, rövid élettartamú bizonyíték
   ellenőrzése; hibás/lejárt/eltérő token elutasítása.
4. Egyszer használható nonce tartós, atomikus létrehozása, kizárólag a
   tesztkönyvtáron belül; replay elutasítása még sikertelen tranzakció után is.
5. Négyfájlos, atomi mentés/csere. Szimulált `pass`, `fail`, `error`
   eredmény alapján byte-ellenőrzéses lezárás vagy hash-ellenőrzött rollback.
6. Hat megszakítási ponton újraindítható tranzakció helyreállításának tesztje.

A rendszer nem tud parancsot futtatni a Pi-n. Nem képes az MCP-t vagy a
tunnelt újraindítani. Nem hív valódi HTTP health-checket, és nem állítja,
hogy az éles szolgáltatás healthy.

### Izoláció

A tranzakció kizárólag
`/tmp/fieldwork-mcp-lifecycle-lab-*/mcp` alakú, felhasználó tulajdonában
álló saját tesztkönyvtárba írhat. A próba által elfogadott
`simulated_health` csak `pass`, `fail` vagy `error`.
Sem az MCP, sem tetszőleges távoli felhasználó nem érheti el RPC-ként.
A teszt-HMAC-kulcs nem lehet Pi-aktiválási hitelesítő adat.

## Reprodukálható teszt

```bash
python -m unittest discover -s tests -p 'test_lifecycle_rehearsal.py' -v
python -m unittest discover -s tests -p 'test_*.py' -v
PYTHONPATH=bootstrap python -m unittest discover -s bootstrap/tests -p 'test_*.py' -v
python -m compileall -q updater bootstrap experimental
```

GitHub Actions PR #1, 2026-10-30: **217/217 updater/experimental teszt PASS,
12/12 bootstrap teszt PASS**, Python compileall PASS. (A branch utolsó
dokumentációs commitja után a CI-állapotot újból ellenőrizni kell.)
A tételes GitHub Actions napló az elfogadási bizonyíték;
nem a helyi teszt deklarációja.

## Kötelező különbség az éles működéstől

| Labor | Valódi Pi-aktiválás esetén szükséges |
| --- | --- |
| Tesztben előállított HMAC token | Független, kizárólag helyben működő jóváhagyó/kiállító, titkos kulcs védelemmel |
| Temp-könyvtárba írás | Szigorúan rögzített, tényleges telepített MCP útvonal és telepítési jogosultság |
| Szimulált health PASS | Systemd + MCP discovery + meglévő tunnel + rollback utáni readiness |
| Lab nonce és journal | Tartós, boot után is olvasható, tulajdon-/jogosultság-ellenőrzött állapotgép |
| Mockolt hibahelyek | ARM64 Pi integráció, valódi crash/reboot, race, lemezhiba és helyreállítási próbák |

## Aktuális blokkolók

1. A telepített `fieldwork_mcp.py` helyi SHA-256 értéke korábban
   `7d24bcfa...` volt, míg a kiinduló release eredeti fájlja
   `b504460d...`; az eltérés nincs forrásszinten feloldva.
2. A jelenleg elérhető Pi MCP csak rögzített, korlátozott műveleteket
   kínál; nem írhatja át a saját hostfájljait és nem indíthatja újra a
   saját tunnelezését.
3. Hiányzik az új lifecycle komponensek Pi-n történő, helyileg
   jóváhagyott telepítése és teljes integrációs ellenőrzése.
4. A FieldWork staging jelenlegi `STAGE_HEALTH_FAIL`, így új funkciót
   még nem szabad prod release-ként címkézni.

**Döntés:** PR #1 marad draft; nincs main merge, nincs automatikus
host-frissítés, nincs produkciós változtatás. Következő valódi
üzemeltetési kapu: Pi-forrásazonosítás és a helyi, biztonságos aktiváló
implementációjának önálló auditja.
