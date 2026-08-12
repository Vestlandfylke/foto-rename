# NB Foto-namngivar

Verktøy som gir re-digitaliserte fotofiler frå Nasjonalbiblioteket nye, ID-baserte filnamn, slik at dei kan importerast i arkivets bildebase. Identifikatoren står som maskin-trykt tekst i sjølve motivet (t.d. `SFFf-94263.0001`), og blir lesen med lokal OCR (RapidOCR / PP-OCR via ONNX). Ingen data blir sendt ut av maskina.

## Namngivingsregelen

Spesifikasjonen står i det interne dokumentet «Namngiving av fotofiler til arkivet.docx», som ikkje ligg i dette repoet. Kort fortalt:

- ID-en i motivet ser ut som `SFFf-94263.0001`.
- Taldelen manglar dei to første siffera i årstalet. Viss taldelen byrjar på **8 eller 9**, blir `19` lagt framføre, slik at `94263` blir `1994263`. Det gir Foto-ID `SFFf-1994263.0001`, akkurat som i databasen.
- Nytt filnamn blir då `SFFf-1994263.0001.jpg` (og `.tif`).
- Kvar fil har ein `.jpg`- og ein `.tif`-versjon med same filstamme. Begge får heilt likt nytt namn.
- Filer som ikkje passar (ingen `SFFf-`-ID funnen, eller taldelen byrjar ikkje på 8/9) blir **ikkje** omdøypte. Dei blir samla i eigne `_manuell`-mapper for manuell gjennomgang (elimineringsmetoden).

Du kan bruke verktøyet på tre måtar: ein **browser-app** (enklast å kome i gang med), ein **desktop-app** (eige programvindauge, kan installerast) eller **kommandolinja** (best for store batch-køyringar).

## Kom i gang (utan IDE, berre dobbeltklikk)

På ein vanleg Windows-PC utan utviklingsverktøy treng du berre to filer:

1. **`Installer.bat`**: dobbeltklikk éin gong. Den sjekkar at Python 3.13 finst (og installerer det via winget om det manglar), lagar eit lokalt Python-miljø og hentar alle avhengnader. Har du eit NVIDIA-grafikkort, spør den om du vil installere GPU-akselerasjon.
2. **`Start NB foto-namngivar.bat`**: dobbeltklikk kvar gong du vil bruke appen. Den startar verktøyet og opnar nettlesaren på `http://127.0.0.1:8000` automatisk. Lat det svarte vindauget stå ope medan du arbeider, og lukk det (eller trykk Ctrl+C) for å stoppe.

Det er alt. Resten av dette dokumentet er for utviklarar og for kommandolinje-bruk.

## Oppsett (utviklarar / PowerShell)

Krev Python 3.13 (RapidOCR/onnxruntime har ikkje wheels for 3.14 enno). `Installer.bat` køyrer eigentleg berre `setup.ps1`, som du òg kan starte direkte:

```powershell
.\setup.ps1
```

Alternativt ordnar CLI-wrapperen venv og avhengnader:

```powershell
.\run-nb-renamer.ps1 -Setup
```

Dette lagar `.venv` med Python 3.13 og installerer `rapidocr`, `onnxruntime`, `pillow`, `numpy` og web-avhengnadene.

### GPU-akselerasjon (valfritt, tilrådd)

For OCR på NVIDIA-GPU, installer torch med CUDA i venv-et:

```powershell
& .\.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
```

Då brukar verktøyet RapidOCR sin torch-CUDA-motor (PP-OCRv5). Utan GPU, eller utan torch, fell det automatisk tilbake til CPU (ONNX Runtime). I CLI styrer du dette med `--device gpu|cpu`; i web-appen er GPU standard når ein CUDA-GPU finst.

## Browser-app

Enklast: dobbeltklikk `Start NB foto-namngivar.bat` (sjå "Kom i gang" over). Frå PowerShell:

```powershell
.\start-app.ps1
```

