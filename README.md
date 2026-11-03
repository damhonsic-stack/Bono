# 🏎️ Bono: AI race engineer pro F1 25

Závodní inženýr pro **F1 25** (včetně Season Pass 2026). Hra běží na Xboxu, inženýr na iPadu/iPhonu.
Čte UDP telemetrii ze hry a v reálném čase:

- **Tempo**: čas kola, živá delta proti referenci, odhad kola, sektory (fialová/zelená/žlutá)
- **Corners**: automaticky najde zatáčky (T1, T2 …) a po každém lapu řekne, kde ztrácíš a proč
  (*„V T4 ztrácíš 0,15 s. Braking point o 12 m dřív, full throttle o 20 m později.“*)
- **Obtížnost AI**: přečte obtížnost ze hry, spočítá cílový čas a řekne, jaké obtížnosti odpovídá tvoje tempo.
  Z časů AI v tvých kvalifikacích a trénincích se postupně sám kalibruje.
- **Reference podle výběru**: osobní rekord na trati, nejlepší kolo session, nejrychlejší AI, Time Trial rival
- **Závod**: palivo, opotřebení a teploty gum, mezera před tebou a za tebou, jestli stahuješ, nebo tě dojíždí
- **Team radio**: mluví česky nebo anglicky hlasem iOS (zdarma, offline). V češtině jsou věty česky,
  ale F1 terminologie je anglicky (lap, sector, delta, gap, apex, braking point, tyre wear, fuel delta, Soft/Medium/Hard …).
- **Chat s inženýrem**: rychlá tlačítka nebo vlastní otázka. Bez internetu odpovídá podle pravidel,
  s Gemini klíčem odpovídá přirozeně (všechna čísla počítá aplikace, Gemini je jen formuluje).
- **Historie**: ukládá osobní rekordy a časy kol, takže vidíš zlepšování na každé trati
- **Regulace 2026** (Season Pass, UDP formát 2026): Straight/Corner mode a kolik % aero zón využíváš,
  Overtake mode (READY/ACTIVE, nevyužité okno, auto za tebou má overtake → „Defend“), ERS battery,
  harvest limit na lap, active aero zóny na mapě, race control (overtake enabled, partial mode)
- **Hands-free**: řekneš „**Bono**, …“ nebo zmáčkneš tlačítko na ovladači Xboxu
- **Strategie** (záložka Strategy): tyre degradation měřená z tvých lapů, pit loss naměřený ze
  skutečných zastávek aut, plán 0/1/2 zastávek s optimálním oknem (respektuje povinné 2 směsi a
  dostupné sady gum ze hry), „Box next lap / Box this lap“, odhad pozice po výjezdu, undercut,
  levná zastávka pod Safety Car / VSC, předpověď deště („rain in 12 minutes“) a přechod na inters
- **Soupeři**: směs a stáří gum všech aut, kdo byl v boxech, tempo aut kolem tebe
  („Norris behind on fresh Softs, 0.6 a lap faster, catches you in 3 laps“)
- **Incidenty**: track limits warnings, penalizace s důvodem, blue a yellow flag, Safety Car / VSC /
  red flag, kontakt, poškození (wing, floor…), defekt, „box for a new nose“
- **Kvalifikace**: out lap (teploty gum, battery), volná trať před tebou, „Push now“, auto za tebou
  na rychlém kole, provisional pozice, zbývající čas
- **Debrief** po session (záložka Debrief): Gemini shrne výsledek, konzistenci, srovnání s rekordem
  a top 3 věci na příště; ukládá se historie debriefů
- **Setup advice**: z úhlů skluzu kol pozná understeer/oversteer v entry/mid/exit a v pomalých,
  středních a rychlých zatáčkách, k tomu zamykání kol, protáčení a teploty gum. Navrhne konkrétní
  změnu, třeba „front ARB 8 → 7“
- **Realistický hlas** (volitelně): odpovědi Bona Gemini hlasem s filtrem týmového rádia

Všechno je **zdarma**. Potřebuješ jen Python 3, bez dalších knihoven, bez Macu a bez vývojářského účtu Apple.

---

## Jak to funguje

```
Xbox (F1 25) ──UDP 20777──▶ server.py (Python) ──Wi-Fi──▶ Safari na iPadu/iPhonu
```

Server může běžet **přímo na iPadu** (varianta A), nebo na **libovolném PC či notebooku** doma (varianta B).

## 1) Nastavení hry (Xbox)

F1 25 → **Nastavení → Nastavení telemetrie**:

| Položka | Hodnota |
|---|---|
| UDP Telemetry | **On** |
| UDP Broadcast Mode | Off |
| UDP IP Address | **IP adresa zařízení, kde běží server** (server ji vypíše po spuštění) |
| UDP Port | **20777** |
| UDP Send Rate | **20 Hz** (stačí; na iPadu šetří baterii) |
| UDP Format | **2026** (se Season Passem 2026), jinak 2025 |
| Your Telemetry | Public |

> Aplikace umí oba formáty a pozná je sama. Funkce regulací 2026 (aero, overtake, harvest limit)
> jsou jen ve formátu **2026**.

