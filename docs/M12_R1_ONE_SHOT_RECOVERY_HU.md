# M12-R1 – Egyszeri telepítés, valódi Pi preflight kompatibilitási javítás

2026-10-31. **M12 eredeti aktiválása NEM történt meg.**
Az `admin@fieldwork` terminálban az első, pontos SHA256-ellenőrzött,
`b84e34f256b7e1dc1111c10eb10f17dd701a1680` kiadási jelölt
azonnal, a helyi jóváhagyás előtt `M12_STOP=SelfServiceOverlayDenied`
eredményt adott. Mivel nem jelent meg `M12_PREFLIGHT_PASS`, a
telepítő nem érte el a helyi jóváhagyási vagy fájlírási ágat.

## Javítási hipotézis és bizonyíték

A korábbi `mcp_self_service_overlay.py` AST-toolname auditori
ellenőrzése egyenként **egy** szövegliterál-előfordulást várt.
Az élesített v0.6.1 `fieldwork_mcp.py` a regisztrációs
listán túl külön toolname allowlistet is tartalmazhat; ez a
név AST-előfordulását kettőre növelheti. A korábbi
mesterséges CI fixture csak egy kombinált string literált
modellezett, így a hibát nem vette észre.

A javított forrástranszformáció a *három pontosan megnevezett*
új eszközhöz egységesen **egy vagy két** AST-konstans
előfordulást fogad, harmadik vagy eltérő előfordulási
mintánál továbbra is fail-closed. Az eredeti forráshash,
három pontos tool-regisztrációs anchor, hozzáadott
allowlist és a Python AST ellenőrzése változatlan.
Az új regressziós teszt mindkét érvényes alakot és
az illetéktelen harmadik/mixed előfordulást ellenőrzi.

Ez a pi-n látott hiba **valószínű magyarázata**, nem az
eredeti kivétel tényleges részletes diagnózisa, mert
az első installer sajnos csak a kivétel osztálynevét
írta ki. Az R1 telepítő már kizárólag a biztonságos
`[A-Z][A-Z0-9_]` jellegű preflight-hibakódot is
visszaadja, így a további hiba soha nem indokol
nyers forrás- vagy titokmegosztást.

## Új, lezárt, ellenőrzött kiadás

- Git commit: `0238edee95551bce65ae9770eb5a8f4e75f1a854`
- `updater/mcp_self_service_activate.py` SHA256:
  `db0bc5ddd435495f8c7b1a17575f11b1b6b786483edbb418c8a8a803473a2fae`
- A telepítő immutábilis commitból, SHA256-tal
  ellenőrzi a három forrásmodult, és csak a pontos
  Pi-n már megfigyelt két aktív MCP-forráshash
  mellett engedhet tovább.