Begge opnar nettlesaren på `http://127.0.0.1:8000` automatisk. Appen køyrer lokalt og arbeider på server-side mapper du skriv inn (ein nettlesar kan ikkje sende ekte filstiar, og dei store TIFF-ane kan ikkje lastast opp).

Grensesnittet er bygd som eit programvindauge, ikkje som ei nettside: verktøylinje med logo øvst, faner for dei tre stega, ei arbeidsflate som fyller vindauget og rullar for seg sjølv med tabellhovudet fastlåst, og ei statuslinje langs botnen som viser kva appen gjer, kva rapport som er open, kor mange rader ho har og om jobben går på GPU eller CPU. Tre steg i UI-et:

1. **Les og rapporter**: vel inn-mappe, eining (GPU/CPU) og innstillingar, start OCR og følg framdrifta, med tid att undervegs. Under **Avanserte val** vel du kvar ID-stripa ligg på bileta (nedst, langs venstre eller høgre kant, eller opp ned) i staden for å skrive gradar. Appen prøver retningane i tur og orden og stoppar ved fyrste treff, så kvar ekstra retning kostar berre tid på bilete som ikkje gav treff før.
2. **Gjennomgå**: hent rapporten og rett Foto-ID/status der det trengst. Rapportar med mange bilete blir henta 200 rader om gongen, med Førre/Neste under tabellen. Skal du rette mange, vel **Treng handarbeid** i filteret og trykk **Start gjennomgang**: eitt bilete om gongen i stor visning, snudd same veg som OCR-en las det, med OCR-teksten ved sida og ID-feltet i fokus. <kbd>Enter</kbd> går vidare, <kbd>Shift</kbd>+<kbd>Enter</kbd> tilbake, <kbd>Ctrl</kbd>+<kbd>S</kbd> lagrar, <kbd>Esc</kbd> lukkar. Appen varslar om ein ID ikkje passar mønsteret, eller om same ID er brukt på fleire bilete.
3. **Køyr omdøyping**: vel ut-mappe. Før noko blir skrive, viser appen kor mange som får nytt namn, kor mange som hamnar i `_manuell`, og eventuelle ID-kollisjonar, til stadfesting. Så blir det sjekka at disken har plass til kopien, og køyringa stoppar før fyrste fila dersom han ikkje har det. Undervegs kan du avbryte, og då stoppar appen mellom to filer, aldri midt i ei. Ei fil som ikkje lèt seg kopiere stoppar ikkje resten; ho blir talt som feil og hamnar i `uidentifiserte.csv` med grunnen.

## Desktop-app (Electron)

Same UI, men i sitt eige programvindauge i staden for i nettlesaren: ingen svart konsollvindauge, ingen adresselinje, og appen kan installerast med ei vanleg `Setup.exe`. Electron startar Python-backenden automatisk på ein ledig port på `127.0.0.1`, og stoppar han igjen når du lukkar appen. Alt køyrer framleis lokalt.

Køyre frå kjeldekoden (brukar `.venv`, same miljø som browser-appen):

```powershell
cd desktop
npm install
npm start
```

Byggje installasjonsfila. Fyrst blir det laga eit sjølvstendig Python-miljø i `desktop\runtime`, slik at maskina som installerer appen ikkje treng Python i det heile:

```powershell
cd desktop
.\scripts\build-runtime.ps1
npm run dist
```

Resultatet blir `desktop\dist\NB-foto-namngivar-Setup-<versjon>.exe`. Merk:

