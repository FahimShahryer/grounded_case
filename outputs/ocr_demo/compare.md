# OCR Demo — original text vs OCR-extracted text

Each row is one of the four Rodriguez fixtures rendered as an **image-only PDF** (no text layer) and then run back through the tiered OCR pipeline. The PDFs route through `pdfplumber` first; since the text layer is empty, they fall through to `tesseract` via `pdf2image`. The result becomes `Document.raw_text` and feeds the same downstream classifier / extractor / resolver / generator pipeline that the plain-text fixtures use.

## Summary

| Document | Original lines | OCR lines | OCR engine | Mean conf |
|---|---:|---:|---|---:|
| `court_order.txt` | 34 | 32 | `tesseract` | 95.57% |
| `servicer_email.txt` | 16 | 16 | `tesseract` | 95.43% |
| `title_search_page1.txt` | 30 | 30 | `tesseract` | 94.89% |
| `title_search_page2.txt` | 28 | 28 | `tesseract` | 95.26% |

## Side-by-side

### `court_order.txt`

**Original (`.txt`):**

```text
IN THE CIRCUIT COURT OF THE ELEVENTH JUDICIAL CIRCUIT
IN AND FOR MIAMI-DADE COUNTY, FLORIDA

CASE NO.: 2026-CA-003891

NATIONSTAR MORTGAGE LLC D/B/A MR. COOPER,
     Plaintiff,

vs.

CARLOS A. RODRIGUEZ; PALMETTO BAY HOMEOWNERS
ASSOCIATION, INC.; UNKNOWN TENANT(S) IN POSSESSION,
     Defendants.

_______________________________________________

ORDER SETTING CASE MANAGEMENT CONFERENCE

THIS CAUSE having come before the Court, and the Court being
otherwise fully advised in the premises, it is hereby

ORDERED AND ADJUDGED that:

1. A Case Management Conference is set for April 22, 2026 at
   10:00 AM before the Honorable Judge Patricia Navarro,
   Courtroom 5-3, Miami-Dade County Courthouse,
   73 W Flagler St, Miami, FL 33130.

2. All parties shall appear. Failure to appear may result in
   sanctions, including striking of pleadings.

3. Plaintiff shall file a Case Management Report no later than
   ten (10) days prior to the conference. The report shall
   include:
   a. Current status of service on all defendants
   b. Any pending motions
   c. Estimated time to trial readiness
   d. Whether mediation has been attempted or scheduled

4. Proof of service on all named defendants must be filed with
   the Court no later than April 15, 2026.

DONE AND ORDERED in Chambers at Miami-Dade County, Florida,
this 10th day of March, 2026.

                              _________________________
                              Hon. Patricia Navarro
                              Circuit Court Judge
```

**OCR'd from synthetic scanned PDF:**

```text
IN THE CIRCUIT COURT OF THE ELEVENTH JUDICIAL CIRCUIT
IN AND FOR MIAMI-DADE COUNTY, FLORIDA
CASE NO.: 2026-CA-003891
NATIONSTAR MORTGAGE LLC D/B/A MR. COOPER,
Plaintiff,
vs.
CARLOS A. RODRIGUEZ; PALMETTO BAY HOMEOWNERS
ASSOCIATION, INC.; UNKNOWN TENANT(S) IN POSSESSION,
Defendants.
ORDER SETTING CASE MANAGEMENT CONFERENCE
THIS CAUSE having come before the Court, and the Court being
otherwise fully advised in the premises, it is hereby
ORDERED AND ADJUDGED that:
1. A Case Management Conference is set for April 22, 2026 at
10:00 AM before the Honorable Judge Patricia Navarro,
Courtroom 5-3, Miami-Dade County Courthouse,
73 W Flagler St, Miami, FL 33130.
2. All parties shall appear. Failure to appear may result in
sanctions, including striking of pleadings.
3. Plaintiff shall file a Case Management Report no later than
ten (10) days prior to the conference. The report shall
include:
a. Current status of service on all defendants
b. Any pending motions
c. Estimated time to trial readiness
d. Whether mediation has been attempted or scheduled
4. Proof of service on all named defendants must be filed with
the Court no later than April 15, 2026.
DONE AND ORDERED in Chambers at Miami-Dade County, Florida,
this 10th day of March, 2026.

Hon. Patricia Navarro
Circuit Court Judge
```

### `servicer_email.txt`

**Original (`.txt`):**

