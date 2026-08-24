---
description: Spara det du gjort som ett läge, med ett svenskt commit-meddelande
argument-hint: [valfri beskrivning av vad ändringen gör]
---

Spara arbetskatalogen som ett nytt läge på `main`.

Argument: $ARGUMENTS

### 1. Står du i ett gammalt läge?

`git rev-parse --abbrev-ref HEAD`. Är svaret `HEAD` — committa **inte**. En
commit där blir nästan omöjlig att hitta igen. Gör i stället:

```bash
SNAP=$(git stash create "räddat från gammalt läge")
NAMN=refs/utkast/$(date +%Y-%m-%d-%H%M%S)
git update-ref "$NAMN" "$SNAP"
git restore --staged --worktree .
```

Säg: "Du står i ett gammalt läge, så jag har lagt undan ändringen i `$NAMN`.
Kör `/fram`, så lägger jag tillbaka den och sparar där." Avbryt sedan.

### 2. Finns något att spara?

`git status --porcelain`. Tom → säg det och sluta. Rader som börjar med `??`
är otrackade nya filer: nämn dem separat och fråga om de ska med, ta aldrig med
dem osett.

### 3. Kör testerna

```bash
python3 -m unittest discover -s tests -t tests
```

Faller något: visa vilket test och vad det säger, och fråga om det ska sparas
ändå. Föreslå inte att testet ändras för att bli grönt.

### 4. Föreslå ett commit-meddelande

Läs `git diff` och `git diff --staged`. Skriv ett meddelande som är:

- svenska, presens, en rad, gärna under 60 tecken
- en beskrivning av vad användaren märker — inte hur koden är byggd
- utan prefix som `feat:` eller `fix:`

Så låter repot:

    Kolumnerna linjerar mellan månadstabellerna
    Statushinkar ersätter översiktsraden och statusmenyn
    Nytt mönster från kopplingsdialogen kopplar alla förekomster

Har användaren gett ett argument: utgå från det, men skriv om det till stilen.

### 5. Vänta på ja, committa sedan

```bash
git add <de ändrade filerna vid namn>
git commit -m "<meddelandet>"
```

Aldrig `git add -A`, aldrig `git add .`, aldrig något under `data/`.

### 6. Rapportera

Ny commits korta sha och meddelandet, plus "Kör `/backa` för att jämföra med
läget innan."
