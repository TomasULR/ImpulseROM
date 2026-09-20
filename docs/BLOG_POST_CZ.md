# Impulse ROM — One UI 8.5 a Android 16 na Galaxy Note10+

*Text pro blog. Nepublikuj ho dřív, než bude vydání otestované na zařízení.*

---

## Šestiletý telefon, nejnovější Samsung systém

Galaxy Note10+ dostal poslední oficiální aktualizaci na Androidu 12. Samsung ho
opustil v roce 2023. **Impulse ROM na něj přináší One UI 8.5 postavené na
Androidu 16** — systém, který Samsung nasadil na Galaxy S24 FE.

Není to téma z nadpisu. Telefon opravdu běží na dnešním One UI: nové Nastavení,
nový vzhled, aktuální bezpečnostní záplaty systémové části, moderní běhové
prostředí Androidu 16.

## Jak to funguje

Impulse ROM vychází z [EternityROM](https://github.com/Ocin4ever/EternityROM) od
Ocin4evera, který stojí na build systému Salva Giangreca. Princip je „port
systémové půlky": vezme se systémový oddíl novějšího Samsungu (tady Galaxy
S24 FE, SM-S721B) a spojí se s vendor vrstvou a jádrem, které Note10+ reálně má.

To je zároveň důvod, proč některé věci nefungují. Systém očekává hardware, který
v telefonu není, a hardware odpovídá ovladačům, které systém už nezná. Většina
mojí práce na téhle ROM je smiřování těchhle dvou světů.

## Co v této verzi funguje

- Start systému, telefonování, mobilní data, Wi-Fi, Bluetooth
- Zvuk včetně reproduktorů a sluchátek
- Fotoaparát
- Čtečka otisků
- Displej v plném rozlišení 1440 × 3040
- **Extrémní ztlumení obrazovky** — Samsung tuhle funkci na Note10+ záměrně
  zablokoval seznamem zařízení. Impulse blokaci odstraňuje.

## Co nefunguje a nebudu předstírat, že ano

- **Bezdrátové nabíjení.** Nefungovalo ani v EternityROM. Kernel má všechny
  potřebné ovladače, problém je v userspace a zatím ho nemám odladěný.
- **Samsung Pay, Wallet a Secure Folder.** Tyhle nespraví žádná ROM. Odemčení
  bootloaderu propálí jednosměrnou pojistku Knox a Samsung to nikdy neodpustí.
- **Samsung Health.** Odmítne se spustit s hláškou o neoprávněných změnách.
  Kontroluje stav Knoxu a ten je po odemčení bootloaderu nevratně poznamenaný.
- **Play Integrity.** Část bankovních aplikací poběží, část ne.
- **AI funkce fotoaparátu a rozpoznávání textu v Galerii.** NPU ovladač
  Exynosu 9825 se neshodne s modely, které novější systém očekává.
- **Filtry v editoru fotek** občas spadnou.

## Co jsem v téhle verzi opravil

Nejdůležitější oprava: **náhodné restarty**.

Telefon se každé dva až čtyři dny sám restartoval. Z logů vyšlo najevo, že za to
může Samsungí kompenzace vypalování OLED displeje. Port jí předával parametry
panelu z původního Androidu 12, jenže knihovna, která je zpracovává, pochází z
One UI 8.5 a čeká jiný formát. Výsledkem byl zápis mimo přidělenou paměť a pád
celého systémového procesu.

Mimochodem — nebyly to skutečné restarty. Jádro běželo dva týdny v kuse. Padal
jen systémový proces, takže telefon ukázal bootanimaci a vrátil se na zámek.

Druhá věc, kterou lidé hlásili jako „náhodný restart", vůbec chyba nebyla.
Samsungí Péče o zařízení má naplánovaný týdenní automatický restart. V logu se
tváří jako pád, ale je tam k tomu i poznámka: *„normal operation caused by
device care"*.

## Pro koho to je

Pro člověka, který má Note10+ v šuplíku nebo jako druhý telefon a baví ho, když
starý hardware dostane druhý život.

**Není to ROM na hlavní telefon.** Je to alfa verze. Počítej s chybami, s tím,
že přijdeš o Samsung Pay natrvalo, a s tím, že instalace smaže všechna data.

## Instalace

Kompletní postup je v `docs/INSTALL.md`. Ve zkratce:

1. Stáhni si **předem** stock firmware pro návrat zpátky. Bez něj instalaci
   nezačínej.
2. Odemkni bootloader — smaže telefon a nevratně propálí Knox.
3. Nainstaluj TWRP.
4. **Zazálohuj si EFS.** Bez něj přijdeš o IMEI.
5. Wipe → **Format Data** (ne „Wipe", ne „Factory reset").
6. Ověř SHA-256 staženého ZIPu a nainstaluj ho.
7. První start trvá 10 až 20 minut.

Podporovaný je **výhradně SM-N975F**. Snapdragon verze (SM-N975U) ani 5G model
(SM-N976B) podporované nejsou a instalátor je odmítne.

## Licence

Impulse ROM je GPLv3. Kompletní zdrojové kódy jsou veřejné — u GPL to není
gesto dobré vůle, ale povinnost. Postaveno na práci Ocin4evera (EternityROM) a
Salva Giangreca (build systém).

---

*Nasazuješ to na vlastní riziko. Odemčení bootloaderu ruší záruku a instalace
smaže všechna data v telefonu.*