**Tlačítka na ovladači (doporučeno):** Settings → Controls → přiřaď **UDP Action 1–8** volným
tlačítkům (např. D-pad nebo kliknutí páčkou):

| Tlačítko | Co Bono udělá |
|---|---|
| UDP Action 1 | 🎙️ push-to-talk: Bono poslouchá otázku bez wake wordu |
| UDP Action 2 | Status report: pozice, gapy, tyres, fuel, battery |
| UDP Action 3 | Kde ztrácím čas (turns) |
| UDP Action 4 | Tyres |
| UDP Action 5 | Gaps |
| UDP Action 6 | Fuel |
| UDP Action 7 | Repeat: zopakuje poslední hlášení |
| UDP Action 8 | Mute: Bono přestane mluvit sám od sebe |
| UDP Action 9 | Strategy: plán zastávek a pozice po výjezdu |
| UDP Action 10 | Damage report |
| UDP Action 11 | Setup advice |
| UDP Action 12 | Debrief |

## 2A) Server přímo na iPadu (a-Shell, zdarma)

1. Z App Store nainstaluj **a-Shell** (zdarma).
2. V a-Shell napiš (stačí zkopírovat):
   ```
   cd ~/Documents
   curl -L -o bono.zip https://codeload.github.com/damhonsic-stack/Bono/zip/refs/heads/f1-ai-engineer
   unzip -o bono.zip
   cd Bono-f1-ai-engineer
   python3 server.py
   ```
3. iPad se zeptá na přístup k místní síti. Dej **Povolit**.
4. Server vypíše IP adresu. Tu zadej v Xboxu (UDP IP Address).
5. Dej a-Shell a Safari **vedle sebe** a v Safari otevři **http://localhost:8080**.
   iOS uspí a-Shell, když není vidět, proto ho nech na obrazovce (stačí úzký pruh).
   V Nastavení iPadu → Displej a jas → Automatický zámek nastav **Nikdy**.

Tip: v Safari → Sdílet → **Přidat na plochu**. Aplikace se pak otevírá na celou obrazovku.

### Aktualizace na novou verzi

V a-Shell (když server běží, nejdřív ho zastav: Ctrl+C):
```
cd ~/Documents/Bono-f1-ai-engineer
python3 update.py
python3 server.py
```
`update.py` stáhne nejnovější kód z GitHubu a **nesahá na složku `data/`**, takže Gemini klíč,
rekordy, kalibrace i debriefy zůstanou.

> Máš starou verzi bez `update.py`? Jednou spusť ve složce Bona:
> `curl -L -o update.py https://raw.githubusercontent.com/damhonsic-stack/Bono/f1-ai-engineer/update.py`
> a pak `python3 update.py`.

## 2B) Server na PC / notebooku (doporučeno pro iPhone)

1. Nainstaluj Python 3 (Windows: Microsoft Store → „Python 3.12“, Mac/Linux ho většinou mají).
2. Stáhni repozitář a ve složce spusť:
   ```
   python server.py
   ```
3. Windows se zeptá na firewall → **Povolit** (privátní síť).
4. Do Xboxu zadej IP adresu PC, kterou server vypíše.
5. Na iPhonu/iPadu otevři v Safari `http://<IP PC>:8080` a dej **Přidat na plochu**.

## 3) Před závodem: Start Bono

1. Nasaď sluchátka (AirPods) na iPad, aby Bono neslyšel sám sebe a hra mu nepřekřikovala mikrofon.
2. V aplikaci klepni na **▶ Start Bono**. Jedno klepnutí zapne hlas, mikrofon a zabrání zhasnutí displeje.
   Bono odpoví „Radio check, loud and clear“ a v liště svítí **👂 say “Bono”**.
3. Od té chvíle máš ruce na ovladači:
   - „**Bono**, how are my tyres?“ → odpoví do sluchátek
   - „**Bono**“ → pípne a 8 s čeká na otázku (v liště 🔴 Bono listening…)
   - nebo zmáčkni **UDP Action 1** na ovladači a rovnou mluv
   - Bono navíc sám hlásí lap time, kde ztrácíš, gapy, overtake mode, battery, fuel a tyres

**Všechno jde ovládat jen z iPadu.** Tlačítka na ovladači jsou volitelná. Dole na obrazovce je
panel velkých tlačítek: 🎙️ **Talk** (Bono poslouchá), **Status, Strategy, Gaps, Tyres, Fuel,
Where?** (kde ztrácím), **Damage, Repeat, Mute**. Odpověď Bono řekne nahlas.

Hlasové příkazy: *status report · strategy / when do I box · tyres · fuel · gap ahead / gap behind ·
where am I losing time · battery / overtake · damage · weather · setup advice · debrief ·
target / AI difficulty · say again · be quiet · talk to me · radio check*.

> **Mikrofon v Safari** funguje jen na zabezpečené stránce. `http://localhost:8080` (server běží na
> stejném iPadu v a-Shell) je v pořádku. Pokud server běží na PC a iPad otevírá `http://192.168…`,
> Safari mikrofon zakáže. Pak Bona ovládej **tlačítky na ovladači**, ta fungují vždy.
> Při prvním startu povol Safari přístup k mikrofonu a k rozpoznávání řeči.

