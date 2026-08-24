---
description: Gå fram igen till ett nyare läge, och lägg tillbaka osparat arbete
argument-hint: [tomt = ett steg fram, "senaste" = hela vägen till main]
---

Flytta arbetskatalogen framåt igen och lämna tillbaka det som lagts undan.

Argument: $ARGUMENTS

### 1. Var står du?

`git rev-parse --abbrev-ref HEAD`. Är svaret `main` står du redan längst fram —
hoppa till steg 4 och erbjud bara att lägga tillbaka ett utkast.

### 2. Lägg undan det som ändrats medan du tittade

Samma sekvens som `/backa` steg 2:

```bash
git status --porcelain
SNAP=$(git stash create "utkast från gammalt läge")
git update-ref refs/utkast/$(date +%Y-%m-%d-%H%M%S) "$SNAP"
git restore --staged --worktree .
```

Har du ändrat något medan du stod i det gamla läget ska det inte försvinna bara
för att du går hem.

### 3. Flytta framåt

- Argumentet är `senaste` → `git switch main`.
- Annars ett steg:
  ```bash
  NASTA=$(git rev-list --ancestry-path HEAD..main | tail -1)
  ```
  Är `$NASTA` tom är du framme — `git switch main`. Är det den commit som
  `main` pekar på — också `git switch main`, så att du landar på grenen och
  inte i ett frånkopplat läge. Annars `git checkout --detach "$NASTA"`.

### 4. Lägg tillbaka utkastet

Bara när du står på `main`:

```bash
git for-each-ref --format='%(refname:short)  %(committerdate:relative)' refs/utkast/
```

Finns utkast: visa det senaste och fråga om det ska läggas tillbaka. Ja →
`git stash apply <refnamn>`. Blir det konflikt: säg det rakt ut, lämna filerna
som de är och peka på refen — inget är förlorat.

**Ta aldrig bort refen**, inte ens efter en lyckad återläsning. Den kostar ett
par kilobyte och är hela skyddsnätet.

### 5. Starta om servern bara om det behövs

`git diff --name-only <där-du-stod> <där-du-är-nu> -- '*.py'` — tomt betyder
ingen omstart, annars `pkill -f "[a]pp\.py"` och `python3 app.py --no-browser` i
bakgrunden.

### 6. Rapportera

Var du står nu, vad som lades tillbaka, och "Ladda om
http://127.0.0.1:8420/".
