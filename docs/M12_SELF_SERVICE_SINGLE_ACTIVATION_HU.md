# M12 – Egyszeri FieldWork MCP önkiszolgáló bővítés

**Kiadási jelölt:** commit `b84e34f256b7e1dc1111c10eb10f17dd701a1680`.
**Állapot:** GitHub CI PASS, a Raspberry Pi-n még **NINCS** telepítve.
Az aktív MCP 0.6.1 változatlan, az éles /opt/fieldwork, PostgreSQL,
a többi Compose-projekt és a tunnel nem változott.

## Cél

A felhasználónak **ne kelljen minden új MCP hibakereséshez
kézzel SSH-/Python-parancsokat másolni**. A meglévő
FieldWork Pi MCP három pontosan megnevezett, olvasási képességet
kap, és a tesztkonténer-eltakarítás M11 javítása is aktiválható
egyszeri helyi engedéllyel.

### Új MCP eszközök, a telepítés + eszközlista-felfedezés után

- `fieldwork_mcp_source_inventory`: a telepített MCP allowlist
  fájljainak SHA256, top-level függvénynevei és állapota.
- `fieldwork_mcp_source_review`: egy pontosan megadott allowlist
  modul/funkció **AST-ja** értékliterálok kitakarásával;
  a forráskódot nem importálja, nem hajtja végre.
- `fieldwork_mcp_docker_inventory`: read-only,
  `/usr/bin/docker --host unix:///var/run/docker.sock container ls
  --all --no-trunc --format '{{json .}}'`,
  tíz másodperces felső korláttal, kimeneti méretlimittel,
  csak korlátozott mezőkkel. Nincs egyetlen Docker mutáció sem.
- A korábbi `fieldwork_sandbox_command` megmarad, az M11
  célzott test-container `cleanup` ellenőrző ágával. A
  tesztkonténer eltűnését két külön, sikeres, pontos
  konténernévre szűrt Docker-lekérdezés igazolja. Bármilyen
  hiba vagy maradó konténer esetén FAIL; a történelmi nyugta
  nem lesz megváltoztatva.

Ez a bővítés **nem** biztosít raw host shellt, automatikus
plugin-/tunnel-újratelepítést vagy korlátlan Docker-hozzáférést.

## Biztonsági határ

A telepítő csak a felhasználó saját
`~/.local/share/fieldwork-pi-mcp/v0.6.1` könyvtárában:

1. lecseréli a forráshash-sel rögzített
   `fieldwork_mcp.py` fájlt (eredeti SHA256:
   `e0e7cfb7b70c7f79845337b84bb47025beaad6d429377b64d1972db68c3fbc1a`),
2. lecseréli az eredeti
   `sandbox_command.py` fájlt (SHA256:
   `5255968dac5c0bb8ac3a94eb72f3131ea2081b683974d97db6bb9ddc3d432615`),
3. létrehozza a kizárólag olvasási
   `mcp_self_diagnostics.py` modult.

A változás teljes egészében távoli, 40-hex Git commit SHA
és **három tartalmi SHA256** ellenőrzéssel védett.
A commitból letöltött két patch-modul csak sikeres hash- és
AST-vizsgálat után használható. A source-patch a megfelelő
régi forráshash és egyértelmű AST/forráshorgony hiányában
FAIL-closed állapotba lép, még a jóváhagyás előtt.

Előbb a teljes új MCP-forrást memóriában állítja elő,
Python AST-t és fordíthatóságot ellenőriz.
**Csak sikeres preflight után** kér egyetlen, helyi
`ENGEDÉLYEZEM_M12` megerősítést, illetve a már
létező systemd-szolgáltatás újraindításához sudo-jogot.
Az éles FieldWork fájljait és az éles Dockert nem
indítja újra és nem módosítja.

A meglévő
`fieldwork-pi-tunnel.service` egyszeri újraindítása
szükséges az új MCP-eszközlista betöltéséhez. Új tunnel
nem jön létre. Külön állományba 0600 módban menti
mindkét régi MCP-forrást, új fájlokat atomikusan ír,
és `/readyz` hibánál megkísérli az automatikus rollbacket.
A nyugta `M12_READY_TOOL_DISCOVERY_PENDING` állapota
**nem egyenlő** a ChatGPT eszközfelfedezésének PASS-jával.
Bármely blokkolás esetén a futtatást nem szabad
blind módon ismételni.

## Tesztbizonyíték

- Unit + contract, Python 3.11 szintaxis: GitHub
  [#41211089279](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41211089279):
  **535 updater + 12 bootstrap = 547/547 PASS**.
- Valódi Docker-host CI:
  [#41211151194](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41211151194):
  **SUCCESS** az új `mcp_self_diagnostics.docker_inventory`
  tényleges Docker-lekérdezésére, a tesztkonténer
  változatlan állapotának igazolásával.
- M11 korábbi Docker-runtime CI:
  [#41209753853](https://github.com/misssska/fieldwork-pi-mcp/actions/runs/41209753853):
  **SUCCESS**, a Docker `--rm` versenyhelyzet,
  sikertelen `rm -f` és lekérdezési hiba tesztekkel.
- Külön 12 negatív egységteszt: lokális aktiválás
  engedély megtagadása, symlinkek és jogosultságok
  elutasítása, sikertelen újraindításkor a két eredeti
  bájtsorozat visszaállítása és az új modul eltávolítása.

**Korlát:** GitHubon a valódi aktív Pi MCP-forrásbájtok
nem hozzáférhetők. A telepítő az aktuális Pi-n
a fent rögzített, felhasználó által SHA-ellenőrzött
telepített forrást hash alapján ellenőrzi, és csak
egyezés esetén írja át.

## Egyetlen egyszeri helyi parancs

A felhasználó az `admin@fieldwork` terminálban
egyszer futtathatja. A parancs magát a telepítőt
csak egy pontos GitHub-commitból, HTTPS-en memóriába
olvassa, a megadott SHA256-tal ellenőrzi, és csak
akkor futtatja. Nem kell ZIP-et, külön modult vagy
repo-klónt letölteni.

```sh
python3 -c 'import hashlib,urllib.request;u="https://raw.githubusercontent.com/misssska/fieldwork-pi-mcp/b84e34f256b7e1dc1111c10eb10f17dd701a1680/updater/mcp_self_service_activate.py";b=urllib.request.urlopen(u,timeout=20).read(200001);assert len(b)<=200000 and hashlib.sha256(b).hexdigest()=="d29474a46a4f9ac482b7b587af52b17f7093a19bcaf272ec523882041a8a804b","M12_INSTALLER_SHA256_MISMATCH";exec(compile(b,"m12_pinned_installer.py","exec"),{"__name__":"__main__"})' --commit b84e34f256b7e1dc1111c10eb10f17dd701a1680 --activate
```

A következő szöveg az egyetlen helyi jóváhagyási
visszakérdezés: `ENGEDÉLYEZEM_M12`.
A meglévő sudo-jogosultság megerősítésére egyszer
szükség lehet.

A sikeres kimenet:
`M12_PREFLIGHT_PASS` majd
`M12_ACTIVATED_READYZ_PASS_DISCOVERY_PENDING`.
Ezután a ChatGPT-ben az új három MCP-eszköz
discoveryjét külön ellenőrizni kell; ha a kliens
még régi listát lát, lehet, hogy connector refresh
szükséges. A felhasználó nem futtat
minden új hibakeresésnél kézzel parancsokat.

**Ez nem jogosít később automatikus éles telepítésre,
adatbázis- vagy host-módosításra.**
