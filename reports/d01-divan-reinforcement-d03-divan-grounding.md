# d01-divan-reinforcement-d03-divan-grounding

## Premise caveats (read first)
- The files the brief points at do not exist on `main` or on this branch: `docs/reinforcement/d01-backlog.md`
  (B3/B4), `app/evals/offline.py`, `persona_golden.json`, and parent commit `2bc9eeb62c15`.
- **The "0/2 off-topic" baseline is unverified.** I never saw those two cases or how they were scored.
- **The golden sets are self-authored.** Tuning set: written with the gate. Held-out set: written by me after the gate
  was frozen. The audit relevance verdicts are mine too. Every before/after number below is therefore a
  **regression gate only**, not a reproduction of the d01 baseline and not evidence of live answer quality.
- Corpus edits stay under the original rule: no owner approval to edit quotable text is on record, so no corpus
  file was touched; markup is removed at load time and the Cyrillic problem is only detected (section 6).
- Branches: the session pinned `claude/divan-grounding-abstention-gpj2h9`; the brief footer asks for
  `cloudlab/d01-divan-reinforcement-d03-divan-grounding`. Both carry the same commits.

## What the code does now
- `app/rag/bm25.py`: a passage is cited only if it shares at least 3 distinct stems with the question (a two-stem
  question needs both, never fewer than 2). The rule is now an explicit `Gate` dataclass (`min_matched`,
  `min_idf_sum`, `min_best_idf`, `min_coverage`, `drop_generic`); the shipped default is `Gate()` = the 3-stem rule only.
  `search()` keeps its positional signature; `min_score`, `min_matched` and `gate` are keyword-only.
  `min_matched=1` reproduces the old results exactly.
- `app/rag/ingest.py`: `strip_markup()` per chunk after refs are assigned (no ref moves; old Rübailər "bənd 2" is still "bənd 2").
- **Removed:** `is_out_of_scope()` and its routing in `builder.py` / `guardrails.py`. `app/graph/` is byte-identical to
  `aab98b6` again, so the live path carries nothing unproven.
- `app/evals/offline.py` (retrieval + council-level eval, `--heldout`, `--audit`, `--no-gate`),
  `app/evals/gate_sweep.py`, `persona_golden.json`, `persona_golden_heldout.json`, `audit_relevance.json`,
  CI steps for the gated run and the report-only held-out and audit runs, `tests/test_grounding_abstention.py` (16 tests).

## 1. Gate sweep and the choice
`python -m app.evals.gate_sweep` (deterministic). Columns: audit questions that get any citation (18 name an advisor);
how many of the 4 questions whose old top hit I judged `weak` still get that same passage (none are `yes`); questions I
judged `no` that still get a citation (junk); hit@2 on in-scope questions with a known passage (tuning 21, held-out 8);
off-topic questions that retrieve nothing (tuning 10, held-out 12); in-scope questions that retrieve nothing (29).

```
setting                          audit cited weak+ kept  junk hit@2 tune hit@2 held off tune off held false abst
----------------------------------------------------------------------------------------------------------------
old: score floor only                  17/18        4/4    13      20/21       8/8      0/10     1/12       0/29
matched>=2                             15/18        3/4    12      20/21       8/8      7/10     8/12       0/29
matched>=3 (shipped)                    8/18        1/4     6      20/21       8/8     10/10    12/12       0/29
idf-sum>=4 (m>=2)                      11/18        3/4     8      20/21       8/8      8/10    10/12       0/29
idf-sum>=6 (m>=2)                       8/18        1/4     6      19/21       7/8     10/10    12/12       2/29
idf-sum>=8 (m>=2)                       4/18        1/4     3      12/21       6/8     10/10    12/12      10/29
idf-sum>=10 (m>=2)                      0/18        0/4     0       8/21       6/8     10/10    12/12      14/29
best-idf>=3.5 (m>=1)                    6/18        0/4     5       4/21       2/8      7/10     7/12      21/29
best-idf>=4.5 (m>=2)                    2/18        0/4     2       0/21       0/8     10/10    12/12      29/29
no-generic m>=2                         8/18        3/4     5      20/21       8/8      9/10    10/12       0/29
no-generic m>=3                         3/18        1/4     2      19/21       8/8     10/10    12/12       1/29
no-generic m>=2 idf-sum>=6              6/18        1/4     5      15/21       7/8     10/10    12/12       6/29
no-generic m>=2 idf-sum>=8              2/18        1/4     1      11/21       6/8     10/10    12/12      11/29
no-generic m>=2 cov>=0.35               0/18        0/4     0      19/21       8/8      9/10    11/12       1/29
no-generic m>=2 cov>=0.5                0/18        0/4     0      18/21       7/8     10/10    12/12       3/29
```

