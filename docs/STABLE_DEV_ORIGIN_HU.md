# FieldWork – állandó fejlesztői cím és munkamenet-megőrzés

**Állapot: csak javaslatot előállító komponens, Pi-n NEM aktív.**

## Állandó cím

Tervezett, csak helyi hálózatról elérhető belépési cím: http://192.168.22.13:18090.
A dedikált fieldwork-dev-gateway a canary-kat külön belső portokon fogadja (M5: 18085, M6: 18086), de a felhasználó címe változatlan. Az éles 8080, korábbi staging 18081, M4 18084 és M5 18085 változatlan.
A gateway portjának szabad voltát az első helyi aktiválás előtt ellenőrizni kell. A stable_dev_gateway.py csak korlátozott Nginx konfigurációt tervez; nem indít, állít le vagy ír át Docker-containert.

## Miért nem elég az állandó port?

- A böngésző sessionStorage tárolója protokoll + host + port szerint elkülönül. A 18084 -> 18085 váltás új eredet, így új bejelentkezés kellhet. Az állandó 18090 ezt a problémát megoldja a nyitva lévő böngészőfülben.
- A jelenlegi M4/M5 canary-k külön adatbázist használnak. Token csak változatlan JWT-kulcs és továbbra is létező felhasználóazonosító mellett lehet érvényes.
- A végleges fejlesztői kiadáskövetéshez külön, tartós, kizárólag fejlesztői adatbázis kell, ellenőrzött migrációval és mentéssel.
- A JWT aláírókulcs maradjon helyi titoktárolóban, ne kerüljön GitHubba, manifestbe vagy naplóba. A token természetes lejáratát a port nem oldja meg.
- A sessionStorage új fülben nem feltétlenül marad meg. Biztonságos cookie-munkamenet hosszabb távon HTTPS alatt külön fejlesztési feladat.

## Kiadásváltás ellenőrzése

1. Kizárólag manifestben rögzített, helyi rendszer által hitelesített canary.
2. Teljes frontend/backend/regressziós/migrációs/jogosultsági teszt PASS.
3. A helyi adapter közvetlenül ellenőrzi a jelölt valódi health, jogosultsági és adatbázis-kompatibilitási állapotát; a beküldött PASS adat nem elegendő.
4. Előző gateway-konfiguráció mentése, hash, majd atomikus konfigurációcsere, nginx -t és reload.
5. A fix 18090 címen hitelesített smoke; hibánál route rollback. Adatbázis-visszaállítás nem automatikusan, mert felhasználói adatot törölhet.
6. Csak LAN/VPN elérés, semmilyen publikus port-forward.

## Valós jelenlegi állapot

A stable_dev_gateway.py kizárólag REVIEW_ONLY_NOT_DEPLOYED állapotot ad, nincs portnyitás. Az M5 továbbra is a 18085 porton fut, a 18090 még nem működik. A Github-feltöltő és az állandó cím megvalósításához az egyszeri, helyben jóváhagyott és visszaállítható MCP-aktiválás, dedikált adapter és teljes Pi-integráció szükséges.
