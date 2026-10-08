# Audit of eleven high-scoring historical DOI rejections

Inspected 2026-10-08, using scorer checkpoint `2ae239d`. No DOI decisions,
assignments, stored scores, runtime code or production configuration changed.
That statement describes the audit itself. The user subsequently authorized
fixes and repairs, completed later on 2026-10-08; see
[the repair receipt](DOI_REPAIR_2026-10-08.md). The historical states below are
retained as evidence rather than rewritten to match the repaired database.

## Finding

Eight rejected pairs have strong evidence of a valid publication match. Three
are legitimate rejections of a full-paper DOI on a separately citable conference
precursor. All three precursor pairs score 100 on title/authors. Raising a
numeric cutoff cannot distinguish those versions.

The eight apparent valid pairs include one DOI currently assigned to a different
paper by the same authors. These findings make historical rejection status an
unsuitable uncurated negative label. They do not establish an overall error rate:
the eleven were selected precisely because they were high-scoring exceptions.

## Scope and method

Selected every rejected pair scoring at least 93/100 on title/authors from the
existing deterministic sample of 400 rejected candidates. Ten score 100; one
scores 93.333 before rounding. The comparison excludes date, journal and runner-up
deductions. Inspected candidate timestamps, competing assignments and public
editor notes in a read-only local database transaction. The transaction was
rolled back and the connection closed.

Checked all eleven current public paper records and the competing He–Wheeler
record through the site MCP. Publication assignments/notes agree with the local
snapshot; historical candidate timestamps below come from the local snapshot.
Compared arXiv and publisher metadata/abstracts, not complete proofs. Six fresh
Crossref work requests succeeded; three returned HTTP 500 and two HTTP 429.
Publisher pages/indexed primary-source pages supplied the remaining evidence.
No failed response was interpreted as evidence against a DOI match.

## All eleven cases

