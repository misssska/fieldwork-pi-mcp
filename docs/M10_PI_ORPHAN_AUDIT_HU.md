# M10 – Raspberry Pi Docker sandbox orphan-audit (2026-10-31)

**Állapot:** GitHub PR #2, CI-ben tesztelt, a Pi hoston NEM telepített
és NEM futtatott, kizárólag olvasási jelölt.

## Kiinduló bizonyítékok (élő MCP v0.6.1)

- `fieldwork_sandbox_command_status`:
  - `proposal_id=cfb10c47c1b3413c9adbd50e5c7249ef`
  - `run_id=b901aaabbbcccdddeeefff0000000020`
  - `status=RUNTIME_CLEANUP_FAILED`
  - `runtime_output=DOCKER_TIMEOUT`
  - `test_container cleanup ok=false`, külön DB/network/source cleanup true
  - `production_modified=false`, `production_mounts=false`
- A későbbi `c0ffee00000000000000000000000001` timeout
  `test_container cleanup=true` nyugtája **NEM** bizonyítja az előző
  azonosítójú konténer eltávolítását.
- Az éles `/api/health` és `/health` HTTP 200, a
  `fieldwork-stage` `STAGE_RUNNING_CHECK`. Ezek a saját Compose
  projektjeik állapotára vonatkoznak. A `fieldwork_compose_ps`
  **nem globális Docker konténerleltár**.
- Az aktív MCP `fieldwork_status` szerint host shell nincs, a
  sandbox parancsok **eldobható Docker-konténerben** futnak; ezért
  ugyanazzal az eszközzel nem lehet megbízható hostszintű Docker
  orphan-auditot végezni.

## GitHub-jelölt

`updater/pi_sandbox_orphan_audit.py`

- Egyetlen rögzített, helyi, csak olvasási `docker container ls --all
  --no-trunc --format '{{json .}}'` lekérdezés;
  `unix:///var/run/docker.sock` hostra szűkítve, a távoli
  `DOCKER_HOST` környezeti útvonalak kizárva.
- Nem root futtatás; nem fogad tetszőleges Docker-parancsot, képet,
  konténernevet, kötetet vagy fájlrendszerutat.
- A teljes JSONL host-inventoryt legfeljebb 256 tételben és
  1 MiB méretig, szigorú JSON-/64 hex ID-ellenőrzéssel értelmezi.
- A megadott, teljes, 32 hex karakteres `run_id` név-/címke
  egyezéseit jelöli; nyers Docker nevek, címkék, portok,
  env változók, mountok nem kerülnek a válaszba.
- Eltérő/hiányzó run marker esetén **nem állítja**, hogy a
  korábbi sikertelen takarítás helyreállt. A lehetséges eredmény:
  `HISTORICAL_CLEANUP_UNVERIFIED_NO_EXACT_MATCH`.
- Pontos marker találatkor az állapot
  `HISTORICAL_ORPHAN_CANDIDATE_FOUND_REVIEW_REQUIRED`; **akkor
  sem ad eltávolítási jogot**. A jelölt konténer lehet álnevesített
  vagy éles munkához tartozó; automatikus törlés nem megengedett.
- `historical_cleanup_receipt_resolved=false`,
  `sandbox_test_retry_authorized=false`,
  `container_removal_authorized=false`, a `production_modified`
  mindig false.
- Docker hiba, timeout, nem UTF-8 kimenet, duplikált vagy nem teljes
  container ID, túl sok sor esetén fail-closed.

`tests/test_pi_sandbox_orphan_audit.py`

- Negatív és biztonsági tesztek: pontos ID és label felismerés,
  félbevágott/hamisító azonosítók, prod-/stage konténerek
  téves jelölése, rejtett label adatok, hibás JSON és túl nagy
  inventory, csak olvasási fix Docker argv, nincs `rm` vagy
  `stop` futtatás.
- Docker-hívások a CI-ben mockoltak, ez **nem** valódi Pi-host audit.

## Miért nincs még tényleges takarítás?

A régi MCP v0.6.1 host-szintű jogosultsági szerződését nem
kerülhetjük meg egy másik sandbox-paranccsal. Egy élő, jóváhagyott
`fieldwork_sandbox_orphan_audit` csak külön, helyileg ellenőrzött
MCP-kiegészítőként telepíthető az operator kifejezett, arra a verzióra
szóló jóváhagyásával. Ez a PR önmagában nem telepít kódot.

A régi konténernevek és címkék nem igazoltan hordozzák a futás
teljes azonosítóját. **Puszta nulla egyezés nem bizonyít
orphan-mentességet.** Valódi helyi Docker-host leltár és a
problémás timeout után esetleg megmaradt konténer tulajdonosi,
mount-, hálózati, Compose-/image-ellenőrzése kell. Eltávolítás
esetén külön, egyértelműen azonosított konténerre szóló
helyi jóváhagyás és újraellenőrzött cleanup-bizonyíték szükséges.

## M10 elfogadási kapu

1. A read-only leltár a Pi-n sikeresen, az aktuális host Docker
   daemon ellen futott, és a rossz korábbi cleanup receiptet
   külön hivatkozza.
2. Minden potenciális árva és minden prod/stage erőforrás
   identitása dokumentált, ütközés nincs.
3. A konkrét régi futás cleanupja hostoldalon bizonyítottan
   rendezett; nem csak egy újabb futás cleanupja PASS.
4. A tiszta, privát Git-bázis egyszeri operator-jóváhagyása
   megtörtént, majd a teljes FieldWork valós tesztelése
   külön izolált környezetben sikeres.

**M10 host-audit jelenleg BLOCKED. Nincs kézi SSH-utasítás
vagy kockázatos automatikus takarítás. Nincs Pi deploy,
új tunnel, DB-módosítás, stage restart.**