Decision rule, fixed before choosing: (1) every off-topic question must abstain on both sets, because a citation on an
off-topic question is the invented-citation failure; (2) then minimal false abstention; (3) then most weak citations
kept; (4) then fewest junk citations. **Chosen: `matched>=3` (unchanged).** It is the only setting that satisfies (1) with
0/29 false abstentions. Every setting that keeps more of the weak citations leaks off-topic questions:
`no-generic m>=2` keeps 3/4 weak and halves junk (13 to 5) but cites 1/10 tuning and 2/12 held-out off-topic questions
(3/22); `idf-sum>=4` keeps 3/4 but leaks 4/22; the settings that do hold off-topic at 100% (idf-sum>=6/8/10, coverage) start
abstaining on in-scope questions (1 to 29 of 29). The rare-stem rules (`best-idf`) are no better on any column.

What this means for "keep recall near 17/18": of the 17 old citations, 13 were lexical accidents ("amma", "var", "bir", "iki",
"mənim"), 4 are `weak` and none is clearly relevant. There is no population of genuinely relevant audit passages to preserve:
the corpus is classical literature and the audit questions are modern life situations. Raw coverage falling from 17/18 to
8/18 is mostly junk removed (13 to 6). I did not widen the generic-stem list using the leaked questions, because that would
fit the held-out set. If the owner values the 3 weak citations over 3 off-topic leaks, `Gate(min_matched=2, drop_generic=True)` is the
one-line alternative (opt-in, tested in the sweep).

## 2. The audit citations that were lost (all 9, passages in full)
Verdicts are mine (`audit_relevance.json`); overrule any of them. `weak` = thematically near but the match is not about
the asked point.

