# Kvittokoll

Lokalt verktyg för att stämma av banktransaktioner mot verifikat.

All data ligger på din dator. Ingen server, inget konto, ingen databas — JSON-filer
och en webbapp mot `localhost`.

> **Status: steg 1–7 av 9 byggda.** Import, dubbletthantering och arbetslistan
> fungerar mot skarp data. Inställningsvyn och massutskick är inte byggda ännu. Se [Vad som saknas](#vad-som-saknas).

## Kom igång

```bash
python3 app.py
```

Webbläsaren öppnas mot `http://127.0.0.1:8420/`. Inga beroenden utanför
standardbiblioteket, inget `pip install`, inget byggsteg.

```bash
python3 app.py --port 8421 --no-browser   # annan port, öppna själv
python3 -m unittest discover -s tests -t tests   # kör testerna
```

Kopiera `settings.example.json` till `settings.json` och fyll i dina uppgifter
när utskicksdelen är byggd. Verktyget kör utan den filen.

## Så används det

1. Exportera transaktioner från internetbanken som CSV eller camt.053-XML.
2. **Importera transaktioner** → välj fil → förhandsgranska → bekräfta.
3. Markera vilka rader som inte kräver verifikat. De försvinner ur arbetslistan
   men finns kvar — växla **Visa även rader utan verifikatkrav** för att se dem.
4. Koppla rader till underlagskällor. Källan bär länken dit verifikatet hämtas.
5. Klicka **Ladda upp** i verifikatkolumnen. Modalen visar källans länk — öppna
   den, logga in, ladda hem filen, och ladda upp den. Du kan också dra filen
   direkt på raden.
6. Klicka **Skicka**. Verktyget skapar en `.eml` med verifikatet bifogat och
   öppnar den i din mejlklient. Du trycker skicka, och markerar raden som
   skickad.

Varje rad visar sin källa som en pill under datumet. Saknas källa står det
**Koppla källa** där istället — aldrig båda, så raden håller sig smal.
Verifikatkolumnen fungerar likadant: **Ladda upp** när verifikatet saknas,
annars en klickbar statusbadge. Skickat-kolumnen med: *Väntar på verifikat*
tills det finns något att bifoga, sedan **Skicka**, sedan datumet. Under
**Källor** i toppen redigerar du namn, länkar, verifikattyp och mönster, och
ser hur många transaktioner varje källa fångar.

Importen är additiv. Den lägger bara till rader — den ändrar aldrig en status,
tar aldrig bort något och rör aldrig ett verifikat du redan laddat upp. Före
varje import tas en kopia av `data/transactions.json` till `data/backups/`.

## Import

### camt.053 (XML)

ISO 20022-kontoutdrag parsas direkt, utan profil. Belopp och tecken läses ur
`Amt` och `CdtDbtInd`, referenstexten ur `RmtInf/Ustrd`, `AddtlNtryInf` eller
motpartens namn — i den ordningen, beroende på vad banken fyller i.

### CSV

CSV kräver en importprofil, eftersom kolumnnamn, avgränsare, teckenkodning,
datumformat och decimaltecken skiljer sig åt mellan banker. Profiler ligger i
`profiles/` som JSON. `profiles/swedbank.json` följer med.

Kolumnmappningen tar antingen ett kolumnnamn eller en mall:

```json
"columns": {
  "date": "Bokfdag",
  "description": "Referens",
  "amount": "Belopp",
  "account": "{Produkt} {Clnr}-{Kontonr}"
}
```

Mallformen finns för att verkligheten sällan lägger ett fält i exakt en kolumn.
Swedbank delar upp kontot i clearingnummer, kontonummer och produktnamn.

Väljer du ingen profil provas alla tills en har alla obligatoriska kolumner.

### Rader som inte går att tolka

De kastas aldrig tyst. Förhandsgranskningen listar dem med radnummer och orsak.
Bekräftar du importen hoppas de över; inget skrivs för dem.

## Dubbletter

Bankexporter saknar oftast ett stabilt transaktions-ID. Swedbanks `Radnr` är
bara radens plats i just den exportfilen. Nyckeln byggs därför av innehållet:

```
datum | belopp | normaliserad text | löpnummer
```

Löpnumret finns för att samma belopp kan dras hos samma källa två gånger samma
dag. Importen räknar förekomster i den nya filen, räknar hur många som redan
finns lagrade, och lägger till differensen. Två identiska köp samma dag ger två
rader. Att importera om samma fil ger noll nya.

Levererar banken ett eget unikt ID används det istället — via `transaction_id`
i profilen eller `AcctSvcrRef` i camt.053.

## Underlagskällor

Entiteten är en **underlagskälla** — en specifik tjänst eller ett abonnemang,
inte ett bolag. Google Workspace och Google Cloud är två källor med olika
portaler och olika fakturor, trots att banktexten är snarlik. Bolaget finns med
som fält för gruppering, men styr ingenting.

### Matchningsmönster

Varje mönster har ett läge:

| Läge | JSON | Betyder |
|---|---|---|
| innehåller | `contains` (standard) | texten finns någonstans i transaktionstexten |
| börjar med | `starts_with` | transaktionstexten inleds med texten |
| slutar med | `ends_with` | transaktionstexten avslutas med texten |

Lägena finns för att `innehåller` ibland är för trubbigt. `börjar med HYRA`
fångar `Hyra Kontorsgatan 5` men inte `Bilhyra Stockholm` eller
`Avser hyra april`.

I `sources.json` skrivs det vanliga fallet som en enkel sträng och de
förankrade som objekt, så att filen förblir handredigerbar:

```json
"match_patterns": [
  "GOOGLE *WORKSPACE",
  { "pattern": "HYRA", "mode": "starts_with" }
]
```

Mönstret och transaktionstexten normaliseras på samma sätt innan matchningen —
versaler, borttagna skiljetecken, kollapsade mellanslag — så `GOOGLE *WORKSPACE`
träffar banktexten `Google Workspace_ab Dublin`, och en förankring sitter i
början av den normaliserade texten, inte efter ett skiljetecken.

Mönstret är text, inte ett reguljärt uttryck. Skriver du `A.*B` matchar det
tecknen `A.*B`, inte "A följt av vad som helst följt av B".

Längre mönster har företräde. Är två lika långa vinner det förankrade —
`börjar med HYRA` är mer specifikt än `innehåller HYRA`. Är även det lika
kopplas raden inte automatiskt, utan flaggas som tvetydig.

När du kopplar en rad kan du samtidigt lägga till ett mönster på källan.
Dialogen provar mönstret medan du skriver och visar hur många av dina
transaktioner det träffar, så att valet av läge inte blir en gissning.

## Filer

```
app.py                  starta appen
kvittokoll/             logiken
  storage.py            atomiska skrivningar, backup, papperskorg
  dedupe.py             dubblettnyckeln
  sources.py            källmatchning
  receipts.py           uppladdning och namnstandard
  mail.py               .eml-generering
  importer.py           förhandsgranska → bekräfta
  importers/            camt.053, CSV, profiler
  api.py                API-lagret, vet inget om HTTP
  server.py             HTTP, standardbiblioteket
static/                 gränssnittet, vanilla JS
  fonts/                Work Sans och JetBrains Mono, self-hostade
profiles/               importprofiler
data/                   din data — ligger i .gitignore
  transactions.json
  sources.json
  receipts/ÅÅÅÅ-MM/     uppladdade verifikat
  outbox/               skapade .eml-filer
  backups/
  trash/
```

`data/`, `receipts/` och `settings.json` ligger i `.gitignore`. Ingen av dina
transaktioner hamnar av misstag i ett publikt repo.

## Verifikat

Verktyget kan inte hämta verifikatet åt dig — det ligger bakom leverantörens
inloggning. Källans `receipt_url` är därför en genväg, inte en nedladdning: den
öppnas i en ny flik så att du slipper leta upp sidan varje gång, och källans
anteckning beskriver sista biten av vägen dit.

Filen du laddar upp **kopieras** in under `data/receipts/ÅÅÅÅ-MM/` så att den
överlever att nedladdningsmappen töms. Originalfilen lämnas orörd och
originalnamnet sparas.

### Namnstandard

```
{date}_{amount}_{tag}.{ext}     →  2026-03-14_449.00_google-workspace.pdf
```

Beloppet är absolut, med två decimaler och punkt — minustecken fungerar dåligt
i filnamn på vissa system. `{tag}` kommer från källans `filename_tag`; saknas
källa används transaktionstexten, gemener, bindestreck, max 40 tecken, utan
å/ä/ö. Vid namnkollision läggs `-2`, `-3` till.

Mallen ändras med `filename_template` i `settings.json`. Platshållare:
`{date}`, `{amount}`, `{tag}`, `{company}`, `{account}`. Blir en platshållare
tom dras dubbla avgränsare ihop, så `{date}_{company}_{tag}` utan bolag ger
`2026-03-14_google-workspace` och inte `2026-03-14__google-workspace`.

### Vad som kontrolleras

PDF, JPG, PNG och HEIC accepteras, och **innehållet** kontrolleras — inte bara
filändelsen. Det vanligaste misslyckandet när man hämtar verifikat bakom
inloggning är att man inte var inloggad och fick en HTML-sida som heter
`faktura.pdf`. Den avvisas med besked om vad som hänt, i stället för att
upptäckas av bokföraren en månad senare.

Ett verifikat per transaktion i version 1. Laddar du upp ett nytt flyttas det
gamla till papperskorgen. Samma sak vid **Ta bort verifikatet** — filer raderas
aldrig, de flyttas till `data/trash/`.

## Utskick

`mailto:` kan inte bifoga filer, och SMTP skulle kräva att du lägger ett
app-lösenord i en konfigfil. Därför `.eml`: verktyget skriver en komplett
mejlfil till `data/outbox/` och öppnar den i din mejlklient med bilagan redan på
plats. Du trycker skicka.

Ämnesrad och brödtext byggs av mallarna i `settings.json`, med platshållarna
`{date}`, `{amount}`, `{source}`, `{company}` och `{account}`. Beloppet behåller
sitt tecken här — en inbetalning och en utgift ska inte se likadana ut i
ämnesraden.

Adresserna fylls i första gången du skickar; de sparas i `settings.json`.

**Verktyget vet inte om mejlet gick iväg.** Det kan bara skapa filen och öppna
den. Därför markerar du raden som skickad i ett eget steg, efteråt. Att en rad
står som skickad betyder att du sa att den var det.

Massutskick (§8.4 i kravspecen) och SMTP som alternativ är inte byggda.

## Typsnitt

Work Sans för text, JetBrains Mono för belopp, datum och antal — siffror som
ska gå att jämföra kolumnvis mår bra av att vara lika breda.

Båda ligger i `static/fonts/` istället för att hämtas från Google Fonts CDN, så
att verktyget fungerar utan internet och inte skickar en förfrågan till en
tredje part varje gång du öppnar din bokföring. Cirka 158 kB, SIL OFL 1.1. Se
`static/fonts/README.md`.

## Begränsningar

Verktyget **bokför ingenting**. Det integrerar inte mot något bokföringssystem
och ersätter inte bokföraren. Det är en avstämningslista med minne.

Det kan inte heller veta vad bokföringssystemet faktiskt tagit emot. Att en rad
är markerad som skickad betyder att du markerade den som skickad.

Servern binder mot `127.0.0.1` och har ingen inloggning. Kör den inte mot en
adress som andra kan nå.

## Vad som saknas

Byggt: datamodell med atomiska skrivningar, import av camt.053 och CSV,
dubblettlogik, arbetslistan med statusar, kräver-verifikat-växlare,
källregistret med matchning, koppling och redigerbar källvy, uppladdning av
verifikat med namnstandard, samt `.eml`-utskick per rad.

Inte byggt ännu: massutskick (§8.4) och inställningsvyn (steg 8). Adresserna
går att fylla i från utskicksmodalen; övriga inställningar redigeras i
`settings.json`.

## Krav

Python 3.9 eller senare. Inga andra beroenden.

## Licens

MIT.
