# Kvittokoll

Lokalt verktyg för att stämma av banktransaktioner mot verifikat. Python 3.9+,
**bara standardbiblioteket**, inget byggsteg, ingen `pip install`. Lägg aldrig
till ett beroende — om något saknas, skriv det för hand.

## Kör och testa

```bash
python3 app.py                                   # http://127.0.0.1:8420/
python3 app.py --no-browser                      # samma, utan att öppna flik
python3 -m unittest discover -s tests -t tests   # hela testsviten
```

`static/*` läses från disk vid varje anrop och skickas med `Cache-Control:
no-store` — en omladdning i webbläsaren räcker efter en ändring där.
`kvittokoll/*.py` och `app.py` läses vid processtart och kräver omstart.

Servern stoppas med `pkill -f "[a]pp\.py"`, aldrig `pkill -f app.py`. Det
senare mönstret står i skalets egen kommandorad och matchar därmed sig självt —
skalet dör innan servern hinner startas om. Hakparentesen bryter matchningen
utan att ändra vad som träffas.

## Gyllene regeln: rör aldrig `data/`

`data/`, `settings.json` och `Transactions/` är skarp bokföring och är
otrackade. Git rör dem aldrig — `checkout`, `switch` och `restore` lämnar
otrackade filer i fred. Ett enda kommando bryter det: **`git clean` skulle
radera hela `data/`**, inklusive `outbox/`, `receipts/` och `backups/`. Kör det
aldrig, i någon form, hur harmlös flaggan än ser ut.

Kopiera, flytta eller radera heller aldrig något inuti `data/` på egen hand.

## Committa

Kör testsviten först, och committa bara med den grön. Faller ett test: visa
vilket och fråga — föreslå aldrig att testet ändras för att bli grönt.

Meddelandet skrivs på svenska, i presens, en rad, och beskriver vad användaren
märker — inte hur koden är byggd. Inga prefix som `feat:` eller `fix:`.

Raden byggs alltid på samma sätt, ungefär som en BEM-klass fast i klartext:
**vad som ändrats först, vilken ändring sedan.** Först subjektet — den sak
användaren ser och kan peka på: kolumnen, knappen, listan, kommandot. Sedan
verbet i presens som säger vad saken numera gör. Så här ser repot ut:

    <vad som ändrats>      <vilken ändring>

    Kolumnerna             linjerar mellan månadstabellerna
    Statushinkar           ersätter översiktsraden och statusmenyn
    Avbryt i redigeraren   lämnar källistan orörd
    git checkout -         växlar mellan de två senaste lägena

Uppdelningen är bara ett tankestöd — meddelandet är en vanlig mening på en rad,
med ett mellanslag mellan delarna. Faller subjektet bort börjar raden i koden
eller i arbetet i stället för i saken användaren ser, och då är den fel:
`Fixar layoutbugg`, `Uppdaterar app.js`, `Diverse förbättringar`.

Lägg till namngivna filer, aldrig `git add -A` — `data/` är gitignorerad, men
vanan är ändå fel här.

## Git svarar på svenska här

`git status` säger "På grenen main". Läs därför alltid maskinformat —
`--porcelain`, `--format`, `git rev-parse` — och matcha aldrig på fritext.

Att hoppa mellan lägen sköter användaren själv med vanlig git; se README.
