---
description: Backa till ett tidigare läge för att se hur appen betedde sig då
argument-hint: [antal steg, eller ord ur ett commit-meddelande]
---

Flytta arbetskatalogen bakåt i historiken. Inget arbete får gå förlorat.

Argument: $ARGUMENTS

### 1. Bestäm målet

- Inget argument → `HEAD~1`, ett steg bakåt från där du står.
- En siffra N → `HEAD~N`.
- Ord → sök i `git log --oneline -20` och välj den commit vars meddelande
  matchar. Är det tvetydigt: visa kandidaterna och fråga.

Lös upp målet med `git rev-parse --short <mål>` och visa meddelandet med
`git log -1 --format=%s <sha>` innan du fortsätter. Kom du inte fram till en
sha: säg det och sluta, hoppa inte på måfå.

### 2. Lägg undan osparat arbete

```bash
git status --porcelain            # tom → hoppa direkt till steg 3
SNAP=$(git stash create "utkast innan backning")
NAMN=refs/utkast/$(date +%Y-%m-%d-%H%M%S)
git update-ref "$NAMN" "$SNAP"
git restore --staged --worktree .
```

Kör sekvensen bara om `git status --porcelain` har rader utöver `??`. Är
`$SNAP` tom av någon anledning: avbryt hela kommandot och säg varför — hoppa
aldrig vidare med osparat i knät.

Rader som börjar med `??` är otrackade. De rörs inte av något steg här, men
nämn dem i rapporten så att användaren inte tror att de försvann.

### 3. Hoppa

```bash
git checkout --detach <sha>
```

### 4. Starta om servern bara om det behövs

```bash
git diff --name-only <sha> <där-du-stod> -- '*.py'
```

- Tomt → ingen omstart. `static/*` serveras från disk med `Cache-Control:
  no-store`, så en omladdning i webbläsaren räcker.
- Något → `pkill -f "[a]pp\.py"`, sedan `python3 app.py --no-browser` i bakgrunden.

### 5. Rapportera på svenska

- Vilket läge som nu ligger i arbetskatalogen: sha + meddelande.
- "Ladda om http://127.0.0.1:8420/" (och om servern startades om: säg det).
- Var utkastet ligger, om något lades undan — `/fram` lägger tillbaka det.
- "Kör `/fram` när du sett klart."
- Påminnelsen, varje gång: "Du tittar på gammal kod mot din skarpa data. Titta
  gärna — men importera inte, skicka inte och radera inget medan du står här."

Kör aldrig `git clean` eller `git reset --hard`, och rör aldrig `data/`.
