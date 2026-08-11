# Demodata

Påhittade transaktioner och källor, så att du kan prova verktyget utan att
först exportera från din egen bank. Inget här är riktigt: bolaget, kontot,
bankgironumret och beloppen är hittepå.

`transaktioner-demo.csv` har samma form som en Swedbank-export — samma
kolumner, `cp1252`, radhuvud på första raden — så den läses av profilen
`profiles/swedbank.json` utan inställningar.

## Prova

```bash
cp demo/sources.json data/sources.json
python3 app.py
```

Importera sedan `demo/transaktioner-demo.csv`. Källorna matchar filens
transaktioner, så listan fylls direkt med kopplingar.

Vill du börja om: ta bort `data/transactions.json` och `data/sources.json`.

## Vad datan visar

Den är gjord för att röra vid de fall som är lätta att göra fel på:

- **Två identiska dragningar samma dag** — 2026-08-03, två gånger 1 256,09
  till Anthropic. De ska bli två rader, inte en, och en omimport ska ge noll nya.
- **Google Workspace och Google Cloud** — samma bolag, olika abonnemang, olika
  portaler. Fallet som gör *underlagskälla* till rätt entitet i stället för
  *leverantör*.
- **Moms, arbetsgivaravgift, avdragen skatt och lön** — källor med
  verifikatkravet avstängt. De döljs ur arbetslistan och räknas inte som saknade.
- **Kontorshyra** — `börjar med Hyra` fångar juni, juli och augusti utan en
  regel per månad.
- **Kundinbetalningar** — positiva belopp, som också behöver underlag.
