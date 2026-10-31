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
