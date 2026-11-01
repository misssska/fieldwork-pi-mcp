# M15-H – GitHub commithez és külső SHA256-hoz kötött, ZIP-másolás nélküli INAKTÍV bootstrap

**2026-10-31 – natív Linux CI-mérföldkő. NEM Pi-telepítés.**

## Mi változott?

A már bizonyított M15-B (`m15_inactive_bootstrap.py`) rendelkezett
root-owned, csak olvasható, visszavonható inaktív telepítéssel,
de a csomagot külön manuálisan kellett volna a hostra juttatni.

Új: `updater/m15h_pinned_nozip_bootstrap.py`.

Az eszköz kizárólag az ismert
`misssska/fieldwork-pi-mcp` publikus GitHub repository
`raw.githubusercontent.com` HTTPS-végpontjáról, **egyetlen
rögzített, 40 karakteres commitra** kérheti le a
`m15_portable_bundle.FILES` pontos, név szerinti listáját.
Nincs tetszőleges URL, eltérő repo, ág, ref, path, HTTP-redirect
vagy külső host; rövid timeout és 256 KiB/fájl felső korlát.
Minden letöltött bájt csak adat, nem lesz futtatva vagy importálva.

Az összegyűjtött bájtokból determinisztikusan újraépíti az M15
archívumot, és annak SHA256-ját **előre, függetlenül ismert**
`--trusted-archive-sha256` értékkel hasonlítja össze.
A lokálisan előállított manifest vagy a GitHub HTTPS kapcsolat
önmagában **nem publisher hitelesítés**.

Három pontos működési mód:
- `--check`: csak ellenőriz és jelent (root nélkül is);
- `--install-inactive`: előbb root és helyi terminál,
  a pontos commit/SHA megjelenítése, a
  `INSTALL_INACTIVE_PINNED_M15H` kifejezés begépelése;
  a teljes csomagellenőrzés után a bevált M15-B pontos
  `/opt/linux-mcp-operator` telepítőjének meghívása;
- `--rollback-inactive`: root/terminál/jóváhagyás,
  **letöltés nélkül**, M15-B rögzített fájllistás,
  hashre és manifestre kötött pontos visszaállítása.

A helyileg egyszer megbízhatóan telepített scriptnek és
függőségeinek **saját eredete is ellenőrzendő**;
a távolról elérhető új scriptet nem szabad
`curl ... | sudo bash` formában végrehajtani.
Az oldalkocsi-komponensek forrásába a letöltés nem
telepít sem szolgáltatást, sem host Docker-jogosultságot.

## Tartós biztonsági szabályok

- Nincs távoli MCP eszköz, host shell, SSH-tunnel, portnyitás.
- Nincs Docker, systemd, user/group vagy approval HMAC titok.
- A telepítés **forrásfájlokat** helyez el, nem indít szolgáltatást.
- `local_admin_approval=True` belső kódargumentum
  nem helyettesíti a fizikai embert; a CLI kötelező
  `sys.stdin.isatty()` ellenőrzése csak a helyi
  operátori jelenlét egyik részbizonyítéka.
- Minden aktív service, felhasználói jelszó, rootful
  Docker socket privilege-separation és real M12 36/36
  eszköz-paritás továbbra is **NOT VERIFIED** a Pi-n.
- Az új Python eszköz nem lett az M15 oldalkocsi
  telepítendő fájllistájához adva: ez külön, egyszeri
  ellenőrzött indító; így nem keletkezik önmagára
  mutató tartalmi SHA / commit körkörös függés.
- Az archívum SHA256-ja **commitfüggő**, mert a manifest
  is tartalmazza a forráscommitot. Mindig a telepítendő
  pontos Git commit CI-kimenetének SHA-ja érvényes.

## Kvalifikáció

`tests/test_m15h_pinned_nozip_bootstrap.py`:
- canonical, csak engedélyezett fájlok és útvonalak;
- hiányzó, nem létező, túlméretes vagy módosított fájl;
- hamis SHA/branch/commit/ref, rossz mód és tiltott root;
- no network before root permission and exact local TTY;
- no filesystem installation on verify-only;
- rollback never downloads anything and forbids wrong pin;
- syntactically bad payload rejected before host writes.

`.github/workflows/m15h-nozip-inactive-bootstrap.yml`:
- natív ARM64 és x86-64 GitHub-runner;
- offline determinisztikus ZIP/tar letöltés nélküli forrás-összeállítás;
- a GitHub HTTPS-ről tényleges, csak rögzített commit szerinti
  forráslekérés és az archívum bitazonosságának ellenőrzése;
- **csak disposable CI hoston** tényleges root-owned, inactive
  M15-E-forrástelepítés, sérült csomag és rossz rollback elutasítása,
  pontos rollback, utána nincs `/opt/linux-mcp-operator` maradvány.
- a teljes `MCP updater security tests` továbbra is kötelező.

## Valós Raspberry Pi – telepítési kapu

A mai Pi MCP `v0.6.1` eszközei nem hívhatnak meg
host-installer kódot. Az `artifact_*` API inert.
Az M15-H sem ad neki ilyen jogot.

A valódi Pi-n M15-E inaktív telepítéséhez **egyszer**
szükséges egy függetlenül megbízható, helyi admin-útvonal
(helyi terminál vagy jóváhagyott, külön OS bootstrap).
Ezt nem lehet a meglévő MCP-n keresztül kijátszani.
Később a helyileg jóváhagyott installer hozhat létre
külön operátori felhasználót és szolgáltatást, de csak
a távoli M12 root/Docker/sudo/privileged socket
útvonalainak auditja és a teljes stage/sandbox migráció után.

**Nem állítjuk, hogy az M15-E telepítve van a Pi-re.**