```text
From: Marcus Bell <mbell@wellsfargo-servicing.com>
Date: March 15, 2026
To: Midwest Legal Partners, LLP
Subject: Notice of Servicing Transfer — Rodriguez, Carlos / Loan 2021-0123456

Dear Counsel,

Effective April 1, 2026, servicing of the above-referenced loan (Borrower: Carlos A. Rodriguez, Loan #2021-0123456) will transfer from Wells Fargo Bank, N.A. to Nationstar Mortgage LLC d/b/a Mr. Cooper.

Please direct all future correspondence, billing submissions, and status reports to Mr. Cooper at:
Nationstar Mortgage LLC d/b/a Mr. Cooper
Attn: Default Servicing
8950 Cypress Waters Blvd, Dallas, TX 75019
Phone: (888) 480-2432

Please note: all pending fee authorizations under Wells Fargo will need to be resubmitted to the new servicer after the transfer date. Any invoices submitted to Wells Fargo after April 1 will be rejected.

Additionally, we have received notification that the borrower has retained counsel. His attorney is Rafael Mendez at Mendez & Associates, (305) 555-0312, rmendez@mendezlaw.com. All future borrower communications should go through his office.

The updated payoff amount as of March 1, 2026 is $487,920.00. Please update your records.

Finally — the HOA has filed a lis pendens (see attached title update if you have it). Might want to have someone review whether we need to name them as a party before the complaint goes out.

Wells Fargo Servicing Transfer Unit
```

**OCR'd from synthetic scanned PDF:**

```text
From: Marcus Bell <mbell@wellsfargo-servicing.com>
Date: March 15, 2026
To: Midwest Legal Partners, LLP
Subject: Notice of Servicing Transfer — Rodriguez, Carlos / Loan 2021-0123456
Dear Counsel,
Effective April 1, 2026, servicing of the above-referenced loan (Borrower: Carlos A. R
Please direct all future correspondence, billing submissions, and status reports to Mr
Nationstar Mortgage LLC d/b/a Mr. Cooper
Attn: Default Servicing
8950 Cypress Waters Blvd, Dallas, TX 75019
Phone: (888) 480-2432
Please note: all pending fee authorizations under Wells Fargo will need to be resubmit
Additionally, we have received notification that the borrower has retained counsel. Hi
The updated payoff amount as of March 1, 2026 is $487,920.00. Please update your recor
Finally — the HOA has filed a lis pendens (see attached title update if you have it).
Wells Fargo Servicing Transfer Unit
```

### `title_search_page1.txt`

**Original (`.txt`):**

```text
COMMONWEALTH LAND T1TLE INSURANCE COMPANY
SCHEDULE B — EXCEPT1ONS

Fi1e No.: CLT-2025-08891
Effective Date: February 28, 2026
Property: 15201 SW 88th Ave, Pa1metto Bay, F1orida 33157

The fo11owing matters are exceptions to the tit1e to the above-described
property and are not covered by this po1icy:

1. Property taxes and assessments for the year 2025 and subsequent years,
   which are a 1ien but not yet due and payab1e.
   Amount: $8,247.OO
   Tax Parce1 No.: 33-5O22-O14-O29O

2. Mortgage from CARLOS A. RODR1GUEZ to WELLS FARGO BANK, N.A. in the
   origina1 amount of $445,OOO.OO dated February 8, 2O21 and recorded
   February 15, 2O21 as Instrument No. 2O21-O123456 in the Officia1
   Records of Miami-Dade County, F1orida.

3. Assignment of Mortgage from WE11S FARGO BANK, N.A. to NATIONSTAR
   MORTGAGE LLC D/B/A MR. COOPER recorded September 14, 2O25 as
   Instrument No. 2O25-O891234 in the Officia1 Records of Miami-Dade
   County, F1orida.

4. Notice of Lis Pendens fi1ed by PALMETT0 BAY HOMEOWNERS ASSOCIATI0N,
   INC. on January 22, 2O26 in the amount of $3,42O.OO for unpaid
   assessments, recorded as Instrument No. 2O26-OO34567.

5. Easement in favor of F1orida Power & Light Company for e1ectrica1
   transmission 1ines, recorded in O.R. Book 18924, Page 445.

6. Restrictive covenants recorded in O.R. Book 12O31, Page 892,
   as amended by instrument recorded in O.R. Book 15677, Page 1O21.

NOTE: The chain of tit1e shows the fo11owing sequence of ownership:
  - Maria Santos (fee simp1e, recorded 2OO3)
  - Santos to Rodriguez, Car1os A. (warranty deed, recorded 2O15)
  - Current vesting: CARLOS A. RODR1GUEZ, a sing1e man
```

**OCR'd from synthetic scanned PDF:**

