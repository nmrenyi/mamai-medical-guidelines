# RAG Source Evaluation — Relevance to MAMAI

Evaluation date: 2026-05-03

## Context

MAMAI is a point-of-care clinical decision support Android app for midwives in Zanzibar/Tanzania, a low-resource setting. This document evaluates all PDFs across `raw/open-books/`, `raw/whole-books/`, and `raw/exams/` for relevance to that use case.

Relevance is assessed on two axes:
- **Clinical actionability**: does the content answer bedside questions (what to do, how to do it, when to refer)?
- **Setting fit**: is the content applicable in a low-resource East African context?

RAG recommendation:
- **Include** — high-value content, ingest when licensing allows
- **Include (selective)** — moderate value; specific chapters/sections are worth ingesting, others are not
- **Exclude** — low clinical actionability or poor setting fit; not worth chunking

Copyright status is noted separately; see `source-research/notes/` for full licensing details.

---

## `raw/open-books/`

| File | Title / Author | Type | Relevance | RAG recommendation | Notes |
|---|---|---|---|---|---|
| `A book for midwives...pdf` | **A Book for Midwives** — Klein, Miller, Thomson (Hesperian, 2013) | Practical reference for community health workers | **Very high** — hands-on bedside reference written for exactly the midwife and setting MAMAI targets; covers pregnancy, labour, birth, postpartum, women's health | **Include** | Best setting fit of any source; low-resource, illustrated, accessible language. License needs permission for digital/AI use — contact `permissions@hesperian.org` |
| `ICM-Essential-Competencies-for-Midwifery-Practice.pdf` | **ICM Essential Competencies for Midwifery Practice (2024)** — ICM | Competency framework | **Moderate** — authoritative map of what midwives must know and do; useful for topic coverage but is a standards document, not clinical guidance | **Include (selective)** — knowledge and skill indicators are extractable; narrative framing less useful | CC BY-NC-SA 4.0 — can ingest now |
| `icm-professional-framework-for-midwifery.pdf` | **ICM Professional Framework for Midwifery (2025)** — ICM | Professional/governance framework | **Low** — covers professional philosophy, regulation, leadership; no actionable bedside content | **Exclude** | CC BY-NC-SA 4.0, but not useful for point-of-care retrieval |
| `msf-essential-obstetric-and-newborn-care.pdf` | **MSF Essential Obstetric and Newborn Care** — Médecins Sans Frontières | Clinical reference / emergency guidebook | **Very high** — designed for resource-limited/humanitarian facilities; actionable obstetric emergency protocols covering bleeding in pregnancy, normal delivery, malpresentations, third stage, newborn care, postpartum | **Include** | Closest match to MAMAI's use case after Hesperian; MSF copyright, permission needed before ingesting |
| `who-essential-childbirth-care-course.pdf` | **WHO Essential Childbirth Care Course — Module 1** (2023) | Training facilitator's guide | **Moderate** — embeds clinically useful tools (Labour Care Guide, Essential Newborn Care action plan), but the document as a whole is an educator's guide, not a clinician's reference | **Include (selective)** — extract Labour Care Guide and action plans; skip facilitation/pedagogy sections | CC BY-NC-SA 3.0 IGO — can ingest now |
| `who-midwifery-education-modules-1.pdf` | **WHO/ICM Midwifery Education Modules — Module 1: The Midwife in the Community** (2008) | Training module (educator-facing) | **Low** — covers community role, health systems, professional identity; minimal clinical procedure content | **Exclude** | WHO copyright; educator framing; no clinical action content |
| `who-midwifery-education-modules-2.pdf` | **WHO/ICM Midwifery Education Modules — Module 2: Managing Postpartum Haemorrhage** (2008) | Training module with embedded clinical content | **High** — active management of third stage, recognition and treatment of PPH; directly addresses a leading cause of maternal death | **Include** | WHO copyright, permission needed; clinical protocol content is sound and LMIC-appropriate |
| `who-midwifery-education-modules-3.pdf` | **WHO/ICM Midwifery Education Modules — Module 3: Managing Prolonged and Obstructed Labour** (2008) | Training module with embedded clinical content | **High** — partograph use, dystocia recognition, referral, intervention; critical for intrapartum care | **Include** | WHO copyright, permission needed |
| `who-midwifery-education-modules-4.pdf` | **WHO/ICM Midwifery Education Modules — Module 4: Managing Eclampsia** (2008) | Training module with embedded clinical content | **High** — recognition, magnesium sulphate protocol, emergency management of pre-eclampsia/eclampsia | **Include** | WHO copyright, permission needed |
| `who-midwifery-education-modules-5.pdf` | **WHO/ICM Midwifery Education Modules — Module 5: Managing Incomplete Abortion** (2008) | Training module with embedded clinical content | **High** — recognition and management of incomplete/unsafe abortion complications | **Include** | WHO copyright, permission needed |
| `who-midwifery-education-modules-6.pdf` | **WHO/ICM Midwifery Education Modules — Module 6: Managing Puerperal Sepsis** (2008) | Training module with embedded clinical content | **High** — recognition, antibiotic treatment, management of postpartum infection | **Include** | WHO copyright, permission needed |

