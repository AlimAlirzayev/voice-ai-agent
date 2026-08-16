# Corpus — what each advisor reads from

Every advisor answers out of their own real texts, and every reply carries the
passage it leaned on (`citations`). Sources are Azerbaijani literary heritage
transcribed on [Vikimənbə](https://az.wikisource.org); each file's header keeps
`work`, `author`, `translator` (where the page names one), `source` URL and a
licence line, so a citation can always be traced back to a real page.

| Advisor | Texts | Chunks |
|---|---|---:|
| `dedeqorqud` | Kitabi-Dədə Qorqud — müqəddimə, Basat, Bamsı Beyrək, Dəli Domrul, Dirsə xan boyları | 152 |
| `koroglu` | Koroğlu dastanı — Koroğluynan bəylər, Durna teli, Qocalığı, Ağcaquzu, Bayazid səfəri | 120 |
| `simurg` | Məlikməmməd nağılı (Zümrüd quşu — the Azerbaijani Simurg), quşların söhbəti qəsidəsi | 60 |
| `nizami` | Sirlər Xəzinəsi (söhbətlər), Leyli və Məcnun (hikmət, nəsihət, zülmə qatlaşmamaq, sevişmə), Xosrov və Şirin (eşq) | 32 |
| `nesimi` | «Sığmazam» və digər qəzəllər, rübailər | 21 |
| `nesreddin` | üç ənənəvi lətifə (Əncir nübarı, Dalı bundan da pis gələcək, Qazı evdədir) | 7 |

## Adding a source

1. Drop a `.txt` under `corpus/<advisor>/` with a header block:

   ```
   # work: <title as it should appear in a citation>
   # author: <original author, or "xalq yaradıcılığı" for folklore>
   # advisor: <roster key: nesreddin|koroglu|simurg|nesimi|dedeqorqud|nizami>
   # type: poem | prose
   # source: <URL>
   # translator: <only if the text is a translation>
   # license: <provenance line>
   ```

2. Re-index on every host that serves the app — the index is derived data and
   is not committed:

   ```bash
   docker compose exec api python -m app.rag.ingest
   ```

`type` matters: `poem` chunks by bənd so a citation never splits a couplet;
`prose` packs paragraphs to ~700 characters. `ingest.py` validates each file
and skips anything that looks like a failed fetch — a site error page served
under HTTP 200 once made it into this corpus before that check existed.