- I ein installert app kan programmappa vere skriveverna, så rapportane hamnar i `Dokument\NB foto-namngivar\rapport`. Du kan overstyre dette med miljøvariabelen `NBR_REPORT_DIR`.
- Backend-loggen finn du via menyen: **Hjelp → Opne loggmappa**.
- Etter ei omdøyping kan du opne ut-mappa eller sjå rapporten i Utforskar. Under lange køyringar viser oppgåvelinja framdrift, og appen varslar når jobben er ferdig, men berre om vindauget ikkje står framme. Alt dette går via `src\preload.js`, så det finst berre i desktop-appen.
- «Bla gjennom ...» brukar systemdialogen i Electron, via `src\preload.js`. Browser-appen har ikkje tilgang til han og går difor om `/api/pick` i backenden, som startar ein PowerShell-prosess per klikk. Difor finst begge vegane.
- Ikonet er eit dokument med OCR-tekst på PMS 304 C (`#9ADBE8`), botnfargen frå profilen til Vestland fylkeskommune. Det blir teikna som flate figurar, ikkje generert som eit bilete, så fargane er nøyaktige og motivet held seg skarpt heilt ned til 16 px:

```powershell
.venv\Scripts\python.exe desktop\scripts\draw_icon.py
.venv\Scripts\python.exe desktop\scripts\make_icons.py --preview tmp_preview.png
```

  Fyrste kommandoen skriv grunnlaget `desktop\build\icon.png` (1024x1024). Fargar og plassering ligg som konstantar øvst i `draw_icon.py`, og `--shape circle` gir ein rund variant i staden for den avrunda firkanten. Andre kommandoen lagar `build\icon.ico` (installasjonsfil og .exe), `src\icon.png` (appvindauga) og `nbrenamer\web\favicon.ico`. `--preview` er valfri og legg dei små storleikane side om side på lys og mørk botn, som er den einaste måten å sjå om ikonet toler 16 px.

### Oppdateringar

