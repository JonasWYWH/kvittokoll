---
description: Visa var du står, vad som är osparat och vilka lägen du kan hoppa mellan
---

Rapportera läget. Ändra ingenting — det här kommandot är rent läsande.

Git svarar på svenska i den här miljön, så läs bara maskinformat. Kör:

```bash
git rev-parse --abbrev-ref HEAD          # "HEAD" = du står i ett gammalt läge
git rev-parse --short HEAD
git log -1 --format=%s
git status --porcelain
git rev-list --count HEAD..main
git log --oneline -8 main
git for-each-ref --format='%(refname:short)  %(committerdate:relative)' refs/utkast/
pgrep -fl "app.py" || true
```

Sammanfatta på svenska, kort, i den här ordningen:

1. **Var du står** — "Längst fram på main" eller "Du tittar på läget `<sha>` —
   `<meddelande>`. Det är N steg bakom senaste." Säg aldrig "detached HEAD".
2. **Osparat** — de ändrade filerna vid namn, eller "Inget osparat."
   Rader som börjar med `??` är otrackade: nämn dem separat och skriv att de
   ligger kvar oavsett hur du hoppar.
3. **Lägen att hoppa mellan** — de åtta senaste commitsen på main, med en
   markör vid den du står på.
4. **Undanlagda utkast** — innehållet i `refs/utkast/`, eller "Inga."
5. **Servern** — vilken port som svarar, eller "Ingen server igång."

Avsluta med nästa naturliga steg: `/spara`, `/backa` eller `/fram`.
