# Négyfájlos MCP lifecycle tranzakció – izolált labor

Állapot: **tesztelt kísérleti modul, nincs Raspberry Pi telepítés, nem használható aktiválásra.**

## Cél

A 2026-10-30-i ötfájlos lifecycle jelölt három futtatandó Python-bővítményt
igényel a `fieldwork_mcp.py` mellett:

- `stage_async.py`
- `stage_inspect.py`
- `stage_start_async.py`

A két overlay kizárólag a jelölt főfájl **előállítására és ellenőrzésére**
szolgál, ezért nem kerül a telepítendő runtime fájlkészletbe.

A `updater/lifecycle_transaction_lab.py` négyfájlos fájlcserét és
megszakítás utáni helyreállítást modellez, **kizárólag** az operációs
rendszer átmeneti könyvtárán belül, `fieldwork-mcp-lifecycle-lab-*/mcp`
alakú, saját tulajdonú tesztkönyvtárban.

## Védelmi modell

- Fix fájllista; tetszőleges célútvonal, host shell, Docker/systemd művelet,
  hálózat, tokenkiállító, produkciós telepítés nincs.
- SHA-256 ellenőrzés az eredeti és minden jelölt fájlon; maximális méret 1 MB/fájl.
- Szimbolikus link, idegen tulajdon és veszélyes írási jogosultság kizárása.
- Egy tranzakciót védő `flock`; tartós backup és napló az első csere előtt.
- Modulok írása után **utolsóként** cseréli a főfájlt; atomi fájlcsere,
  `fsync` a fájlokon és az érintett könyvtáron.
- A helyreállítás az összes ismert fájl hashértékét ellenőrzi **mielőtt**
  bármit visszaírna vagy törölne; ismeretlen változtatásnál leáll.
- A `LAB_BYTES_VERIFIED_ONLY` nem MCP-/tunnel readiness és nem telepítési jóváhagyás.
  Minden státuszban `activation_authorized=false`.

## Megismételhető helyi teszt

A repository gyökerében:

```bash
python -m unittest discover -s tests -p 'test_lifecycle_transaction_lab.py' -v
python -m compileall -q updater/lifecycle_transaction_lab.py
```

A készítő izolált Python 3.13.5 környezetében **18/18 teszt PASS**.
Ezek közül egy teszt külön alfolyamatban megszakított írást ellenőriz;
egy másik hat mesterséges megszakítási pontot fed le. A további tesztek
eltérő hash, hiányos payload, szimbolikus link, rossz napló, hamis backup,
konkurens változtatás és duplikált tranzakció ellen védenek.

**Nem igazolt:** Raspberry Pi függőség-/fájlrendszer-kompatibilitás,
éles MCP-forrás-hash drift, GitHub Actions PASS, tényleges systemd/service
restart és readiness, helyi felhasználói jóváhagyás, teljes restore
áramkimaradás és hardverhiba esetén.

## Kapuk tényleges aktiválás előtt

1. A Pi telepített `fieldwork_mcp.py` fájljának helyileg megbízható
   azonosítása; a korábbi SHA-256 eltérés megszüntetése **forrásösszevetéssel**,
   nem a hash-ellenőrzés kikapcsolásával.
2. Változatlan Git commitra és manifestre rögzített lifecycle qualification,
   illetve a Pi-n is teljes izolált teszt.
3. A helyi felhasználó konkrét, rövid élettartamú, egyszer használatos
   jóváhagyása a rögzített fájlhash-ekhez, általános shell nélkül.
4. A valódi frissítő külön megvalósítása, atomikus mentés/csere,
   crash/reboot utáni rollback és szolgáltatás-readiness ellenőrzéssel.
5. A **meglévő** `fieldwork-pi-tunnel.service` felügyelete,
   regressziók, visszaállítási teszt, csak ezután staging-diagnosztika.

A labor **nem** jogosult és **nem** képes a Pi MCP vagy az éles FieldWork
módosítására. Nem szabad átnevezéssel vagy a célútvonal-korlátok
megkerülésével telepítőként használni.
