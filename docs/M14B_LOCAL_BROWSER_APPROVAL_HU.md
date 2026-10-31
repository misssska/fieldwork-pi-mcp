# M14-B – Helyi böngészős jóváhagyás és biztonságos telepítő-kapcsolat

Dátum: 2026-10-31. **Offline fejlesztői elfogadási kapu: PASS.**
**Raspberry Pi / Orange Pi aktiválás: NEM TÖRTÉNT MEG.**

## Mi készült el?

A korábbi M14-kérelem, HMAC és visszaállítható helyi
fájltranzakció közé elkészült az operátori jóváhagyás
helyi webes felülete és az elkülönített, aláírt átadás.

- `updater/linux_upgrade_review_ui.py`:
  beépített Python HTTP-szerver, kizárólag
  `127.0.0.1` (IPv4 loopback) felületre bindelhető;
  egyetlen, helyi policy által előre kiválasztott
  frissítési tervet mutat: gépazonosító, Git commit,
  teljes terv SHA256, módosítandó MCP-modulok és
  a cél SHA-k. Áttekinthető magyar HTML/CSS képernyő.
  **Nincs külső JavaScript, CDN, betöltött kép vagy font.**
  Két valódi művelet: jóváhagyás és elutasítás.
- Az operátori `POST /decision` egy szigorú,
  legfeljebb 1024 bájtos HTML-form: exact Host, Origin,
  Sec-Fetch-Site, CSRF és tervlenyomat ellenőrzés.
  `Content-Security-Policy`, `X-Frame-Options: DENY`,
  `Cache-Control: no-store`, `Referrer-Policy`.
  Dupla döntés és ismételt aláírás fail-closed.
  A napló nem írja ki a rejtett formmezőket.
- A tényleges helyi gombnyomás hatására az izolált,
  titkos kulccsal készült rövid élettartamú,
  géphez/tervhez kötött HMAC-jóváhagyás
  0600/0700, atomikus, no-overwrite átadó
  könyvtárba kerül. Az API-válasz a MAC-et, kulcsot
  és nonce-t nem tartalmazza. A weboldal
  **nem futtat telepítést**.
- `updater/linux_upgrade_local_handoff.py`:
  kizárólag helyi processzből hívható összekötő.
  Egy teljes, konkrét terv SHA-járól olvas
  0600 nyugtát, `O_NOFOLLOW`, megengedett fájlnév,
  korlátozott méret és canonical JSON vizsgálattal,
  majd a gépazonosítót és a HMAC-et ellenőrzi.
  Az OS-szinten elkülönített (később telepítendő)
  végrehajtóhoz tartozó `linux_upgrade_local_transaction`
  a nyugtát egy alkalommal használhatja
  pontos forráshash- és Python-AST-check után.
  A teszt éles szolgáltatást nem indít újra.
- Az előző M14 `linux_upgrade_gate.py`,
  `linux_upgrade_inbox.py`,
  `linux_upgrade_local_transaction.py` változatlan
  protokollon alapul. Az M12 és M13 telemetria
  külön modulok, semmi sem kerül automatikusan
  a Pi meglévő, 36 eszközös MCP-regisztrációjába.

### Mit validáltunk?

A [teljes GitHub CI](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41220887770)
**665 updater + 12 bootstrap = 677/677 PASS**.

A [natív ARM64 + x86-64 CI](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41220883514)
mindkét Linux architektúrán **SUCCESS**.
A tesztek valós helyi `127.0.0.1` HTTP-t és
valós ideiglenes fájlrendszer-írásokat használnak,
de nem a Pi-ken futnak.

Negatív elfogadások: idegen Origin/Host,
DNS rebinding, hibás CSRF, clickjacking-védelem,
form-injection, elutasított vagy ismételt döntés,
másik host approval, hibás/tamperelt HMAC,
lejárt terv, eltérő modul SHA,
symlink/csoportosan olvasható nyugta,
sikertelen egészségellenőrzés miatti rollback,
és hivatkozott, nem jóváhagyott idegen fájl
változtatásának megtagadása.

A legfontosabb `BrowserToLocalInstallerIntegration`
teszt **valóban végigmegy** az aláírt
kérelmen, a helyi átadáson, az engedélyezett
modulok változtatásán és a rollbacken.
A teszt **nem** téveszthető össze a valódi
Raspberry Pi MCP-frissítéssel.

## Biztonsági korlát – még nem release-ready

1. A Python webszerver **csak loopbacken** hallgat.
   Telefonról közvetlen LAN-címen és nyilvános
   HTTP-porton **nem** elérhető, szándékosan.
   A mobilos eléréshez külön hitelesített
   proxy/VPN, CSRF és session biztonság,
   device pairing és erős hozzáférés-szabályozás
   szükséges. Nincs kész.
2. A helyi böngészőgomb és a HMAC-kiadó
   az offline prototípusban egy processzben fut.
   Ez **nem bizonyítja**, hogy a helyi operátor
   megbízható és fizikailag jelen van:
   a külön OS-felhasználó, hitelesített
   operátori login és védett kulcstároló
   továbbra is kötelező release-gate.
   A loopback önmagában nem auth.
3. Az ügyfél által készített commit+SHA
   **csak azonosságot**, nem forrásbiztonságot
   bizonyít. A telepítő előtt független
   release-hitelesítés, rögzített publisher,
   forrásdiff-áttekintés és releváns CI PASS
   követelmény. Az UI jelenleg nem mutat
   bizonyított, független forrásdiffet.
4. Az offline local transaction a
   `health_check` függvényt paraméterként
   kapja. A Pi/Orange Pi célrendszer
   konkrét service restart, várakozási idő,
   health és rollback-konfigurációja még
   nincs telepített és natívan elfogadott
   állapotban.
5. A távoli inbox és a helyi UI közötti,
   OS-biztonsági tartományokat is átlépő
   **hitelesített, csak egyirányú IPC**
   még nincs megvalósítva. Minden beérkező
   frissítést a helyi oldalon újra validálni kell.
   A helyi HMAC-titok soha nem kerülhet
   a távoli MCP-t működtető Unix-felhasználóhoz.
6. A működő FieldWork Pi MCP,
   `fieldwork-pi-tunnel.service`,
   `/opt/fieldwork`, a staging és a
   Docker-konténerek **nem módosultak**.
   A PR továbbra is draft.

## Következő, valóban hasznos mérföldkő

Nem újabb ZIP-eket vagy parancsokat akarunk.
Egyetlen, egyszer telepítendő, önálló
`linux-mcp-updater` rendszerszolgáltatás kell:

- gépenként saját, nem az MCP-felhasználóhoz
  tartozó local approver identity, secret és policy;
- read-only remote proposal intake, no raw shell,
  explicit reviewer UI/telefonos MFA és rövid
  lejáratú, tervhez kötött helyi döntés;
- megbízható, külön processzbeli executor,
  szigorúan verziózott bináris/forráscsomag,
  exact trusted publisher és host policy,
  health/rollback, távoli státusz
  **a jóváhagyástól külön**;
- a működő M12 átalakítása regresszió nélkül,
  csak egyszeri lokális bootstrap után.
  Az aktív Pi nem képes ezt jelenleg önmagán
  unattended módon bekapcsolni.

**Elfogadási feltétel:** a későbbi M15+ frissítés
ne kérjen újabb SSH-parancsmásolást,
ne függjön a konkrét Pi disztribúciójától,
és operátori elfogadás nélkül soha ne
állítsa, hogy telepítés történt.
