# Item Request Portal

Where plant staff at Carabao Group ask for a new non-stock or service purchase
item, and procurement turns that ask into one standard item in the group master.

## Language

### The request

**Item Request**:
One requester's ask for a new purchase item, from submission until the item
exists in AX/D365 and the requester is told.
_Avoid_: form, ticket, order

**Requester**:
The plant employee who submits an Item Request.
_Avoid_: user, customer

**Originator**:
The plant employee a Procurement-submitted Item Request is made on behalf of.
Receives the request's emails but is not its Requester; if they have an
Account, they may also resubmit it from Needs Info.
_Avoid_: on-behalf person, end user

**Procurement**:
The central team (Peter + 1–2 people) that reviews requests, readies them for
Approval, exports them and imports the result into AX/D365. Only its
Administrators (the Data Steward and backup) may approve.
_Avoid_: admin, approver, buyer

**Approval**:
The Administrator's decision that accepts an Item Request and mints its Central
Code from the Running Register. Cannot be undone: the Running Number stays used.
_Avoid_: sign-off, confirm

### Access

**Account**:
One login to the portal, tied to one email and one Role. A Requester Account
belongs to exactly one Plant. Accounts are deactivated, never deleted, and
their email never changes, because Request history names the Account by email.
_Avoid_: user, login, profile

**Role**:
What an Account may do: Requester, Procurement or Administrator. One Role per
Account.

**Administrator**:
The Role for the central Data Steward and their backup (Peter + one). Can do
everything Procurement can, plus manage Accounts, Snapshots and reference data.
_Avoid_: admin (in prose), superuser

**Plant**:
One of CBD, APM, APG, ACM — the company whose AX/D365 environment the item is
created in.
_Avoid_: factory (in prose), site, company

**Request Status**:
The stage an Item Request is in: submitted → in_review / needs_info → approved
or rejected → exported → created → notified.

**In Review**:
Procurement has checked the request and it waits for an Administrator's
Approval. An Administrator may also approve straight from submitted.
_Avoid_: pending, under review (it means review is done, not ongoing)

**Needs Info**:
Procurement sent the request back to the Requester for missing detail; the
Requester (or the Originator, if any) resubmits it.
_Avoid_: returned, pending

### The item

**Base Name**:
What the Requester calls the thing (ชื่อเรียก), before brand, model, size and
variant are added.
_Avoid_: item name, description

**Item Name**:
The full composed name `[CATEGORY] - [name] - [detail]`, ≤ 110 characters.
Composed by the system, never typed by the Requester.
_Avoid_: product name, description

**Name Prefix**:
The English CATEGORY word(s) at the front of an Item Name, owned by the
Sub-Category.

**Name Override**:
An Item Name Procurement typed in place of the composed one. It stays until a
resubmit composes the name again, or a category move swaps its Name Prefix.
_Avoid_: typed name, manual name

**Variant**:
Type or colour that distinguishes otherwise identical items (ชนิด/สี).

**Search Name**:
The English item-type term AX uses for search and grouping (e.g. `BALL BEARING`),
drawn from the Search Term dictionary.
_Avoid_: short name, keyword

**Service Item**:
An item whose Product Type is Service (7xx groups): work done, not a thing
delivered.
_Avoid_: job item

### Classification

**Item Group**:
Level-1 taxonomy node, 3 digits (7xx service, 9xx non-stock). 20 of them.
_Avoid_: category (alone), group code

**Sub-Category**:
Level-2 taxonomy node, 2 digits (01–99) under an Item Group. 130 of them.
_Avoid_: subgroup, class

**Taxonomy**:
The approved Item Group × Sub-Category tree of the group standard.

**Product Type**:
Item or Service, fixed per Sub-Category.

**Category Suggestion**:
The system's proposed Item Group + Sub-Category for a new request, with a
confidence. Auto-selected only above the threshold; always editable before a
code is issued.

**Procurement Category**:
The spend-reporting category AX needs on the import file. Separate from the
Taxonomy.

### Codes

**Central Code**:
The 11-digit group-wide item code `[Group 3][Sub 2][00][Running 4]`. One per
item, same in every Plant.
_Avoid_: item number, SKU, new code

**Legacy Code**:
An item code issued by a Plant's own scheme before the central standard
(ACM/APM/APG 11-digit with `0000` in digits 4–7; CBD 10-character `64…`).
_Avoid_: old code

**Running Register**:
The single table holding the last Running number issued per Item Group +
Sub-Category. The only source of new Central Codes.
_Avoid_: counter, sequence, max code

**Running Number**:
The last 4 digits of a Central Code.

**Code System**:
A code pattern the portal can issue (CENTRAL, plus legacy patterns kept
inactive).

**Stock Item**:
An item held in inventory (CBD `99…`, future `8xx`). Owned by the stock team and
out of this portal's scope.

### Master data

**Snapshot**:
An uploaded copy of an item master used for duplicate checks and learning; the
portal never reads AX/D365 live.
_Avoid_: master, import (for this meaning)

**Labeled Master**:
A Snapshot whose items already carry Item Group + Sub-Category (the Central
master file). Feeds the Category Suggestion.

**Duplicate Check**:
Fuzzy comparison of a new request against Snapshots to find an existing item
before a new code is issued.

**Unit of Measure (UoM)**:
The unit an item is counted and bought in, from the group's 24-code list.
_Avoid_: unit, UOM code

**UoM Alias**:
A spelling that maps to a canonical UoM (e.g. `pcs` → `EA`). Aliases are added
by an explicit merge, never automatically.

### Export

**Export Batch**:
A set of approved requests written into one Plant's AX/D365 import file at one
time.
_Avoid_: export job, upload

**Import Template**:
The exact column layout AX/D365 of a Plant accepts; one per Plant.

## Relationships

- An **Item Request** belongs to one **Plant** and, once approved, gets exactly
  one **Central Code**.
- A **Central Code** is minted from the **Running Register** row of its
  **Item Group** + **Sub-Category**; changing either after that means a new code.
- An **Export Batch** holds requests of one **Plant** only.
- An **Item Request** is submitted by one **Account**, which is its Requester.
  A Requester Account can only submit for its own **Plant**; Procurement picks
  the Plant and stays the Requester even when asking on someone's behalf;
  that someone is the request's **Originator**.

## Flagged ambiguities

- "category" alone is ambiguous: say **Sub-Category**, **Item Group**, or
  **Procurement Category**.
- "Requester" names both a Role and the submitter of one Item Request. When
  Procurement submits, it is that request's Requester without holding the
  Requester Role.
- "factory" appears in code (`Factory` model) where the language says **Plant**.
