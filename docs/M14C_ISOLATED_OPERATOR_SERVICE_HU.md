# M14-C – Helyi Linux MCP jóváhagyó szolgáltatás és jogosultsági kapu

2026-10-31. **Fejlesztői tesztek PASS; NINCS telepítve a Raspberry Pi-re vagy az Orange Pi-re.**

A cél változatlan: a későbbi frissítésekhez ne kelljen ZIP-eket
letölteni, forráskódot/parancsot másolni, SSH-n kézzel
szerkeszteni vagy újabb tunnelt telepíteni. A felhasználó
csak a *konkrét, ellenőrzött* frissítés helyi jóváhagyását
adja meg.

## Megvalósított források

- `updater/linux_upgrade_review_ui.py`: korábban meglevő
  localhost-only, CSRF/Origin/Host-ellenőrzött HTTP UI.
  M14-C-ben **külön legalább 32 bájtos operátori
  hitelesítéssel** bővítve: Basic auth szükséges már
  a jóváhagyási terv/CSRF oldalának megtekintéséhez is.
  A hitelesítő token nem lehet azonos a HMAC aláíró
  kulccsal. A HTTP Basic kizárólag **loopbacken**
  használható; LAN/telefon felé TLS és autentikált
  közvetítő nélkül NEM vezethető ki.
- `updater/linux_upgrade_operator_app.py`: külön,
  nem root Unix felhasználóként indítható helyi
  jóváhagyó alkalmazás. Nem fogad tetszőleges
  parancsot, fájlelérési útvonalat, portot vagy
  modulnevet a webes felhasználótól. Privát 0700
  állapotkönyvtárból olvas:
  `config.json`, `request.json`,
  `approval_hmac.key`, `operator_token.key`,
  mind 0600 és az operátor tulajdonában.
  Az engedélyezett, egygépes manifestet a
  `linux_upgrade_gate` újraellenőrzi,
  és külön `approved/` könyvtárba állít elő
  egy rövid életű, SHA-val és HMAC-kal kötött
  jóváhagyási jegyet. **Kódot nem telepít,
  systemd-t nem indít újra.**
- `deploy/systemd/linux-mcp-operator.service`:
  csak **referenciaegység**, kézi/automatikus
  telepítés nélkül. Saját `linux-mcp-operator`
  fiók, `NoNewPrivileges`, üres Linux
  capability halmaz, `ProtectSystem=strict`,
  privát állapotkönyvtár, `IPAddressDeny=any`
  és `IPAddressAllow=localhost`.
  Nincs Docker-socket mount, általános host shell
  vagy deploy művelet. A systemd-egység
  csak olyan gépen alkalmazható, ahol a
  telepítési környezet és a szolgáltatásbeállítások
  ténylegesen ellenőrizve lettek.
- `updater/linux_upgrade_trust_gate.py`:
  csak olvasási, fail-closed preflight.
  Megvizsgálja, hogy a távolról meghívható MCP
  saját felhasználója root-e, illetve hozzáfér-e
  írásra a Docker sockethez. Ha igen, az
  operátori kulcsok Unix-felhasználók közötti
  elkülönítése **nem tekinthető biztonságosnak**.
  A többi lehetséges privilégium (sudo, másik
  Docker endpoint, Podman, privilegizált local
  helper) független vizsgálata hiányában sem
  állítható általános PASS. A gate helyesen
  `PRIVILEGE_ISOLATION_BLOCKED` eredményt ad
  bizonyíték hiányában.
- `tests/test_linux_upgrade_trust_gate.py`,
  `tests/test_linux_upgrade_operator_app.py`,
  `tests/test_linux_upgrade_systemd_unit.py`;
  valamint a korábbi Browser UI és handoff
  tesztek hitelesített felülettel frissítve.

## Új, fontos biztonsági felismerés

