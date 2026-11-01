# FieldWork DEV – első fix 18090-es gateway-aktiválás (R8)

**Állapot:** GitHubon előkészített és offline egységtesztelt, **nem futtatott Pi-host művelet**.

A felhasználó 2026-11-01-i Pi-kimenete szerint:
- M5 R8 él: külön Compose projekt \`fieldwork-parity-m5-r8\` és \`192.168.22.13:18085\`; API/DB healthy, Nginx fut, HTTP GET \`/api/health\` status ok.
- \`192.168.22.13:18090\` IP-n nincs TCP listener a méréskor.
- R8 exact 7 forrás SHA256 a \`parity-m5.Krm2sA3i\` könyvtárban megegyezik a scriptbe rögzített értékekkel.
- Production és régi 18081 staging érintetlen.

## Rendeltetés

A régi, áttekintésre szolgáló \`stable_dev_gateway.py\` csak \`fieldwork-parity-m5\` formájú projektnevet fogad, az éles teszt canary viszont \`fieldwork-parity-m5-r8\`. A meglévő tervező modul **nem engedélyez automatikus deploy-t**. Ezért egy külön, **helyben admin által indítható, első aktiválásra szűkített** eszköz készült az R8 fix belépési pontjához.

\`updater/activate_r8_stable_dev_gateway.py\`:
- \`--precheck\`: R8 forrás, futó 3 Docker-konténer, Compose-címkék, R8 HTTP health, hiányzó gateway-konténer, 18090 port szabad.
- \`--activate\`: ugyanaz a precheck, majd egy **új** \`fieldwork-dev-gateway-r8\` nevű konténer az R8 Nginx pontos image-ID-jából; kizárólag \`192.168.22.13:18090:8080\` publish; read-only rootfs, drop ALL capabilities, no-new-privileges, unprivileged UID 101, átírás nélküli config mount.
- A proxy upstreamja rögzített \`192.168.22.13:18085\`, nem production és nem 18081.
- Health hiba esetén kizárólag az újonnan létrehozott gateway konténer exact ID-ja kerül visszavonásra; korábbi rendszerek érintetlenek.
- Nincs DB-migráció, JWT-átvitel, felhasználó-/jelszómódosítás, forrásfelülírás, production restart.
- Megőrzi az R8 DB-jét az első stabil DEV-cím mögött; **jövőbeli verzióváltás DB/auth folytonosságát ez önmagában nem igazolja**.
- A LAN IP binding NEM bizonyít tűzfalszintű izolációt vagy HTTPS-t.
- A fix HTTP-origin új böngésző-tárterületet jelent: az első login új bejelentkezést igényelhet.

## Helyi művelet

Csak **helyi Pi admin-jóváhagyással** és a teljes Python-forrás SHA256 visszaellenőrzése után futtatható \`--activate\`. A publikus MCP-repo tárolhatja az indítót, de semmilyen titkos adatot vagy privát app-forrást nem tartalmazhat.

A már futó \`fieldwork-dev-gateway-r8\` konténert nem állítja le és nem írja át: ilyen állapotban FAIL-CLOSED.

## Teszthatár

A script 5 Python unittestje offline tesztkörnyezetben **PASS**, köztük source-drift, gateway collision, precheck, aktiválási paraméterek és kizárólag frissen létrehozott ID-ra korlátozott rollback. Nem volt Pi-n Docker-nginx indítási próba, ezért a valódi aktiválás még **PENDING**.

Az \`admin/admin\` kérést a gateway **nem hajtja végre**. Új e-mail/fiók és szerepkörök létrehozása külön M6 app integráció; productionban és tartós DEV-ben nem tehető alapértelmezetté gyenge jelszó.