| # | question id | question | old top passage (work, ref; full text) | verdict |
|---|---|---|---|---|
| 1 | nesreddin-qonsu | Qonşum hər gün maşınını mənim yerimə qoyur, deyəndə də üzümə gülür. Mübahisə etmək istəmirəm. Nə edim? | *Molla Nəsrəddin lətifələri (üç lətifə: Əncir nübarı; Dalı bundan da pis gələcək; Qazı evdədir), hissə 3*: «Günlər keçir, həftələr dolanır, aylar başa çatır. Molla qalır zindanda. Günlərin birində, necə olursa, Teymur Ləng zindana gəlir. Mollanın nə üçün tutulmuş olduğunu soruşur. Molla əhvalatı danışır. Teymur əmr eləyir ki, Mollanı azad eləsinlər. Sonra soruşur: /  / — Sənin əncirin də mənim xoşuma gəlmişdi. De görüm məndən nə istəyirsən? /  / Molla deyir: /  / — Qibleyi-aləm, mən o əncir üçün sizdən o qədər görmüşəm ki, daha başqa mükafat istəməyə üzüm gəlmir. Xahiş eləyirəm, əmr eləyəsiniz mənə bircə dənə iti balta versinlər. /  / Teymur soruşur: /  / — Baltanı nə eləyirsən? /  / Molla deyir: /  / — Heç zad. Əlimdən bircə bu gəlir ki, o əncir ağacını dibindən kəsim. /  / Dalı bundan da pis gələcək» | no |
| 2 | nesreddin-reis | Rəisim hər iclasda məni hamının qabağında kiçildir. Cavab versəm, işdən çıxararlar. | *Molla Nəsrəddin lətifələri (üç lətifə: Əncir nübarı; Dalı bundan da pis gələcək; Qazı evdədir), hissə 7*: «— "Allaha şükür" de, qibleyi-aləm! Bizim yerlərdə öskürəndə qulaq asanlar "Allaha şükür" deyərlər. Əgər sən də Allahına şükür eləməsən, dalı bundan da pis gələcək. /  / Qazı evdədir /  / Şəhər qazısının Molladan çox acığı gəlirdi. Bir gün bir məsələdən ötrü Molla qazının yanına getməyə məcbur olur. Evinin qabağına çatanda qazının pəncərədən baxıb çəkildiyini görür. Molla qapını döyür. Qazının nökəri qapıya gəlib, xəbər alır: /  / — Kimi istəyirsən? /  / Molla deyir: /  / — Qazını görəcəyəm. /  / Nökər deyir: /  / — Ağam evdə yoxdur, bazara gedib. /  / Molla deyir: /  / — Qayıdanda ağana deyinən ki, bazara gedəndə bir də başını yadından çıxarıb pəncərədə qoymasın, yoxsa xalq elə bilər ki, evdədir.» | no |
| 3 | koroglu-haqq | Dostumun haqqını yeyiblər, mən şahidəm. Desəm, başım ağrıyacaq; deməsəm, vicdanım rahat olmayacaq. | *Koroğlu dastanı — Durna teli, hissə 35*: «Hay geyəndə haya basar, / Huy deyəndə huya basar, / Koroğlunu çaya basar, / Giziroğlu Mustafa bəy. /  / Giziroğlu Mustafa bəy Koroğludan bu sözü eşidib başının adamları ilə onun yanına gəldi. / Dedi: / – Koroğlu, sən doğrudan da Koroğlusan. Mərd iyidsən, bu gündən sonra arada olan düşmənçiliyi atdım, səninlə qardaş oldum. Başımdakı dəstəmlə sənin dəlilərinə qarışdım. Əl ver, düşməninlə düşmən, dostunla dostam. / Koroğlu ilə Giziroğlu bir-birlərinə əl verdilər. O gündən dost oldular.» | no |
| 4 | simurg-mena | Qırx yaşım var, hələ də bilmirəm həyatımın mənası nədir. | *Məlikməmməd nağılı (Zümrüd quşu), hissə 20*: «-Ey Məlikməmməd, qırx ağaclıqda bir padşahın ölkəsi var. Bir əjdaha gəlib suyun qabağmı kəsib. Nə qədər arzuman pəhləvanlar gedibsə, onu öldürə bilməyib. Yeddi ildi ki, əjdaha suyun qabağını kəsib. Hər gün bir qız aparıb onun ağzına atırlar. Əjdaha qızı yeyəndə bir az su axır, camaat da su götürür. Indi görürəm, sən qüvvətli pəhləvansan, olsa-olsa, о əjdahanı da sən öldürə bilərsən. Get о əjdahanı öldür. Padşahdan qırx şaqqa ət, qırx tuluq su al. Elə ki, dediklərimə əməl elədin, bu tükümü oda tut, mən hazır olaram, səni işıqlı dünyaya çıxardaram.» | no |
| 5 | simurg-telesmek | Uşaqlıqdan bəri tələsirəm, heç vaxt heç yerə çatmıram. Yorulmuşam. | *Bu qəsidə quşların söhbəti adlanır, bənd 9*: «Quşlar uşaqlar kimi əzbərləyir "ebcəd"i, / Bülbül "həmd" oxumaqda göstərir məharəti. /  / Dünən yeni körpələr dəvət olundu bağa, / Birdən göz yaşı tökdü qara bulud torpağa.» | no |
| 6 | nesimi-deyer | Hamı deyir ki, mən heç nəyə yaramıram. Artıq özüm də buna inanmağa başlamışam. | *Sığmazam (qəzəl), bənd 4*: «Gənci-nihan mənəm mən uş, eyni-əyan mənəm, mən uş, / Gövhəri-kan mənəm mən uş, bəhrəvu kanə sığmazam. /  / Gərçi mühiti-əzəməm, adım Adəmdir, Adəməm, / Dar ilə künfəkan mənəm, mən bu məkanə sığmazam.» | weak |
| 7 | nesimi-fikir | Öz fikrimi deyəndə məni ələ salırlar, ona görə susuram. Amma susanda özümə xəyanət edirəm kimi hiss edirəm. | *Zühur eylədi cümlə əşyada həq (qəzəl), bənd 1*: «Zühur eylədi cümlə əşyada həq, / Qanı bir bəsirətli, açıqnəzər. /  / Nəsimi kimi vahid ol yarilən, / Ikilik sifətdən ikilik bitər.» | no |
| 8 | dedeqorqud-toy | Oğlum evlənir. Toyda ata kimi ona nə deyim ki, ömrü boyu yadında qalsın? | *Kitabi-Dədə Qorqud — Qam Börənin oğlı Bamsı Beyrək boyı, hissə 9*: «Bunlar böylə edicək Baybörə bəgin acığı tutdı. Bazir-ganlara aydır: “Mərə, qavat oğlı qavatlar! Ata dururkən oğul əlinmi öpərlər?” Ayıtdılar: “Xanım, bu yigit sənin oğlunmıdır?” “Bəli, mənim oğlumdur”, - dedi. Ayıtdılar: “İmdi in-» | weak |
| 9 | dedeqorqud-ana | Anam qocalıb, kənddə tək yaşayır. Şəhərə, yanıma gətirmək istəyirəm, o isə evindən çıxmır. | *Kitabi-Dədə Qorqud — Dirsə xan oğlı Buğac xan boyı, hissə 19*: «Paralanub Qazılıq atımdan enməyincə, Yenümlə alca qanım silməyincə, Qol-bud olub yer üstinə düşməyincə Yalnuz oğul yollarından dönməyəyim! Yalnuz oğul xəbərin, a Dirsə xan, degil mana! Qara başım qurban olsun bu gün sana! - dedi, zarılıq eylədi, ağladı. Böylə digəc Dirsə xan xatunma cavab vermədi. Ol qırq namərd qarşu gəldi, aydır: “Oğlun sağdır - əsəndir, avdadır: bu gün-yarın qanda isə, gəlür; qorqma-qa-yırma, bəg sərxoşdur, cavab verəməz” - dedilər. Dirsə xanın xatunı qayıtdı, gerü döndi. Qatlanmadı, qırq incə qızı boyma aldı, bədəvi ata binüb, oğlancuğm istəyü getdi. Qışda-yazda qarı-buzı ərinməyən Qazılıq dağma gəldi çıqdı. Alçaqdan yuca yerlərə çapub çıqdı.» | no |