Az aktív Pi MCP a valós Raspberry Pi-n képes
`docker container ls` parancsot végrehajtani a
Docker Unix socketen keresztül. Ez önmagában
nem bizonyítja, hogy a saját folyamatának
tetszőleges írási Docker API-jogosultsága van,
de *szokványos rootful Docker-telepítésben*
a socket használója host-root ekvivalens
képességhez juthat. **Ez kritikus kockázat.**

Ezért nincs biztonságosnak nyilvánítva a
„külön operátori Unix-user + külön secret”
felépítés addig, amíg az MCP tényleges
Docker-socket/sudo hozzáférését helyi,
független policy-audit nem tisztázta,
és a távolról vezérelhető MCP nem veszítette
el a root-ekvivalens jogosultságokat.

A helyes célrendszer:

```text
ChatGPT
  -> nem privilegizált Linux MCP (külön identity)
      -> csak olvasási / korlátozott Docker diagnosztikai proxy
      -> csak SHA-pinnelt frissítési kérelem (NINCS approve)
  -> hitelesített, elkülönített operator-UI
      -> csak konkrét tervhez kötött HMAC aláírás
  -> szűk jogosultságú local executor
      -> csak előre allowlistelt MCP-modulok
      -> source publisher trust + backup/health/rollback
```

A jelenlegi FieldWork M12 által nyújtott
`fieldwork_stage_*` műveletekhez is saját,
szigorúan project-scope-olt privilegizált
local helper kell majd; nem szabad egyszerűen
megvonni a Dockerhez való hozzáférést
a működő staging funkciók regressziójával.

## Elfogadási bizonyíték és pontos határ

- Teljes biztonsági teszt:
  [GitHub CI #41222278408](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41222278408):
  **692 updater + 12 bootstrap = 704/704 PASS**.
- Platformteszt:
  [M14 native ARM64 + x86_64 CI #41222273127](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41222273127):
  **mindkét platform SUCCESS**.
- A kódvizsgálat elutasítja a root-futást,
  az azonos operator/MCP uid-t, hibás
  operátori fájlmódot, idegen hostot,
  hibás SHA-t, hamis és hiányzó webes
  autentikációt, más portot, szimbolikus
  linket, extra fájl-/parancsmezőt.
- Valós Pi/Orange Pi user/service
  előkészítés, jogosultsági audit,
  titokátadás, systemd native smoke,
  hosszú távú update/rollback,
  HTTPS telefonos elérés: **NOT RUN**.
- M13 CPU/RAM mérés továbbra sincs
  a Raspberry Pi-n aktiválva.
- M12 telepített főfájl hash:
  `ee218971079b988e1e85b3790dd50228847e5e911e2e688b3df77972ad78b532`;
  a GitHub fejlesztés **nem módosította**.

## Következő, önálló mérföldkő: privilege-separated upgrade bootstrap

1. A jelenlegi Pi MCP jogosultsági auditja
   **csak olvasási** bizonyítékokkal; a
   Docker-socketet és az éles FieldWorköt
   nem piszkáljuk audit címén.
2. Külön, korlátozott Docker diagnosztikai
   proxy / stage lifecycle helper bevezetése,
   negatív tesztekkel és fokozatos átállítással.
   Csak akkor távolítjuk el a közvetlen
   socket hozzáférést, ha a meglévő M12
   ellenőrzések regresszió nélkül működnek.
3. Külön, helyileg jóváhagyott operator
   szolgáltatás telepítése és újraindítás /
   health / rollback elfogadása valós Pi-n.
4. Teljes frissítési kérelem ChatGPT-ből,
   önmagának jóváhagyás nélküli teszt,
   operátori döntés, végrehajtás és
   közvetlen MCP-discovery ellenőrzés;
   később Orange Pi-n külön is.
5. **Minden későbbi frissítés
   kézi SSH-parancsmásolás nélkül.**

Ez a dokumentum nem engedélyez
automatikus éles telepítést vagy
az M12 tunnel újrapéldányosítását.