- [Biztonsági CI #41212093143](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41212093143):
  **541 updater + 12 bootstrap = 553/553 PASS**.
- [Valódi Docker CI #41212088887](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41212088887):
  **SUCCESS**.
- Jelenlegi FieldWork Pi MCP 0.6.1 kapcsolat
  olvasható; éles `/api/health` és `/health`
  továbbra is HTTP 200; stage `STAGE_RUNNING_CHECK`.
  Nem történt éles/mcp/tunnel változtatás.

## Egyetlen helyi, SHA-pinnelt művelet

A korábbi `b84e34f256b7e1dc1111c10eb10f17dd701a1680`
parancs **ELAVULT**, többé ne fusson. A következő
egyetlen parancs a friss `0238...` forrást tölti
le, SHA256-ellenőrzés után memóriából végrehajtva.
Nincs ZIP, repo-klónozás vagy külön fájlmásolás:

```sh
python3 -c 'import hashlib,urllib.request;u="https://raw.githubusercontent.com/misssska/fieldwork-pi-mcp/0238edee95551bce65ae9770eb5a8f4e75f1a854/updater/mcp_self_service_activate.py";b=urllib.request.urlopen(u,timeout=20).read(200001);assert len(b)<=200000 and hashlib.sha256(b).hexdigest()=="db0bc5ddd435495f8c7b1a17575f11b1b6b786483edbb418c8a8a803473a2fae","M12_R1_INSTALLER_SHA256_MISMATCH";exec(compile(b,"m12_r1_pinned_installer.py","exec"),{"__name__":"__main__"})' --commit 0238edee95551bce65ae9770eb5a8f4e75f1a854 --activate
```

Csak `M12_PREFLIGHT_PASS` és teljes, csak memóriában
lezajló újforrás-ellenőrzés után jelenhet meg az
`ENGEDÉLYEZEM_M12` megerősítés, azután a meglévő
sudo jogosultság a meglévő
`fieldwork-pi-tunnel.service` egyszeri restartjához.
A `/opt/fieldwork`, production/staging DB, más Docker
projektek nem tartoznak a módosítási körbe.

Ha `M12_STOP=...` látható és
`M12_PREFLIGHT_PASS` még nem jelent meg, nem történt
fájlmódosítás; a **rövid hibakód** önmagában elég
a következő célzott GitHub-javításhoz. Ha a preflight
PASS, de később hiba van, ne próbáljuk vakon újra:
a durable receipt és rollback bizonyíték kell.

A sikeres `M12_ACTIVATED_READYZ_PASS_DISCOVERY_PENDING`
után az új három MCP-eszköz jelenlétét ChatGPT felől
külön ellenőrizzük. Ezt a kódot nem kell kézzel
beilleszteni a Pi-be, az egyetlen helyi telepítő intézi.

## 2026-10-31 – TÉNYLEGES RASPBERRY PI AKTIVÁLÁS SIKERES

A Pi tulajdonosa az előző fejezetben leírt, pontos SHA256-tal ellenőrzött
M12-R1 telepítőt **helyileg lefuttatta és jóváhagyta**. A visszaküldött
hiteles, lokális parancskimenet:

```text
M12_PREFLIGHT_PASS
OLD_MCP_SHA256=e0e7cfb7b70c7f79845337b84bb47025beaad6d429377b64d1972db68c3fbc1a
NEW_MCP_SHA256=ee218971079b988e1e85b3790dd50228847e5e911e2e688b3df77972ad78b532
NEW_SANDBOX_SHA256=5a4a6ba775f7fd16d0660a654eb3ab8724659ff1ac72fd1427ed3c9eadb797f5
SCOPE=MCP_SOURCE_AND_SANDBOX_ONLY_PRODUCTION_UNTOUCHED
M12_ACTIVATED_READYZ_PASS_DISCOVERY_PENDING
```

**Helyileg sikerült** a két forrásfájl cseréje, az egy új olvasási
modul telepítése, a meglévő tunnel restart és a lokális readyz.
A helyi aktiválási ágon a felhasználó explicit
`ENGEDÉLYEZEM_M12` jóváhagyást adott. Az aktív install
fájlbájtjait a ChatGPT innen még nem olvasta vissza az új MCP toolokkal:
az alábbi discovery kapu ettől különbözik.

**ChatGPT oldali csatlakozás ellenőrizve:** a régi FieldWork MCP eszközök
működnek (`fieldwork_status` válasz, verzió 0.6.1);
éles `/api/health` és `/health` HTTP 200; stage
`STAGE_HEALTH_PASS`, a meglévő stage running check megtörtént.
Az **új három eszköz** viszont az ebben a beszélgetésben
elérhető Tool Directoryban **még nem jelent meg**:
`fieldwork_mcp_source_inventory`,
`fieldwork_mcp_source_review`,
`fieldwork_mcp_docker_inventory`. A meglévő lista 33 eszközt tartalmaz.

**M12 release két külön státusz:**
- `LOCAL_PI_ACTIVATION=PASS` a helyi install nyugtája alapján.
- `CHATGPT_NEW_TOOL_DISCOVERY=PENDING`, nem PASS.
- `PRODUCTION_API_HEALTH=PASS`,
  `STAGING_HEALTH=PASS`, régi MCP toolhívások működnek.
- `M11_HISTORICAL_CLEANUP_RECEIPT` marad a korábbi sikertelen
  nyugta; nem íródott át.

**Következő művelet:** indítsunk új ChatGPT beszélgetést,
amelyben a csatlakoztatott FieldWork Pi MCP plugin eszközlistája
újra felfedezhető, vagy frissítsük a ChatGPT plugin-kapcsolatot
az alkalmazás felületén (csak ha van tényleges frissítés opció).
A plugin eltávolítása, új tunnel létrehozása vagy újabb
SSH-installer futtatása **nem indokolt**.

Az első új MCP eszközfelfedezés után sorban
`fieldwork_mcp_source_inventory` és
`fieldwork_mcp_docker_inventory` csak olvasási smoke,
majd `fieldwork_mcp_source_review` az ellenőrzött
cleanup-függvényre. Tilos az éles FieldWork vagy Docker
módosítása felfedezési teszt címén.
