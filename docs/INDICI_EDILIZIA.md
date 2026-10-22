# Indici tabellari per screening preliminare edilizio

**Fonte primaria:** Ministero del Lavoro e delle Politiche Sociali, Decreto ministeriale n. 143 del 25 giugno 2021 e tabella allegata degli indici di congruità.

- [Pagina ufficiale del D.M. 143/2021](https://www.lavoro.gov.it/documenti-e-norme/normative/Documents/2021/DM-143-del-25062021-congruita)
- [PDF del decreto](https://www.lavoro.gov.it/documenti-e-norme/normative/Documents/2021/DM-143-del-25062021-congruita.pdf)
- [PDF della tabella degli indici](https://www.lavoro.gov.it/sites/default/files/priorita/Documents/Tabella-Indici-Congruita-2021.pdf)
- [Informativa del Ministero sul sistema di congruità](https://www.lavoro.gov.it/notizie/pagine/registrato-dalla-corte-dei-conti-il-decreto-per-la-verifica-di-congruita-nel-settore-edile)

Fonte controllata il **22 ottobre 2026**. Nella v3.1 i 17 valori sono stati confrontati con due fonti secondarie indipendenti ([ANCE Ragusa](https://ragusa.ance.it/wp-content/uploads/archivet/45780-Tabella-Indici-Congruita-2021.pdf), [Cassa Edile di Milano](https://www.cassaedilemilano.it/wp-content/uploads/2021/11/20211021_CE-MI_normativa-congruita_Slide.pdf)): coincidono tutti. La seconda fonte riporta anche l'applicazione dal 1° novembre 2021 e la soglia di 70.000 euro per i lavori privati. Prima di ogni progetto pilota istituzionale occorre verificare nuovamente l'eventuale presenza di modifiche, circolari, accordi o indicazioni applicative successive.

## Indici trascritti

| Codice interno | Categoria riportata nella tabella ministeriale | Incidenza minima tabellare |
|---|---|---:|
| `OG1_NUOVA_CIVILE` | OG1 — Nuova edilizia civile, compresi impianti e forniture | 14,28% |
| `OG1_NUOVA_INDUSTRIALE` | OG1 — Nuova edilizia industriale, esclusi impianti | 5,36% |
| `RISTRUTTURAZIONE_CIVILE` | Ristrutturazione di edifici civili | 22,00% |
| `RISTRUTTURAZIONE_INDUSTRIALE` | Ristrutturazione di edifici industriali, esclusi impianti | 6,69% |
| `OG2_RESTAURO` | OG2 — Restauro e manutenzione di beni tutelati | 30,00% |
| `OG3_STRADALE` | OG3 — Opere stradali, ponti, ecc. | 13,77% |
| `OG4_SOTTOSUOLO` | OG4 — Opere d'arte nel sottosuolo | 10,82% |
| `OG5_DIGHE` | OG5 — Dighe | 16,07% |
| `OG6_ACQUEDOTTI_FOGNATURE` | OG6 — Acquedotti e fognature | 14,63% |
| `OG6_GASDOTTI` | OG6 — Gasdotti | 13,66% |
| `OG6_OLEODOTTI` | OG6 — Oleodotti | 13,66% |
| `OG6_IRRIGAZIONE_EVACUAZIONE` | OG6 — Opere di irrigazione ed evacuazione | 12,48% |
| `OG7_MARITTIME` | OG7 — Opere marittime | 12,16% |
| `OG8_FLUVIALI` | OG8 — Opere fluviali | 13,31% |
| `OG9_IMPIANTI_ENERGIA` | OG9 — Impianti per la produzione di energia elettrica | 14,23% |
| `OG10_DISTRIBUZIONE` | OG10 — Impianti per la trasformazione e distribuzione | 5,36% |
| `OG12_OG13_AMBIENTALE` | OG12 / OG13 — Bonifica e protezione ambientale | 16,47% |

I valori sono trascritti come quote decimali in `app/normativa_edilizia.py`, con link e data di verifica della fonte. I nomi dei codici sono chiavi tecniche interne, non classificazioni sostitutive delle categorie ufficiali.

## Limiti dell'implementazione

La funzione Emersione esegue esclusivamente uno **screening preliminare**: calcola il rapporto tra `costo_manodopera_dichiarato` e `valore_opera` ricevuti, e lo confronta con l'indice tabellare della categoria selezionata. Per lavori privati sotto 70.000 euro, segnala il limite di ambito descritto nelle informazioni del Ministero.

Questo non costituisce un'attestazione di congruità. Non vengono calcolate tutte le componenti eventualmente riconoscibili ai fini della congruità, gestite automaticamente varianti, subappalti, esclusioni, regolarizzazioni o procedura delle Casse Edili/Edilcasse. Una categoria errata, un valore economico non comparabile o un dato incompleto rende il risultato non valutabile o fuorviante. La conferma del caso applicabile spetta ai soggetti competenti.

Il risultato dello screening è mantenuto separato dal punteggio generale e **non attiva automaticamente una segnalazione di rischio**. Prima di qualsiasi uso istituzionale occorrono validazione normativa e metodologica e test su casi di riferimento approvati.