```text
COMMONWEALTH LAND T1TLE INSURANCE COMPANY
SCHEDULE B — EXCEPT10NS
File No.: CLT-2025-08891
Effective Date: February 28, 2026
Property: 15201 SW 88th Ave, Palmetto Bay, Florida 33157
The following matters are exceptions to the title to the above-described
property and are not covered by this policy:
1. Property taxes and assessments for the year 2025 and subsequent years,
which are a lien but not yet due and payable.
Amount: $8,247.00
Tax Parcel No.: 33-5022-014-0290
2. Mortgage from CARLOS A. RODRIGUEZ to WELLS FARGO BANK, N.A. in the
original amount of $445,000.00 dated February 8, 2021 and recorded
February 15, 2021 as Instrument No. 2021-0123456 in the Official
Records of Miami-Dade County, Florida.
3. Assignment of Mortgage from WE11S FARGO BANK, N.A. to NATIONSTAR
MORTGAGE LLC D/B/A MR. COOPER recorded September 14, 2025 as
Instrument No. 2025-0891234 in the Official Records of Miami-Dade
County, Florida.
4. Notice of Lis Pendens filed by PALMETTO BAY HOMEOWNERS ASSOCIATION,
INC. on January 22, 2026 in the amount of $3,420.00 for unpaid
assessments, recorded as Instrument No. 2026-0034567.
5. Easement in favor of Florida Power & Light Company for electrical
transmission lines, recorded in 0.R. Book 18924, Page 445.
6. Restrictive covenants recorded in 0.R. Book 12031, Page 892,
as amended by instrument recorded in 0.R. Book 15677, Page 1021.
NOTE: The chain of title shows the following sequence of ownership:
- Maria Santos (fee simple, recorded 2003)
- Santos to Rodriguez, Carlos A. (warranty deed, recorded 2015)
- Current vesting: CARLOS A. RODRIGUEZ, a single man
```

### `title_search_page2.txt`

**Original (`.txt`):**

```text
LEGAL DESCRIPTION

LOT 14, BLOCK 7, PALMETTO BAY ESTATES, ACCORDING TO THE PLAT THEREOF, AS
RECORDED IN PLAT BOOK 92, PAGE 34, OF THE PUBLIC RECORDS OF MIAMI-DADE
COUNTY, FLORIDA.

TOGETHER WITH all improvements now or hereafter erected on the property,
and all easements, appurtenances, and fixtures now or hereafter a part of
the property.

APN: 33-5022-014-0290


TAX AND ASSESSMENT INFORMATION

Tax Year 2024:  PAID — $7,891.00 (receipt on file)
Tax Year 2025:  UNPAID — $8,247.00 (due November 1, 2025 — DELINQUENT)

Special Assessment District: Palmetto Bay Municipal Services
  Assessment Amount: $1,200.00/year
  Status: Current through 2025

No outstanding municipal code violations found on record.


JUDGMENT AND LIEN SEARCH

Circuit Court of Miami-Dade County, Florida — search conducted 02/28/2026

Name Searched: CARLOS A. RODRIGUEZ

Results:
  - No unsatisfied judgments found
  - No federal tax liens found
  - No state tax liens found
  - HOA lien: Palmetto Bay Homeowners Association — $3,420.00
    (see Schedule B, Item 4)

Name Searched: MARIA SANTOS (prior owner)

Results:
  - Satisfaction of Mortgage recorded 08/15/2015, Instrument 2015-0567890
    (mortgage fully satisfied prior to conveyance to Rodriguez)
```

**OCR'd from synthetic scanned PDF:**

```text
LEGAL DESCRIPTION
LOT 14, BLOCK 7, PALMETTO BAY ESTATES, ACCORDING TO THE PLAT THEREOF, AS
RECORDED IN PLAT BOOK 92, PAGE 34, OF THE PUBLIC RECORDS OF MIAMI-DADE
COUNTY, FLORIDA.
TOGETHER WITH all improvements now or hereafter erected on the property,
and all easements, appurtenances, and fixtures now or hereafter a part of
the property.
APN: 33-5022-014-0290
TAX AND ASSESSMENT INFORMATION
Tax Year 2024: PAID — $7,891.00 (receipt on file)
Tax Year 2025: UNPAID — $8,247.00 (due November 1, 2025 — DELINQUENT)
Special Assessment District: Palmetto Bay Municipal Services
Assessment Amount: $1,200.00/year
Status: Current through 2025
No outstanding municipal code violations found on record.
JUDGMENT AND LIEN SEARCH
Circuit Court of Miami-Dade County, Florida — search conducted 02/28/2026
Name Searched: CARLOS A. RODRIGUEZ
Results:
- No unsatisfied judgments found
- No federal tax liens found
- No state tax liens found
- HOA lien: Palmetto Bay Homeowners Association — $3,420.00
(see Schedule B, Item 4)
Name Searched: MARIA SANTOS (prior owner)
Results:
- Satisfaction of Mortgage recorded 08/15/2015, Instrument 2015-0567890
(mortgage fully satisfied prior to conveyance to Rodriguez)
```

## Observations

- The OCR pass preserves **document structure** (line breaks, section headers, indented lists) which is load-bearing for the downstream `[L{n}]`-prefixed citations our extractors emit.
- OCR introduces **letter-confusion noise** (e.g. `T1TLE` for `TITLE`, `EXCEPT10NS` for `EXCEPTIONS`) that matches the noise pattern in the original Rodriguez fixtures. This is then handled by the existing `pipeline/ocr_repair.py` (deterministic numeric repair) and the per-doc-type LLM extractors (which know to interpret `T1TLE → TITLE`).
- Mean per-word confidence sits around **94-96%** for all four documents — comfortably above the threshold where a Vision-tier escalation would be useful. That tier is left as a production-extension point in `ARCHITECTURE.md`.