---

## `raw/whole-books/`

All titles in this directory are copyrighted commercial publications. None can be ingested without explicit publisher permission (Elsevier, OUP, Jones & Bartlett, ACM). Relevance is assessed to guide which permissions are worth pursuing.

| File | Title / Author | Type | Relevance | RAG recommendation | Notes |
|---|---|---|---|---|---|
| `ACM Guidelines for Consultation and Referral.pdf` | **National Midwifery Guidelines for Consultation and Referral, 4th ed** — Australian College of Midwives (2021) | Clinical practice guideline | **Low-moderate** — referral trigger framework is clinically useful in principle, but thresholds and pathways are Australia-specific | **Exclude** — jurisdiction too specific for Zanzibar context | ACM copyright; free PDF; permission should be sought if including |
| `Clinical practice guidelines for midwifery and women's...pdf` | **Clinical Practice Guidelines for Midwifery & Women's Health, 4th ed** — Tharpe, Farley & Jordan (Jones & Bartlett, 2013) | Clinical reference / guideline compendium | **Moderate** — problem-oriented format maps well to point-of-care lookup; drug dosages and referral pathways are US-centric | **Include (selective)** — complications and emergency chapters after localisation | Jones & Bartlett copyright; permission needed |
| `MayesMidwifery.pdf` | **Mayes' Midwifery, 14th ed** — Fraser & Cooper (eds) (Elsevier) | Comprehensive academic textbook | **Low** — encyclopaedic narrative prose; UK NHS context; poorly suited to point-of-care RAG retrieval | **Exclude** | Elsevier copyright with explicit AI/RAG restriction; not worth pursuing |
| `Myles Textbook for Midwives. 16th Edition.pdf` | **Myles Textbook for Midwives, 16th ed** — Marshall & Raynor (eds) (Elsevier, 2014) | Comprehensive academic textbook | **Low** — dense textbook prose; UK NHS context; same issues as Mayes' | **Exclude** | Elsevier copyright with explicit AI/RAG restriction |
| `Oxford-Handbook-of-Midwifery-3e-PDFDrive-.pdf` | **Oxford Handbook of Midwifery, 3rd ed** — Edwards & Thomas (OUP) | Pocket clinical reference | **High** — compact, protocol-style entries; emergencies and complications sections are directly applicable; well-suited to RAG chunking | **Include** — high priority for permission request | OUP copyright; permission needed |
| `Midwifery _ Preparation for Practice...pdf` | **Midwifery: Preparation for Practice, 4th ed** — Pairman, Tracy, Dahlen & Dixon (Elsevier, 2018) | Comprehensive academic textbook (AU/NZ) | **Low** — jurisdiction-specific professional and regulatory content; AU/NZ framing limits applicability | **Exclude** | Elsevier copyright with AI/RAG restriction |
| `Physiology in Childbearing...pdf` | **Physiology in Childbearing, 3rd ed** — Stables & Rankin (Elsevier) | Academic bioscience reference | **Very low** — explanatory physiology prose; no clinical management protocols; does not answer bedside action questions | **Exclude** | Elsevier copyright; low relevance makes permission not worth pursuing |
| `Varney's Midwifery(6th Edition)...pdf` | **Varney's Midwifery, 6th ed** — King, Brucker & Osborne (Jones & Bartlett, 2018) | Comprehensive academic textbook (US) | **Low-moderate** — clinically thorough but US regulatory framing; selective chapters on complications may have value | **Exclude** — deprioritise; pursue Oxford Handbook and Skills for Midwifery Practice first | Jones & Bartlett copyright |
| `skills-for-midwifery-practice.pdf` | **Skills for Midwifery Practice, 4th ed** — Bowen & Taylor (Elsevier) | Procedural skills manual | **High** — 56 skill-based chapters with step-by-step procedure format; covers assessment, drug administration, intrapartum skills, neonatal assessment, resuscitation | **Include** — high priority for permission request; equipment/drug names need localisation | Elsevier copyright with AI/RAG restriction; needs custom license |
| `midwifery-essentials-2.pdf` | **Midwifery Essentials Vol 2: Antenatal** — Baston & Hall (Elsevier) | Short educational volume | **Moderate** — antenatal assessment and surveillance content is useful; reflective/narrative format reduces RAG density | **Include (selective)** — clinical assessment chapters only | Elsevier copyright |
| `midwifery-essentials-3.pdf` | **Midwifery Essentials Vol 3: Labour** — Baston & Hall (Elsevier, 2017) | Short educational volume | **Moderate-high** — intrapartum care is core to MAMAI; labour progress, fetal monitoring, third stage chapters are useful | **Include (selective)** — clinical chapters only | Elsevier copyright |
| `midwifery-essentials-5.pdf` | **Midwifery Essentials Vol 5: Infant Feeding** — Marshall, Baston & Hall (Elsevier, 2017) | Short educational volume | **Moderate** — breastfeeding/lactation support relevant to postnatal care; UNICEF Baby Friendly content is internationally endorsed | **Include (selective)** | Elsevier copyright |
| `midwifery-essentials-6.pdf` | **Midwifery Essentials Vol 6: Emergency Maternity Care** — Baston & Hall (Elsevier, 2018) | Clinical emergency reference volume | **Very high** — APH, cord prolapse, breech, shoulder dystocia, PPH, maternal collapse, eclampsia, sepsis, neonatal resuscitation; emergency protocols are largely aligned with WHO/international guidance | **Include** — highest priority in whole-books/; pursue permission first | Elsevier copyright with AI/RAG restriction; needs custom license |