Still cited after the gate: 8 questions (2 `weak`, 6 `no`).

| question id | verdict | cited passage |
|---|---|---|
| nesreddin-qerar | no | Molla Nəsrəddin lətifələri, hissə 5 |
| koroglu-biznes | no | Koroğlu dastanı — Durna teli, hissə 16 |
| koroglu-ses | no | Koroğlu dastanı — Durna teli, hissə 19 |
| simurg-bosluq | no | Məlikməmməd nağılı (Zümrüd quşu), hissə 1 |
| dedeqorqud-miras | no | Kitabi-Dədə Qorqud — Dirsə xan boyı, hissə 23 |
| nizami-sevgi | weak | Leyli və Məcnun — sevişmə, bənd 4 |
| nizami-edalet | no | Leyli və Məcnun — ahuları, bənd 1 |
| nizami-evlilik | weak | Leyli və Məcnun — sevişmə, bənd 5 |


## 3. Scope gate: removed
`is_out_of_scope()` scored 0/12 on the held-out off-topic questions, so I removed it and its routing, its tests, and the
tuning-set scope numbers from earlier reports (they were in-sample and should not have been quoted as capability). Nothing replaced it:
a keyword list does not generalise, and I found no deterministic signal that separates an off-topic question from a
life-advice question (advisors legitimately answer 10/18 audit questions with no citation).

## 4. Council-level abstention (graph + stubbed LLM, no credits)
`python -m app.evals.offline` runs every off-topic question through the real graph in two modes. Results on the tuning
set (10 off-topic) and held-out set (12):

| check | meaning | before gate | after gate |
|---|---|---|---|
| council_abstention (tuning / held-out) | router says YEKUN: host reply, no advisor, no citation, no retrieval call | 10/10, 12/12 | 10/10, 12/12 |
| council_no_citation (tuning / held-out) | router names an advisor anyway: no citation is claimed | 0/10, 1/12 | **10/10, 12/12** |
| council_host_misrouted (tuning / held-out) | misrouted question still ends in the host reply | 0/10, 0/12 | **0/10, 0/12** |
| council_in_scope_cited | in-scope questions routed to their advisor come back cited | 21/21, 8/8 | 21/21, 8/8 |
| council_faithfulness | every graph citation quote is a prefix of its real chunk | 1.0 | 1.0 |

