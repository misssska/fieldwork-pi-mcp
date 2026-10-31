# M15-E – külön Linux UID-k közötti HMAC-jóváhagyás egyszeri beváltása

**2026-10-31. Draft PR / GitHub disposable teszt. NINCS telepítve a Raspberry Pi-re vagy Orange Pi-re.**

## Mit old meg?

Az M14 `linux_upgrade_local_handoff.py` kísérleti belépője
a végrehajtótól is elvárta a helyi HMAC-aláíró titok ismeretét.
Ez **nem megfelelő OS-különválasztás**, ha később a végrehajtó
Dockerhez vagy más privilegizált segédhez hozzáférhet.

Az `updater/linux_approval_redeemer.py` az M15-E következő,
szűk tesztelt **átadási építőeleme**:

1. A külön operator-UID által birtokolt `0700` ticket- és `0700`
   spent-könyvtárakba a külön executor-UID nem léphet be.
2. Az operator-UID saját csoportjával létrehozott helyi AF_UNIX
   socketnek `0660` a jogosultsága; a tartalmazó könyvtár `0710`.
3. A szerver `SO_PEERCRED` útján a **kernel által közölt** kliens-UID-t
   ellenőrzi, nem az ügyfél által közölt azonosítót.
4. A kliens legfeljebb 256 bájtos, kanonikus, egyetlen kérést küldhet,
   amely csak a `protocol=1` és az **előre helyben rögzített**
   `plan_sha256` értékeket tartalmazhatja.
5. Az operátori kulcs és az aláírt jegy nem kerül át a kliensnek.
   A szerver `gate.verify_local_approval` segítségével
   ellenőrzi a pontos host/terv/lejárat/HMAC egyezést.
6. A 128 bites nonce-t csak új (`O_CREAT|O_EXCL`) `0600`
   fájlként, `fsync` után jelöli tartósan felhasználtnak.
   Csak ezután küldhet pozitív választ. Újraindításkor ugyanaz
   a nonce **nem** fogadható el, részleges írásnál fail-closed.
7. A válasz `LOCAL_APPROVAL_REDEEMED_NOT_EXECUTED`:
   **nem telepítés, nem publisher-ellenőrzés és nem jogosultság
   a Dockerhez vagy a produkciós fájlokhoz**.

## Mi nincs benne?

- Nincs távolról meghívható MCP-endpoint vagy LAN/telefonos listener.
- Nincs Docker API, host shell, tetszőleges parancs, forrásfájlírás,
  service-restart, release-telepítés vagy reboot.
- Nincs Pi telepítő, és az M15 csomag allowlistje **nem változott**.
- A külön UID csak akkor valódi bizalmi határ, ha az éles M12
  nem root, nincs közvetlen Docker-root joga és más bypass sem.
  Ez Pi-n továbbra is **NOT VERIFIED**.
- A próba szintetikus local approvalt használ. Nem helyettesíti
  a tényleges felhasználói jelenlétet, a pontos release publisher
  aláírást, sem a végrehajtási visszaállítást.
- Az egyszer használatos protokoll tudatosan egyszeri kapcsolatot
  fogad; a socketet rendellenes kilépés után nem törli automatikusan.
  Az újraindításhoz helyi állapotegyeztetés kell. Ez még nem
  üzemszerűen skálázott hosszú életű daemon.

## Biztonsági és platform-elfogadás

- `tests/test_linux_approval_redeemer.py`: direkt negatív tesztek
  hamis HMAC, rossz terv/SHA, lejárat, replay, duplikált JSON-mező,
  idegen Unix peer, rossz fájljogosultság, symlink, két listener,
  nyitott port nélküli helyi socket esetére.
- `tests/native_m15e_peer_acceptance.py`: *csak disposable GitHub
  runneren* két **valóban külön Linux UID** és külön executor-csoport.
  Native `setpriv` közvetlen folyamatfuttatás, operátori kulcs
  olvasásának tiltása a végrehajtó UID alatt, valódi AF_UNIX
  `SO_PEERCRED` elfogadás, tartós nonce replay tagadása,
  más UID elutasítása. Csak szintetikus tesztjegy.
- `.github/workflows/m15e-native-approval-ipc.yml`: natív
  `ubuntu-24.04` és `ubuntu-24.04-arm` CI; külön accountok
  csak disposable Github runneren, nem a Pi-n.

## Hátralévő kritikus mérnöki kapuk

**P0:** a real Pi M12 MCP tényleges UID/GID/Docker/sudo/socket/FD
felmérése független helyi auditorral; a Docker-socket root-ekvivalens
hozzáférés megszüntetése működésvesztés nélkül.

**P1:** külső publisher signature és immutábilis release, aktív
M12 source SHA és 36/36 regresszió, kizárólag engedélyezett
stage/sandbox lifecycle-műveletek elkülönített segéddel, atomic
service restart + health + rollback.

**P2:** hosszú életű, systemd/alternatív Linux supervisor adapter,
helyi emberi jóváhagyás, biztonságos mobil TLS/auth, no-copy
GitHub→Pi folyamat.

A PR marad DRAFT; a Pi /opt/fieldwork, DB, Docker, tunnel és
meglévő MCP szolgáltatás változatlan.
