# Judge calibration: rater instructions / Reytinq təlimatı

## Azərbaycanca

**Məqsəd.** «Divan» şurasının 20 cavabını sən qiymətləndirirsən; sonra sənin balların avtomatik hakimin ballarıyla müqayisə olunur. Hakimin balları səndən gizlədilib — ona baxma və təxmin etmə.

**Fayl.** `pack/labels.csv` (UTF-8; Excel/Numbers/LibreOffice-də açmaq olar). Hər sətir bir cavabdır: sual, danışan üzvlər, cavab. Yalnız bu sütunları doldur: `xarakter`, `mentalitet`, `dil`, `bedii`, `fayda` (tam ədəd, 1–5), istəyə görə `defects` və `comment`. Qalan sütunlara toxunma. Əmin deyilsənsə xananı boş burax — sıfır yazma.

**Şkala (hamısı üçün).** 1 — pis, yarama­yan; 2 — zəif, ciddi qüsur; 3 — orta, qüsurlu amma qəbul edilən; 4 — yaxşı, kiçik qüsur; 5 — təmiz, ustad işi. Yalnız 4 və 5 «qəbul edilir» sayılır.

| Sütun | Sual |
|---|---|
| `xarakter` | Cavab danışan üzvün(lərin) ədəbi/tarixi şəxsiyyətinə sadiqdirmi — üslub, düşüncə tərzi, mənbə ruhu? |
| `mentalitet` | Azərbaycan dəyərləri (ailə, ağsaqqal, halallıq, böyüyə hörmət, səbir, qonaqpərvərlik, qeyrət) təbii hiss olunurmu, yoxsa ümumi «self-help» tonu var? |
| `dil` | Təmiz ədəbi Azərbaycan dilidir? Türk/rus kalkası, tərcümə qoxusu, yad sintaksis varmı? |
| `bedii` | Mətn canlıdır — ritm, obraz, xalq ifadəsi varmı, yoxsa quru nəsihətdir? |
| `fayda` | Sual verən insan bu cavabla nə edəcəyini bilirmi? |

**Qaydalar.** Hər ölçünü ayrıca qiymətləndir (dil pis, amma fayda yaxşı ola bilər). Cavabı əvvəlcə bütöv oxu, sonra bal ver. Qeyd etdiyin qüsurları `defects` xanasına `;` ilə yaz. Bir oturuşda 20 cavab təxminən 40–60 dəqiqədir; yorulanda fasilə ver.

**Təhvil.** Doldurulmuş CSV-ni olduğu kimi qaytar (adını dəyişmə).

## English

**Purpose.** You rate 20 replies of the "Divan" council. Your scores are then compared with the automatic judge's scores. The judge's scores are hidden from you; do not look them up or guess them.

**File.** `pack/labels.csv` (UTF-8; opens in Excel, Numbers or LibreOffice). One row per reply: question, speaking members, reply. Fill in only `xarakter` (character), `mentalitet` (mentality/values), `dil` (language), `bedii` (literary style), `fayda` (usefulness) as whole numbers 1–5, and optionally `defects` and `comment`. Leave other columns alone. If you cannot judge a cell, leave it empty — do not write 0.

**Scale (all dimensions).** 1 unusable; 2 weak, serious defect; 3 mediocre, flawed but acceptable; 4 good, minor defect; 5 clean, masterful. Only 4 and 5 count as "acceptable".

**Rules.** Score each dimension independently. Read the whole reply before scoring. List defects in `defects`, separated by `;`. About 40–60 minutes for 20 replies; take a break when tired.

**Return.** Send back the filled CSV unchanged in name and columns.

## For the organiser (do not send to the rater)

- `pack/key.json` holds the judge's scores; keep it away from the rater.
- Score: `.venv/bin/python -m app.evals.calibration score --labels <filled.csv> --key docs/calibration/pack/key.json`
- Regenerate a pack from new audit reports: `.venv/bin/python -m app.evals.calibration pack --reports output/audit-vN.json --out docs/calibration/pack`
- Read the table: `exact` and `±1` are percent agreement; `kappa` unweighted, `k(quad)` quadratic-weighted (use this for the 1–5 scale), `k(pass)` agreement on the ≥4 accept/reject call; `bias` is judge minus human (positive = judge is more lenient). Common reading of kappa: <0.4 weak, 0.4–0.6 moderate, 0.6–0.8 good, >0.8 strong. With 20 items, kappa is noisy; treat it as a screen, not a certificate.
