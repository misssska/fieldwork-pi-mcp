# Ellenőrzött helyi vizsgálatok — 2026-10-30

## Forráscsomagok

A ChatGPT munkakörnyezetében elérhető, korábban átadott ZIP-ekből olvasva:

- `FieldWork-Pi-MCP-v0.6.1-Stage-Final.zip` SHA-256: `f9e37d95bfdf7db758820a41c9845d8c4814c2684980a30a601c9936a2e0e10e`
- `FieldWork-Pi-MCP-Async-Stage-r2.zip` SHA-256: `2fe295987c72524bb1a2eada6d6c65425c86fe0b6309bce5b4c5e0c3e573c197`

A v0.6.1 ZIP `fieldwork_mcp.py` SHA-256 értéke `b504460dc1477898dc048dc990e7fd432ba880926f9f063904cd6a9b085e5948`.

Az r2 ZIP `fieldwork_mcp.py` SHA-256 értéke `5729060acf8b833523921954f232558db5c853aa87fb366e7f4c1488cd38f33f`.

A Pi telepítési naplójából közölt aktuális SHA-256: `7d24bcfabdbfb7fd0c4693fdaaaba678d757f46cab86ebe83151b96b77991a04`.

**Következtetés:** a telepített Pi-forrás nem azonos a v0.6.1 ZIP alapfájljával. A különbség oka és tartalma még nem ismert. A hash-ellenőrzés feloldása vagy a teljes fájl cseréje nem engedélyezhető forrásösszevetés nélkül.

## Reprodukálható offline teszt

A v0.6.1 ZIP fájljai és az r2 ZIP fájljai egy **külön helyi munkakönyvtárba** lettek kibontva; az r2-ben hiányzó függőségekhez a v0.6.1 csomag szolgált alapként.

Parancs:

```bash
python -m unittest discover -s tests -v
```

Eredmény: **71 teszt, OK**, 1.162 másodperc. Az r2 ZIP önmagában nem önálló futtatási csomag: a hiányzó `stage_manager.py` és más függőségek miatt önmagában futtatva 14 importhibát adott. A 71 sikeres teszt csak a fenti összeállított, helyi tesztkörnyezetre vonatkozik.

**Nem igazolja:** a Pi-n telepített, módosult forrás kompatibilitását, a helyi Docker-stage integrációt, az MCP-alagút újraindulását vagy a GitHub Actions sikerét.

## Biztonsági döntés

A Pi-n nincs végrehajtva telepítés. Az éles `/opt/fieldwork` és a tunnel változatlan. Következő kapu: a tényleges Pi MCP-forrás megbízható összevetése és a lokálisan jóváhagyható frissítési mechanizmus tesztelése.
