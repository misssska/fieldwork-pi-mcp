# Schemafix-r1 eredetazonosítás és lifecycle kompatibilitás – 2026-10-30

**Érdemi új bizonyíték:** a korábban eltérőnek nevezett
`7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04`
SHA-256 nem ismeretlen forrás: bájtra azonos a korábban átadott
`FieldWork-Pi-MCP-v0.6.1-Schemafix-r1.zip` csomag
`fieldwork-pi-mcp-v0.6.1-schemafix-r1/fieldwork_mcp.py` fájljával.

## Eredeti kiadási csomagok – valódi helyi bájtellenőrzés

A megőrzött, eredeti ZIP-ekből olvasva, **nem a Raspberry Pi-n**:

| Kiadási csomag | ZIP SHA-256 | Belső MCP-fájl SHA-256 |
| --- | --- | --- |
| v0.6.1 Stage Final | `f9e37d95bfdf7db758820a41c9845d8c4814c2684980a30a601c9936a2e0e10e` | `b504460dc1477898dc048dc990e7fd432ba880926f9f063904cd6a9b085e5948` |
| v0.6.1 Schemafix-r1 | `c68a9b9db51fb78519a0fc88517a8d365e0ce2de2a8a3cba97b56b3d9a2f57dd` | `7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04` |
| Async Stage-r2 | `2fe295987c72524bb1a2eada6d6c65425c86fe0b6309bce5b4c5e0c3e573c197` | `5729060acf8b833523921954f232558db5c853aa87fb366e7f4c1488cd38f33f` |

A két v0.6.1 `fieldwork_mcp.py` forrás közötti **egyetlen diff-hunk**
az MCP `tools/list` `required` mezőjének összeállítását módosítja:
a `fieldwork_sandbox_runtime_test` eszköz `suite`, illetve a
`fieldwork_sandbox_command` eszköz `command` és `with_test_db`
paramétereit kifejezetten kötelezőként sorolja fel, a hibás összetett
feltétel helyett. A teljes fájl különbsége pontosan ez a változtatás.

## Offline lifecycle-kompatibilitási eredmény

A GitHub által publikált `updater/async_overlay.py` transzformáció
egyedi, szigorú anchorain végrehajtott ellenőrzés:

1. Eredeti v0.6.1 + Async Stage overlay = `5729060a...`,
   **bájtra azonos** az Async Stage-r2 csomag főfájljával.
2. Schemafix-r1 főfájl + Async Stage overlay + lifecycle overlay:
   szintaktikailag érvényes Python-fájl.
3. A kapott jelölt SHA-256:
   `b9d449ba2802b2f13e8e09252cdcf593007f3aeadfebe06010fa01ac2f5a62a5`.
4. A Schemafix-r1 kötelező-paraméter javítása a jelöltben megmaradt.
5. Az öt új staging MCP-eszköz sztringje szerepel a statikus jelöltben.

A `updater/schemafix_lineage.py` az eredeti bájtok pontos
hash-egyezését, az egyetlen ismert módosítás kizárólagosságát és
a két overlay teljes eredményét ellenőrzi. Nem telepít, nem indít
szolgáltatást, nem fogad el tetszőleges installálási útvonalat.

**Fontos:** a ZIP-ek lokális egyezése és a szintaktikai alkalmasság
NEM bizonyítja a Raspberry Pi **jelenlegi** forrásfájljának azonosságát,
a teljes függőség-/futásidejű kompatibilitást vagy a telepítési biztonságot.
A korábbi Pi-mérés egy kiadási artifactumhoz köthető, de a Pi-t most
újra kell attestálni.

## Reprodukció: csak olvasási offline összevetés

A három pontosan fenti nevű ZIP-et egy önálló vizsgálati könyvtárba
helyezve, a repó ellenőrzött checkoutjából:

```python
from pathlib import Path
from zipfile import ZipFile
from updater.schemafix_lineage import audit, sha

p = Path('release-artifacts')
names = {
    'FieldWork-Pi-MCP-v0.6.1-Stage-Final.zip': (
        'f9e37d95bfdf7db758820a41c9845d8c4814c2684980a30a601c9936a2e0e10e',
        'fieldwork-pi-mcp-v0.6.1/fieldwork_mcp.py'),
    'FieldWork-Pi-MCP-v0.6.1-Schemafix-r1.zip': (
        'c68a9b9db51fb78519a0fc88517a8d365e0ce2de2a8a3cba97b56b3d9a2f57dd',
        'fieldwork-pi-mcp-v0.6.1-schemafix-r1/fieldwork_mcp.py'),
    'FieldWork-Pi-MCP-Async-Stage-r2.zip': (
        '2fe295987c72524bb1a2eada6d6c65425c86fe0b6309bce5b4c5e0c3e573c197',
        'fieldwork_mcp.py'),
}
data = []
for filename, (digest, internal) in names.items():
    raw = (p / filename).read_bytes()
    assert sha(raw) == digest
    with ZipFile(p / filename) as archive:
        data.append(archive.read(internal))
print(audit(base=data[0], schemafix=data[1], async_r2=data[2]))
```

A GitHub CI a `test_schemafix_lineage.py` elutasítási
és szintetikus pozitív eseteit ellenőrzi. Az eredeti ZIP-eket
**nem** töltjük fel a publikus repóba; ezért a CI nem állíthatja, hogy
az eredeti ZIP-eket is végigellenőrizte.

## Aktiválási kapu

A telepített forrás friss, helyi SHA-256-ja, a helyi approval issuer,
a teljes ARM64 regresszió és valódi systemd/MCP/tunnel readiness
továbbra is szükséges. Az állapot kizárólag
`OFFLINE_SCHEMAFIX_LINEAGE_PASS`, amely
`activation_authorized=false`, `mcp_modified=false` és
`production_modified=false` eredményt ad.

Nincs új tunnel, production deploy vagy automatikus MCP-fájlcsere.
