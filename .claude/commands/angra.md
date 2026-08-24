---
description: Kasta en ändring som blev fel, men behåll den åtkomlig
argument-hint: [tomt = det osparade, eller sha/ord för en sparad ändring]
---

Två fall. Är det oklart vilket som gäller — fråga.

Argument: $ARGUMENTS

## A. Det osparade blev fel (inget argument)

1. Visa `git diff --stat` så användaren ser vad som kastas. Vänta på ja.
2. Parkera det först — kasta aldrig något utan skyddsnät:
   ```bash
   SNAP=$(git stash create "ångrat utkast")
   NAMN=refs/utkast/angrat-$(date +%Y-%m-%d-%H%M%S)
   git update-ref "$NAMN" "$SNAP"
   git restore --staged --worktree .
   ```
3. Otrackade filer (`??`) rörs inte. Säg det, så att användaren själv får
   avgöra vad som ska hända med dem.
4. Rapportera: "Kastat ur arbetskatalogen. Ligger kvar i `$NAMN` —
   `git stash apply $NAMN` hämtar tillbaka den."

## B. En sparad ändring blev fel (argumentet pekar ut en commit)

1. Hitta commiten via `git log --oneline -20`, visa sha + meddelande, vänta på
   ja.
2. Står du i ett gammalt läge: `git switch main` först. Har du osparat arbete —
   parkera det enligt A2 innan du byter.
3. ```bash
   git revert --no-commit <sha>
   git commit -m "<svenskt meddelande i presens: vad som backas och varför>"
   ```
   Så låter det i repot: "Backa redigerarens tre fixar, för att göra om dem
   stegvis".
4. Kör testerna: `python3 -m unittest discover -s tests -t tests`.
5. Ändrades någon `*.py` av reverten: `pkill -f "[a]pp\.py"` och
   `python3 app.py --no-browser` i bakgrunden. Annars räcker en omladdning.
6. Rapportera: "Ändringen är backad. Originalet finns kvar som `<sha>` i
   historiken — `/backa <ord>` tar dig dit när du vill titta på den igen."

Använd aldrig `git reset --hard` och aldrig `git clean`. Revert och
`refs/utkast/` behåller allt — det är hela poängen.