| Candidate | arXiv | DOI | Title/author score | Assessment |
| --- | --- | --- | ---: | --- |
| 7857 | [2004.00285](https://arxiv.org/abs/2004.00285) | 10.37236/9720 | 100 | Correct rejection: FPSAC extended abstract; DOI belongs to the longer paper 2007.07078. |
| 49574 | [2310.03527](https://arxiv.org/abs/2310.03527) | 10.1007/s00029-025-01113-x | 100 | Valid Periodic paper match; DOI is currently attached to the different Free boundary paper 2512.02267. |
| 27047 | [0707.4460](https://arxiv.org/abs/0707.4460) | 10.5802/jolt.583 | 100 | Valid match supported by title, authors, abstract and exact journal reference. |
| 11754 | [1801.05973](https://arxiv.org/abs/1801.05973) | 10.3934/dcds.2022022 | 100 | Valid match: Rauzy dynamics II, same author and labelling-method argument. |
| 29083 | [math/0312232](https://arxiv.org/abs/math/0312232) | 10.1006/jcta.2002.3291 | 100 | Valid match; journal publication in 2002 precedes the 2003 arXiv upload. |
| 3061 | [2201.06596](https://arxiv.org/abs/2201.06596) | 10.1287/moor.2023.0054 | 100 | Valid match: same author and characterization of simultaneous optimization. |
| 6218 | [2011.02139](https://arxiv.org/abs/2011.02139) | 10.1007/s10468-022-10115-8 | 100 | Valid match: same author and type D/exceptional-case completion of Reeder's conjecture. |
| 3221 | [2112.13333](https://arxiv.org/abs/2112.13333) | 10.37236/11724 | 100 | Correct rejection: FPSAC abstract; full-paper record 2210.17476 explicitly lists this DOI. |
| 2435 | [2204.06847](https://arxiv.org/abs/2204.06847) | 10.1090/tran/9103 | 93.333 | Valid match; the apparent title discrepancy is a normalization bug affecting mathematical italic capital M. |
| 25522 | [0906.3445](https://arxiv.org/abs/0906.3445) | 10.37236/323 | 100 | Correct rejection: FPSAC 2009 precursor; DOI is assigned to the full-paper record 0910.3047. |
| 20504 | [1306.0542](https://arxiv.org/abs/1306.0542) | 10.7146/math.scand.a-25501 | 100 | Valid match: same author and symbolic-power Stanley-depth inequalities. |

### Three legitimate version distinctions

The public editor notes describe all three as reviewed removals. The local
rejection timestamps are all `2026-08-18 09:40:12`. Independent source checks:

- Rodrigues: [short record](https://arxiv.org/abs/2004.00285) explicitly says
  extended abstract, 12 pages; [long record](https://arxiv.org/abs/2007.07078)
  explicitly identifies itself as a longer version, 43 pages. The
  [journal article](https://www.combinatorics.org/ojs/index.php/eljc/article/download/v30i4p30/pdf/)
  has DOI 10.37236/9720.
- Lazzeroni: [short record](https://arxiv.org/abs/2112.13333) explicitly says
  FPSAC extended abstract. The [full record](https://arxiv.org/abs/2210.17476)
  explicitly links DOI 10.37236/11724.
- Aval–Duchon: the [short record](https://arxiv.org/abs/0906.3445) cites FPSAC'09.
  The [journal publication](https://www.combinatorics.org/ojs/index.php/eljc/article/view/v17i1r51)
  is EJC 17 (2010), R51, DOI 10.37236/323. The existing reviewed note identifies
  [0910.3047](https://arxiv.org/abs/0910.3047) as the full-paper record. This audit
  corroborated venue/record distinctions; it did not repeat a PDF-by-PDF audit.

Their DOI owners are respectively 2007.07078, 2210.17476 and 0910.3047. The
existing assignment-conflict guard and rejection filter already block automatic
reassignment in this state. For a new unseen pair, title/author scoring alone
would still miss the version distinction.

### Six probable batch rejections

Candidates 27047, 11754, 3061, 6218, 2435 and 20504 all have stored score 0.600
and rejection timestamp `2026-03-30 09:07:27`. This suggests one batch operation;
the original reason is not recorded in the inspected legacy rows. It does not
prove which operator or rule rejected them. Current publication evidence:

- [Bergeron–Livernet, Journal of Lie Theory](https://jolt.centre-mersenne.org/articles/10.5802/jolt.583/):
  20 (2010), 3–15, exactly the journal reference on arXiv; matching rooted-tree
  pre-Lie construction and author names.
- [De Mourgues, DCDS](https://www.aimsciences.org/article/doi/10.3934/dcds.2022022):
  42 (2022), 3465–3538; same title, author and labelling-method classification.
- [Schoot Uiterkamp, Mathematics of Operations Research](https://pubsonline.informs.org/doi/abs/10.1287/moor.2023.0054):
  same title, author and least-majorized-element characterization; online 2024,
  volume 50 (2025), 252–276.
- [Di Trani, Algebras and Representation Theory](https://link.springer.com/article/10.1007/s10468-022-10115-8):
  same title, author and abstract; online 2022, volume 26 (2023), 881–900.
- [Elvey Price, Transactions AMS](https://www.ams.org/tran/0000-000-00/S0002-9947-2024-09103-1/):
  same author, title and general M-quadrant enumeration; 378 (2025), 3005–3084.
- [Seyed Fakhari, Mathematica Scandinavica](https://www.mscand.dk/article/view/25501):
  same author, title and symbolic-power inequalities; 120 (2017), 5–16.

### Publication before arXiv

Candidate 29083 was rejected `2026-05-07 07:57:03`, with stored score zero and no
inspected reason. The [arXiv record](https://arxiv.org/abs/math/0312232) already
gives JCTA 100 (2002), 153–175. Fresh Crossref metadata for
[10.1006/jcta.2002.3291](https://api.crossref.org/works/10.1006/jcta.2002.3291)
confirms the title, authors and pagination. The publisher's
[author bibliography](https://www.sciencedirect.com/author/6505856684/javier-parcet)
also lists the article and matching abstract. Fresh score is 98, including the
two-point deduction for publication one year before upload. The date ordering
is legitimate; whether it caused the old rejection remains unknown.

### Conflicting He–Wheeler assignment

Candidate 49574 was rejected `2026-09-15 15:19:14` with stored score 0.900.
The DOI is currently marked verified on
[2512.02267, Free boundary](https://arxiv.symmetricfunctions.com/paper/2512.02267).
However, the [publisher page](https://link.springer.com/article/10.1007/s00029-025-01113-x)
identifies the article as *Periodic q-Whittaker and Hall–Littlewood processes*,
with the same abstract as [2310.03527](https://arxiv.org/abs/2310.03527): periodic
processes and a (q,u) symmetry. The [Free boundary preprint](https://arxiv.org/abs/2512.02267)
instead concerns free boundaries and (q,t) symmetry. This is strong evidence
that the existing verified assignment is wrong. No reassignment was performed.

## Refinements justified by this audit

1. Curate labels before threshold fitting. Keep `wrong_work`, `wrong_version`,
   `assignment_conflict` and `legacy_unknown` distinct from a generic rejection.
   Record source evidence, and do not use a batch rejection as ground truth.
2. Add an automatic-approval review guard for explicitly marked extended
   abstracts/conference precursors when a journal DOI is proposed. Do not
   reject all conference papers: they may have their own valid DOI. Inspect
   related arXiv records, venue, explicit links and page counts as evidence.
3. When a DOI is already assigned, retain the no-reassignment guard but expose
   both records for review. An existing `verified` label is not proof that its
   assignment is correct, as the He–Wheeler case demonstrates.
4. Fix Unicode compatibility normalization before further calibration.
   `normalize_title('M-quadrant')` gives `m quadrant`, but
   `normalize_title('𝑀-quadrant')` gives `quadrant`. `_ascii_fold` casefolds
   before NFKD introduces ASCII capital M, which the subsequent lowercase-only
   filter removes. Add regression coverage for styled capitals and Greek
   symbols, with normalization/casefold ordering checked together.
5. Keep score separate from auto-approval eligibility. None of these cases
   justifies a higher scalar cutoff: even 100 admits the three wrong-version
   pairs, while a higher cutoff can lose valid matches. Keep the current 93
   threshold pending a curated evaluation of the complete decision process.

These are follow-up proposals, not changes implemented by this audit. The
eight apparent valid pairs need an explicit editorial correction pass; the
three wrong-version rejections should be retained. Current rejection filtering
continues to protect all eleven from automatic rediscovery/approval.

## Verification and reproducibility

Recomputed all eleven scores with the existing application scorer; inspected
all local rows and public site records; independently checked primary-source
publication evidence. No runtime change, so no build/test rerun was necessary.
The local snapshot has no `doi_review_events` table; this is not a production
schema finding. These legacy rejections predate the newly deployed API audit.

Local evidence artifacts: `/tmp/arxiv-high-rejects.json`,
`/tmp/arxiv-high-rejects-db.json`, `/tmp/arxiv-high-rejects-crossref.json`.
Python was used only to orchestrate bounded reads and the existing text scorer.