---

## `raw/exams/`

| File | Title / Issuing Organisation | Type | Relevance | RAG recommendation | Notes |
|---|---|---|---|---|---|
| `icm-essential-competencies-assessment-guide.pdf` | **ICM Essential Competencies — Assessment Guide** (ICM / MPath, 2024) | Educator assessment methodology guide | **Low** — teaches educators how to design assessments; no clinical procedure content | **Exclude** | CC BY-NC-SA 4.0 but no clinical value for MAMAI |
| `nmc-midwifery-marking-criteria.pdf` | **NMC Test of Competence: Midwifery Marking Criteria** (NMC, Feb 2026) | OSCE station marking rubrics | **Moderate** — clinical topics (labour, neonatal assessment, IM injection, complex birth) directly overlap with bedside midwifery; rubric framing is assessment-oriented rather than procedural | **Include (selective)** — station rubrics for clinical skills stations | NMC copyright; permission needed |
| `nmc-midwifery-mock-osce.pdf` | **NMC Test of Competence: Midwifery Mock OSCE** (NMC, Jan 2026) | Mock exam with performance criteria | **Low-moderate** — front matter is professional values criteria; station scenarios likely contain clinical content | **Include (selective)** — station scenario content only | NMC copyright; permission needed |
| `nmc-midwifery-blueprint.pdf` | **NMC Test of Competence: Midwifery Blueprint** (NMC) | Exam competency mapping table | **Low** — signals clinical domains but contains no clinical content | **Exclude** | NMC copyright; no clinical content |
| `nmc-midwifery-cbt-booklet.pdf` | **NMC Test of Competence: Midwifery CBT Candidate Booklet** (NMC, Apr 2025) | Exam candidate information | **Not relevant** — entirely administrative and logistical | **Exclude** | No clinical content |
| `nmc-midwifery-test-specification.pdf` | **NMC Test of Competence: Midwifery Test Specification** (NMC, Mar 2023) | Psychometric design document | **Not relevant** — structural/psychometric design only | **Exclude** | No clinical content |
| `amcb-candidate-handbook.pdf` | **AMCB Certification Exam Candidate Handbook** (AMCB, Jan 2026) | US exam candidate handbook | **Not relevant** — US exam administration and eligibility only | **Exclude** | No clinical content |
| `who-midwifery-educator-core-competencies.pdf` | **Midwifery Educator Core Competencies** (WHO, 2013) | Educator competency framework | **Not relevant** — addresses the educator role, not the practising midwife | **Exclude** | No actionable clinical procedure content |
| `who-platform-malta-guide-for-midwifery-skills.pdf` | **A Guide for Midwifery Skills** (Mater Dei Hospital, Malta, 2013) | Clinical skills procedural guide | **High** — step-by-step clinical procedures: antenatal examination, abdominal assessment, CTG, vaginal examination, positions in labour, examination of placenta, postnatal examination, newborn care and examination | **Include** — high clinical value; some technology-specific chapters (CTG, TENS, water birth) less applicable in low-resource settings | Mater Dei Hospital copyright; strict — written permission required |

