# Fonter

Fonterna ligger i repot istället för att hämtas från Google Fonts CDN. Två skäl:

1. Verktyget ska fungera utan internet. En avstämning ska gå att göra på tåget.
2. Ingen förfrågan går till en tredje part när du öppnar din bokföring.
   Ett CDN-anrop läcker IP-adress och tidpunkt vid varje sidladdning.

Filerna är hämtade från Google Fonts och innehåller enbart delmängderna
`latin` och `latin-ext`, vilket räcker för svenska. Båda är variabla fonter,
så en fil täcker hela viktomfånget.

| Font | Används till | Vikter | Licens |
|---|---|---|---|
| Work Sans | all icke-numerisk text | 300–700 + kursiv 400 | SIL OFL 1.1 |
| JetBrains Mono | belopp, datum och antal | 400–600 | SIL OFL 1.1 |

Totalt cirka 158 kB.

Licenstexterna ligger i `OFL-Work-Sans.txt` och `OFL-JetBrains-Mono.txt`.
Fonterna har inte ändrats, bara delmängdats av Google Fonts.

- Work Sans — https://github.com/weiweihuanghuang/Work-Sans
- JetBrains Mono — https://github.com/JetBrains/JetBrainsMono

## Uppdatera

Hämta `https://fonts.googleapis.com/css2?family=Work+Sans:ital,wght@0,300..700;1,400&family=JetBrains+Mono:wght@400..600&display=swap`
med en modern webbläsares User-Agent, plocka ut `latin`- och
`latin-ext`-blocken, ladda ner deras woff2-filer hit och uppdatera
`@font-face`-reglerna överst i `../style.css`.
