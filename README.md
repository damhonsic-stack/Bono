# 🏎️ F1 25 AI inženýr

Závodní inženýr pro **F1 25** (včetně Season Pass 2026). Hra běží na Xboxu, inženýr na iPadu/iPhonu.
Čte UDP telemetrii ze hry a v reálném čase:

- **Tempo**: čas kola, živá delta proti referenci, odhad kola, sektory (fialová/zelená/žlutá)
- **Zatáčky**: automaticky najde zatáčky a po každém kole řekne, kde ztrácíš a proč
  (*„V Z4 ztrácíš 0,15 s. Brzdíš o 12 m dřív, na plný plyn o 20 m později.“*)
- **Obtížnost AI**: přečte obtížnost ze hry, spočítá cílový čas a řekne, jaké obtížnosti odpovídá tvoje tempo.
  Z časů AI v tvých kvalifikacích a trénincích se postupně sám kalibruje.
- **Reference podle výběru**: osobní rekord na trati, nejlepší kolo session, nejrychlejší AI, Time Trial rival
- **Závod**: palivo, opotřebení a teploty gum, mezera před tebou a za tebou, jestli stahuješ, nebo tě dojíždí
- **Rádio**: mluví česky nebo anglicky hlasem iOS (zdarma, offline)
- **Chat s inženýrem**: rychlá tlačítka nebo vlastní otázka. Bez internetu odpovídá podle pravidel,
  s Gemini klíčem odpovídá přirozeně (všechna čísla počítá aplikace, Gemini je jen formuluje).
- **Historie**: ukládá osobní rekordy a časy kol, takže vidíš zlepšování na každé trati

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
| UDP Format | **2025** |
| Your Telemetry | Public |

> Pokud se Season Passem 2026 hra nabízí formát 2026, nech zatím **2025**. Formát 2026 aplikace zatím neumí.

## 2A) Server přímo na iPadu (a-Shell, zdarma)

1. Z App Store nainstaluj **a-Shell** (zdarma).
2. Na GitHubu otevři tento repozitář → **Code → Download ZIP**. V aplikaci **Soubory** přesuň ZIP do složky
   **a-Shell** a klepnutím ho rozbal.
3. V a-Shell napiš:
   ```
   cd bono-main        # nebo jak se rozbalená složka jmenuje (ukáže ji příkaz ls)
   python3 server.py
   ```
4. Server vypíše IP adresu. Tu zadej v Xboxu (UDP IP Address).
5. Otevři **Split View**: vlevo a-Shell, vpravo Safari s adresou **http://localhost:8080**.
   iOS uspí a-Shell, když není vidět, proto ho nech na obrazovce (stačí úzký pruh).
   V Nastavení iPadu → Displej a jas → Automatický zámek nastav **Nikdy**.

Tip: v Safari → Sdílet → **Přidat na plochu**. Aplikace se pak otevírá na celou obrazovku.

## 2B) Server na PC / notebooku (doporučeno pro iPhone)

1. Nainstaluj Python 3 (Windows: Microsoft Store → „Python 3.12“, Mac/Linux ho většinou mají).
2. Stáhni repozitář a ve složce spusť:
   ```
   python server.py
   ```
3. Windows se zeptá na firewall → **Povolit** (privátní síť).
4. Do Xboxu zadej IP adresu PC, kterou server vypíše.
5. Na iPhonu/iPadu otevři v Safari `http://<IP PC>:8080` a dej **Přidat na plochu**.

## 3) První jízda

1. Na iPadu klepni na **🔇 Rádio**, tím zapneš hlas. iOS vyžaduje klepnutí, než může stránka mluvit.
2. Odjeď jedno **čisté platné kolo**. Aplikace z něj najde zatáčky (Z1, Z2 …) a nakreslí mapu trati.
3. Od dalšího kola dostáváš hlášení, kde ztrácíš. Záložka **Zatáčky** má tabulku a graf rychlosti, plynu a brzdy.

## Nastavení

- **Úroveň inženýra**: Nováček (málo hlášení, jedna rada), Pokročilý, Pro (i drobné ztráty a hlášení sektorů)
- **Srovnávat s**: automaticky / osobní rekord / nejlepší kolo session / nejrychlejší AI / TT rival
- **Obtížnost AI**: prázdné = vezme se ze hry, nebo zadej vlastní číslo pro cílové časy (např. v Time Trialu)
- **Gemini API klíč** (volitelné): zdarma na <https://aistudio.google.com/apikey>.
  Pozn.: studentské předplatné Gemini platí pro aplikaci Gemini, API klíč z AI Studia má vlastní free tier.
  Na free tieru může Google data použít ke zlepšování modelů. Posílají se ale jen čísla z telemetrie.

## Testování bez Xboxu

Simulátor posílá falešnou telemetrii (trať s 8 zatáčkami, ty + 5 AI, náhodné chyby jezdce):

```
python3 server.py                                  # terminál 1
python3 tools/simulator.py --speed 4               # terminál 2 (kvalifikace)
python3 tools/simulator.py --mode race --laps 15   # závod
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
engineer/radio.py      texty rádia CZ/EN, úrovně inženýra
engineer/llm.py        Gemini + offline odpovědi
engineer/state.py      hlavní logika
engineer/web.py        HTTP server + živý stream (SSE)
web/                   aplikace pro iPad/iPhone
tools/simulator.py     simulátor telemetrie
data/                  tvoje rekordy, kalibrace a nastavení (vzniká samo)
```

## Známá omezení (verze 1)

- Zatáčky jsou číslované podle pořadí na trati, ne podle oficiálního číslování.
- Cílové časy pro obtížnost jsou na začátku odhad podle reálných pole position. Zpřesňují se samy,
  jakmile odjedeš kvalifikaci nebo trénink s AI na dané trati.
- Formát UDP 2026 zatím není podporovaný (nastav ve hře 2025).
- Online: ostatní hráči mohou mít telemetrii omezenou, takže srovnání s nimi nemusí fungovat.
