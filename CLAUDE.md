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
aldrig, i någon form, hur harmlöst flaggan än ser ut.

Kopiera, flytta eller radera heller aldrig något inuti `data/` på egen hand.

## Lägesmodellen

| Var du är | Under huven | Betyder |
|---|---|---|
| Hemma | `main` | Senaste läget. Här utvecklas och committas det. |
| Tittar bakåt | frånkopplat HEAD | Ett gammalt läge ligger i arbetskatalogen. Committa inte här. |
| Skyddsnät | `refs/utkast/*` | Undanlagt osparat arbete. Radera aldrig en sådan ref. |

Kommandon: `/spara`, `/backa`, `/fram`, `/lage`, `/angra`. Säg "gammalt läge"
till användaren, aldrig "detached HEAD".

Står ett gammalt läge i arbetskatalogen kör gammal kod mot skarp data. Titta —
men importera inte, skicka inte och radera inget så länge det gäller.

## Commit-stil

Svenska, presens, en rad, beskriver vad användaren märker — inte hur koden är
byggd. Inga prefix som `feat:` eller `fix:`. Så här ser repot ut:

    Kolumnerna linjerar mellan månadstabellerna
    Statushinkar ersätter översiktsraden och statusmenyn
    Backa redigerarens tre fixar, för att göra om dem stegvis

## Git svarar på svenska här

`git status` säger "På grenen main". Läs därför alltid maskinformat —
`--porcelain`, `--format`, `git rev-parse` — och matcha aldrig på fritext.