Desktop-appen sjekkar sjølv om det finst ein nyare versjon, og hentar han frå [GitHub-releases](https://github.com/Vestlandfylke/foto-rename/releases).

Slik opplever brukaren det:

- Ved oppstart, kort tid etter at vindauget er synleg, kjem det eit varsel dersom ein nyare versjon finst. Brukaren vel sjølv om han vil laste ned no eller seinare.
- Under nedlastinga viser appen framdrift i MB og prosent. Nedlastinga kan avbrytast ved å lukke vindauget.
- Når nedlastinga er ferdig, kan brukaren installere med ein gong, eller vente til han lukkar appen.
- Er maskina utan nettilgang, skjer det ingenting og brukaren blir ikkje masa på. Menyen **Hjelp → Sjekk etter oppdateringar ...** gir beskjed om kva som gjekk gale.

Appen lastar berre ned dei delane av installasjonsfila som er endra, fordi electron-builder lagar ei `.blockmap`-fil ved sida av `.exe`-en. GPU-pakkane ligg utanfor programmappa og blir ikkje rørte av ei oppdatering.

Ei oppdatering køyrer installasjonsfila i stille modus, og den innebygde NSIS-malen slettar då snarvegane utan å lage dei på nytt. `desktop\build\installer.nsh` lagar difor snarvegane på skrivebordet og i startmenyen på nytt til slutt i kvar installasjon, med app-identiteten sett på begge.

### Legge ut ein ny versjon

Ein release er ferdig fyrst når ein brukar med den førre versjonen faktisk får varsel om oppdatering. Gå gjennom alle stega under, og hopp særleg ikkje over sjekken i steg 4 og publiseringa i steg 5.

**1. Sett nytt versjonsnummer.** Køyr `npm version` inne i `desktop`, så blir både `package.json` og `package-lock.json` oppdaterte. Bygget les versjonen frå `package.json`. `package-lock.json` har han òg, to stader, og står dei ulikt, blir lockfila skriven om av neste `npm install`, midt i ei heilt anna endring.

```powershell
cd d:\foto-rename\desktop
npm version 1.1.1 --no-git-tag-version
cd ..
```

**2. Commit og tagg.** Taggen skal ha same nummer som `package.json`, med `v` framføre. Byggjejobben stoppar med ein tydeleg feil om dei ikkje stemmer, for elles ville brukarane fått tilbod om ein versjon som ikkje finst.

```powershell
git add -A
git commit -m "Versjon 1.1.1"
git tag v1.1.1
git push origin main --tags
```

**3. Følg med på bygget.** GitHub Actions byggjer Python-runtime og installasjonsfila, lastar filene opp med `gh` og lagar eit **release-utkast**.

```powershell
gh run watch
```

**4. Sjekk at releasen er heil.** Det siste steget i jobben les over releasen og feilar dersom installasjonsfila, `.blockmap` eller `latest.yml` manglar, så ei grøn køyring er i seg sjølv eit godt teikn. Sjå likevel over sjølv:

```powershell
gh release view v1.1.1
```

Du skal sjå tre filer: `NB-foto-namngivar-Setup-1.1.1.exe` på rundt 230 MiB, `.exe.blockmap` og `latest.yml`. Utan `latest.yml` finst det ikkje noko oppdateringsfeed, og appen svarar med feilmelding når nokon sjekkar etter oppdateringar.

**5. Publiser.** Så lenge releasen er eit utkast, ser korkje brukarane eller `electron-updater` han. Skriv kva som er nytt på Releases-sida og trykk **Publish release**, eller gjer det frå terminalen:

```powershell
gh release edit v1.1.1 --draft=false
```

**6. Stadfest at oppdateringa kjem fram.** Start appen på ei maskin som har den førre versjonen installert. Varselet skal kome av seg sjølv kort tid etter at vindauget er synleg, og **Hjelp → Sjekk etter oppdateringar ...** skal seie det same. Går det gale, skriv `electron-updater` kva URL han prøvde og kva han fekk tilbake i `%APPDATA%\NB foto-namngivar\logs\main.log`.

Gjekk noko gale undervegs, lag ein ny lapp-versjon i staden for å flytte ein tag som alt er pusha. Slett den mislukka releasen med `gh release delete v1.1.1 --yes` (taggen blir liggjande), og gå vidare til neste nummer.

Vil du testbyggje utan å publisere, køyr arbeidsflyten **Release** manuelt i Actions-fanen. Då blir installasjonsfila lagt ved som nedlastbar fil på byggjesida i staden for å bli publisert.

### GPU i desktop-appen

Installasjonsfila inneheld berre CPU-utgåva, slik at ho held seg lita. GPU-akselerasjon blir lasta ned frå inne i appen når det er behov for det:

- Ved fyrste oppstart tilbyr appen dette automatisk om maskina har eit NVIDIA-kort som ikkje er i bruk. Du kan svare "Ikkje no", eller krysse av for at appen ikkje skal spørje igjen.
- Du kan alltid gjere det seinare frå menyen **Verktøy → GPU-akselerasjon ...**, som òg viser om GPU er i bruk og kva kort som blir brukt.
- Nedlastinga (torch med CUDA, 2 til 3 GB) hamnar i `%LOCALAPPDATA%\NB foto-namngivar\gpu-packages`, altså utanfor programmappa. Det gjer at det verkar sjølv om appen er installert i Program Files, og at dei mange GB-ane ikkje blir med i ein roaming-profil.
- Appen må startast på nytt etterpå, og tilbyr det sjølv når nedlastinga er ferdig.
- Vil du heller ha alt inkludert i installasjonsfila, byggjer du runtime-en med `.\scripts\build-runtime.ps1 -Device gpu`. Då blir han rundt 5 GB utpakka.

## Arbeidsflyt i to fasar

Verktøyet er delt i to fasar så du kan kontrollere resultatet før nokon filer blir flytta.

### 1. `discover` (les og rapporter, flyttar ingenting)

OCR-ar alle bilete under ei mappe og skriv ein CSV-rapport med føreslåtte namn:

```powershell
.\run-nb-renamer.ps1 discover --input-dir "D:\sti\til\nb-bilete" --report report.csv --workers 4
```

- `--workers` styrer talet på parallelle prosessar. Sett det til omtrent halvparten av CPU-kjernane for best gjennomstrøyming.
- `--resume` hoppar over filer som alt står i rapporten, så du kan stoppe og halde fram.
- `--tiff-dir` viss `.tif`-filene ligg i ei anna mappe enn `.jpg`-ane.

Ved sida av rapporten blir det skrive ei eiga liste over bilete der OCR-en ikkje fann ein gyldig ID: `<rapportnamn>_uidentifiserte.csv`. Kvar rad har `original_jpg`, `matched_tiff`, `status` og ei **grunngjeving** (statisk forklaring ut frå feiltypen, med systemfeilen lagt til ved tekniske feil).

### 2. Sjå over rapporten

Opne `report.csv` (t.d. i Excel). Kolonnar:

| kolonne | tyding |
| --- | --- |
| `original_jpg` | full sti til kjeldefila |
| `ocr_text` | rå OCR-tekst (avkorta) for innsyn |
| `rotation` | rotasjonen som gav treff (0/90/270) |
| `raw_id` | ID-en slik han stod i motivet |
| `foto_id` | nytt namn etter 19-regelen |
| `new_basename` | filnamn utan etternamn |
| `year` | årstal utleidd frå Foto-ID |
| `matched_tiff` | `.tif` som høyrer til |
| `status` | `ok`, `manuell_ingen_id`, `manuell_uventa_tal` eller `feil` |
| `error` | merknad ved manuell/feil |

Du kan rette `new_basename`/`foto_id` manuelt og sette `status` til `ok` der du har fylt inn eit namn. `execute` les den redigerte fila. Steg 2 i appen gjer det same, men viser biletet ved sida av feltet og varslar om ID-ar som ikkje passar mønsteret eller er brukte fleire gonger.

### 3. `execute` (kopier/omdøyp)

Les rapporten og legg filene i utmappa:

```powershell
.\run-nb-renamer.ps1 execute --report report.csv --output-dir "D:\sti\til\omdøypt" --organize-by-year
```

- Standard er **kopiering** (trygt). Bruk `--move` for å flytte i staden.
- `--organize-by-year` legg `ok`-filer i undermapper per årstal.
- `--overwrite` skriv over eksisterande målfiler. Utan dette blir kollisjonar rapporterte og hoppa over.
- `ok`-filer får nytt namn; `manuell_*`-filer blir kopierte til `_manuell\<status>\` med originalnamn.
- I tillegg skriv `execute` ei samla liste `_manuell\uidentifiserte.csv` over alle bilete som ikkje kunne namngivast, med grunngjeving og kva mappe dei blei kopierte til. Filer som kolliderte eller ikkje lét seg kopiere står òg der, med grunnen, slik at ingenting forsvinn utan spor.
- Ved kopiering blir det rekna ut kor mykje plass som trengst før noko blir skrive, og køyringa stoppar med ein gong dersom disken ikkje har rom. Eit skann er eit par på rundt 630 MB, så nokre tusen bilete blir fort fleire terabyte.
- Éi fil som ikkje lèt seg kopiere, til dømes fordi ho er open i eit anna program eller er borte, blir talt som feil og hoppa over. Resten av køyringa held fram.

## Teste éi fil

```powershell
.\run-nb-renamer.ps1 test --file "D:\sti\til\eit-bilete.jpg"
```

Skriv ut full OCR-tekst, kva rotasjon som gav treff, rå ID, status og føreslått Foto-ID.

## Tekniske val

- **Multi-rotasjon**: billedteksten står av og til loddrett. Verktøyet prøver `0°`, så `90°`, så `270°`, og stoppar ved første treff. Vassrette bilete kostar berre éi OCR-køyring.
- **Autokontrast**: på som standard, hjelper på falma reprofilm. Slå av med `--no-autocontrast`.
- **Oppløysing**: bileta blir skalerte til lengste kant `--max-dim` (standard 2048) før OCR, for fart og for å halde seg innan modellgrensene.

## Kjende avgrensingar

- Bilete der teksten er fysisk uleseleg (svært falma reprofilm) får ingen ID og hamnar i `_manuell`. Dette er venta og må handsamast manuelt.
- OCR kan i sjeldne tilfelle lese feil siffer. Difor finst `discover`-rapporten: sjå over før `execute`.