Does it hold? **Half.** With a router that declines, the council abstains (host reply, nothing retrieved, nothing cited).
With a router that wrongly names an advisor, no invented citation survives (the retrieval gate), but the advisor
**still answers**, uncited; nothing deterministic prevents that. `test_known_limit_a_misrouted_off_topic_question_still_gets_an_advisor_answer`
pins this so a future classifier flips it on purpose. The compliant-router row checks the host-reply plumbing, not router quality.
The first three rows are in the CI eval (`council_abstention`, `council_no_citation` gated at 1.0; host_misrouted printed, not gated).

## 5. Before / after on all sets (final setting)
Commands: `cd apps/voice-ai-agent && python -m app.evals.offline [--heldout] [--audit] [--no-gate]`. "Before" = score floor only.

| metric | tuning before | tuning after | held-out before | held-out after | audit before | audit after |
|---|---|---|---|---|---|---|
| hit@2 | 0.952 | 0.952 | 1.000 | 1.000 | n/a (no gold) | n/a |
| MRR | 0.944 | 0.944 | 1.000 | 1.000 | n/a | n/a |
| citation faithfulness | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| abstention, off-topic gets no citation | 0/10 | **10/10** | 1/12 | **12/12** | n/a | n/a |
| no-citation rate on audit questions | n/a | n/a | n/a | n/a | 1/18 | 10/18 |
| false abstention (in-scope, nothing retrieved) | 0/21 | 0/21 | 0/8 | 0/8 | n/a | n/a |
| audit citations that are lexical accidents | n/a | n/a | n/a | n/a | 13 | 6 |
| chunks carrying markup | 2 | 0 | | | | |

The single tuning hit@2 miss (`sim-divle`, gold at rank 3) is the same before and after. MRR is computed on the unfloored
ranking, so no gate setting can move it. The shipped rule was frozen at `52dde5f` and the sweep did not change it, so the
held-out column remains an out-of-sample estimate for that rule; I did read the held-out leak lists while evaluating the rejected alternatives.
Tests: `python -m pytest -q` 137 passed; `python -m app.evals.run` 8/8.

## 6. Cyrillic lookalikes (detected, not edited)
The problem is larger than the single "О" I reported before. Cyrillic letters that look like Latin ones sit inside the
transcribed text: 83 tokens in `nizami/xosrov-sirin-esq.txt` (Cyrillic "к": "кimi", "bəlкə", "gərəк", "çünкi") and 35 in
`simurg/melikmemmed-zumrud-qusu.txt` ("о saat", "О quşu", "уana"). That touches 21 of 379 chunks (20 of the 60 Simurğ chunks).
Effects measured: the tokenizer drops the Cyrillic letter ("кimi" becomes "imi", "bərкit" becomes "bər" + "it"), so those words
cannot match a normal query, and a citation would show the mixed-script text to a user as written. `test_cyrillic_lookalikes_in_the_corpus_are_reported_not_edited`
emits a warning with the per-file counts and fails if a new file gets any or if the known counts change, which forces a
decision when the owner approves a fix. A tokenizer-only fold (matching without touching quoted text) would fix retrieval
without a corpus edit; not done, because it changes the retrieval numbers and was not requested.

## Not measured
- The live router LLM and real answers; only the stubbed graph ran.
- The embeddings backend (`RAG_BACKEND=embeddings`): untouched.
- Whether my audit verdicts match the owner's.
- Any held-out set written by someone other than me; only one exists (30 cases).

## Open questions
- Owner approval to edit quotable corpus text (Cyrillic lookalikes, and the two files with markup)?
- Prefer fewer off-topic leaks (shipped) or 3 more weak citations (`Gate(min_matched=2, drop_generic=True)`)?
- Where are d01 B3/B4 and the original 0/2 cases?

## Recommended next briefs
1. Router-level abstention eval with live credits, and a scope classifier scored on a held-out set written by someone else.
2. Tokenizer fold for Cyrillic lookalikes (retrieval only) plus a before/after on all three sets.
3. Same coverage gate for the embeddings backend, compared with BM25 on one set.