---

## Summary — Prioritised Ingestion List

### Ingest now (open license, high relevance)
1. `raw/open-books/msf-essential-obstetric-and-newborn-care.pdf` — pending MSF permission
2. `raw/open-books/A book for midwives...pdf` — pending Hesperian permission
3. `raw/open-books/who-midwifery-education-modules-2.pdf` through `-6.pdf` (PPH, obstructed labour, eclampsia, abortion, sepsis) — pending WHO permission
4. `raw/open-books/who-essential-childbirth-care-course.pdf` — CC BY-NC-SA 3.0 IGO, can ingest now (selective extraction)
5. `raw/open-books/ICM-Essential-Competencies-for-Midwifery-Practice.pdf` — CC BY-NC-SA 4.0, can ingest now

### High priority permission requests
6. `raw/whole-books/midwifery-essentials-6.pdf` (Emergency Maternity Care) — Elsevier
7. `raw/whole-books/Oxford-Handbook-of-Midwifery-3e-PDFDrive-.pdf` — OUP
8. `raw/whole-books/skills-for-midwifery-practice.pdf` — Elsevier
9. `raw/exams/who-platform-malta-guide-for-midwifery-skills.pdf` — Mater Dei Hospital

### Lower priority / pursue after above
10. `raw/whole-books/midwifery-essentials-3.pdf` (Labour) — Elsevier
11. `raw/whole-books/midwifery-essentials-2.pdf` (Antenatal) — Elsevier
12. `raw/whole-books/midwifery-essentials-5.pdf` (Infant Feeding) — Elsevier
13. `raw/exams/nmc-midwifery-marking-criteria.pdf` — NMC
14. `raw/whole-books/Clinical practice guidelines for midwifery and women's...pdf` — Jones & Bartlett

### Exclude (low relevance or poor setting fit)
- `raw/open-books/icm-professional-framework-for-midwifery.pdf`
- `raw/open-books/who-midwifery-education-modules-1.pdf`
- `raw/whole-books/MayesMidwifery.pdf`
- `raw/whole-books/Myles Textbook for Midwives. 16th Edition.pdf`
- `raw/whole-books/Midwifery _ Preparation for Practice...pdf`
- `raw/whole-books/Physiology in Childbearing...pdf`
- `raw/whole-books/Varney's Midwifery(6th Edition)...pdf`
- `raw/whole-books/ACM Guidelines for Consultation and Referral.pdf`
- `raw/exams/icm-essential-competencies-assessment-guide.pdf`
- `raw/exams/nmc-midwifery-blueprint.pdf`
- `raw/exams/nmc-midwifery-cbt-booklet.pdf`
- `raw/exams/nmc-midwifery-test-specification.pdf`
- `raw/exams/amcb-candidate-handbook.pdf`
- `raw/exams/who-midwifery-educator-core-competencies.pdf`