## 4) První jízda

1. Klepni na **▶ Start Bono**.
2. Odjeď jeden **čistý valid lap**. Aplikace z něj najde zatáčky (T1, T2 …) a nakreslí mapu trati.
3. Od dalšího lapu dostáváš hlášení, kde ztrácíš. Záložka **Corners** má tabulku a graf speed / throttle / brake.

## Nastavení

- **Úroveň inženýra**: Rookie (málo hlášení, jedna rada), Advanced, Pro (i drobné ztráty a sector hlášení)
- **Reference**: Auto / Personal best / Session best / Fastest AI / Time Trial rival / Time Trial ghost
- **AI difficulty**: prázdné = vezme se ze hry, nebo zadej vlastní číslo pro target lap time (např. v Time Trialu)
- **Gemini API klíč** (volitelné): zdarma na <https://aistudio.google.com/apikey>. Klíč se ukládá jen
  lokálně do `data/settings.json` (na GitHub se nenahrává). Výchozí model `gemini-flash-lite-latest`
  odpovídá zhruba za 1 s. Když je přetížený, Bono zkusí `gemini-3.5-flash` a `gemini-flash-latest`,
  a když Gemini nejde vůbec, odpoví offline.
- **Hlas Bona**: *Mixed* (výchozí) = odpovědi na tvoje otázky realistickým Gemini hlasem s rádiovým
  filtrem, automatická hlášení a urgentní věci (box, vlajky, SC) okamžitě hlasem iOS.
  Free tier Gemini TTS pustí jen asi 2 hlasy za minutu, nad limit Bono automaticky mluví hlasem iOS.
  Pozn.: studentské předplatné Gemini platí pro aplikaci Gemini, API klíč z AI Studia má vlastní free tier.
  Na free tieru může Google data použít ke zlepšování modelů. Posílají se ale jen čísla z telemetrie.

## Testování bez Xboxu

Simulátor posílá falešnou telemetrii (trať s 8 zatáčkami, ty + 5 AI, náhodné chyby jezdce):

```
python3 server.py                                  # terminál 1
python3 tools/simulator.py --speed 4               # terminál 2 (kvalifikace)
python3 tools/simulator.py --mode race --laps 15   # závod (formát 2026)
python3 tools/simulator.py --format 2025           # starý formát
python3 tools/simulator.py --button 2              # stiskne UDP Action 2 (status report)
python3 tools/simulator.py --mode race --laps 25 --pit-lap 14 --sc-lap 8 --damage-lap 4 \
        --penalty-lap 6 --rain-in 12               # závod se vším: box, SC, damage, penalty, déšť
```

Testy: `python3 -m unittest discover -s tests`

## Struktura

```
server.py              spuštění
engineer/packets.py    parser UDP F1 25 (formát 2025)
engineer/laps.py       záznam kol, převzorkování po 5 m, delta
engineer/corners.py    detekce zatáček, srovnání, rady
engineer/targets.py    cílové časy podle obtížnosti AI + kalibrace
engineer/race.py       palivo, gumy, mezery a trendy
engineer/regs.py       regulace 2026: active aero, overtake mode, ERS
engineer/strategy.py   tyre deg, pit loss, plán zastávek, undercut, SC, počasí
engineer/opponents.py  gumy, zastávky a tempo soupeřů
engineer/incidents.py  track limits, penalizace, vlajky, safety car, poškození
engineer/quali.py      out lap, provoz na trati, push call
engineer/setup.py      vyvážení auta ze skluzu kol, návrhy setupu
engineer/debrief.py    debrief po session
engineer/tts.py        realistický hlas (Gemini TTS)
engineer/radio.py      texty rádia CZ/EN, úrovně inženýra
engineer/llm.py        Gemini + offline odpovědi
engineer/state.py      hlavní logika
engineer/web.py        HTTP server + živý stream (SSE)
web/                   aplikace pro iPad/iPhone
tools/simulator.py     simulátor telemetrie
data/                  tvoje rekordy, kalibrace a nastavení (vzniká samo)
```

## Známá omezení (verze 1)

- Turns (T1, T2 …) jsou číslované podle pořadí na trati, ne podle oficiálního číslování.
- Cílové časy pro obtížnost jsou na začátku odhad podle reálných pole position. Zpřesňují se samy,
  jakmile odjedeš kvalifikaci nebo trénink s AI na dané trati.
- Rozpoznávání řeči v Safari je hlavně pro angličtinu. Wake word „Bono“ se může občas netrefit
  (v hluku nebo u reproduktorů), a proto jsou tu i tlačítka na ovladači.
- Wake word, rozpoznávání řeči ani hlas iOS jsem nemohl vyzkoušet na skutečném iPadu, jen v prohlížeči
  na počítači se simulovaným mikrofonem.
- Strategie, setup advice a odhad pit loss jsou modely z telemetrie. Ve skutečné hře je potřeba je
  ověřit a doladit (otestováno jen se simulátorem).
- Online: ostatní hráči mohou mít telemetrii omezenou, takže srovnání s nimi nemusí fungovat.
