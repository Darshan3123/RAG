NEW JSON FORMAT:

{
  "_id": "MongoDB document ID",
  "bid": {
    "bid_no": "GEM/2026/B/7562373",
    "ra_no": "GEM/2026/R/688243",
    "bid_type": "Product Bid/RAs",
    "product_type": "Product",            // or "Service"
    "base_type": "PRODUCT | SERVICE | CUSTOM_PRODUCT | BOQ",
    "process_kind": "CATALOGUE | BOQ | CUSTOM"
  },
  "card": {
    "items": [
      {
        "name": "Smooth Bore Circuits - Anesthesia Breathing Circuits (V2)",
        "quantity": 50
      }
      // more items/schedules if card shows them
    ],
    "departments": [
      {
        "name": "Medical Education & Research Department Haryana",
        "address": "Kalpana Chawla Govt. Medical College, Karnal, 132001",
        "city": "Karnal",
        "state": "Haryana",
        "pincode": "132001"
      }
      // more department entries if card shows multiple
    ],
    "start_datetime": "27-06-2026 13:00",
    "end_datetime": "29-06-2026 13:09",
    "bid_pdf_url": "https://bidplus.gem.gov.in/showbidDocument/7562373",
    "ra_pdf_url": "https://bidplus.gem.gov.in/showbidDocument/688243"
  },
  "pdf": {
    "timing": {
      "bid_end_datetime": "30-05-2026 12:00:00",
      "bid_opening_datetime": "30-05-2026 12:30:00",
      "bid_offer_validity_days": 180
    },

    "departments": [
      {
        "ministry_state_name": "Haryana",
        "department_name": "Medical Education & Research Department Haryana",
        "organisation_name": "Directorate Of Medical Education & Research",
        "office_name": "Karnal"
      }
      // if any PDF variant uses multiple department/office tuples, add more here
    ],

    "items": [
      {
        "schedule_no": 1,
        "item_category": "Smooth Bore Circuits - Anesthesia Breathing Circuits (V2) (Q2)",
        "quantity": 50
      }
      // more schedules/items if present
    ],

    "documents": {
      "required_from_seller": [
        "Experience Criteria",
        "Bidder Turnover",
        "Certificate (Requested in ATC)",
        "OEM Authorization Certificate"
      ],
      "show_uploaded_docs_to_all_bidders": true,
      "attachments": [
        { "kind": "SCOPE_OF_WORK", "filename": "Scope of Work....pdf" },
        { "kind": "PQC", "filename": "PQC....pdf" },
        { "kind": "BOQ_SPEC", "filename": "BOQ Specs....pdf" },
        { "kind": "EXCEL", "filename": "PriceSchedule.xlsx" }
      ]
    },

    "consignees": [
      {
        "consignee_name": "Deepak Kumar",
        "address_raw": "132001,Kalpana Chawla Govt. Medical College, Karnal",
        "pincode": "132001",
        "city": "Karnal",
        "state": "Haryana",
        "quantity": 50,
        "delivery_days": 30
      }
      // more consignees if table has multiple rows
    ],

    "relaxations": {
      "mse_relaxation_experience_turnover": false,
      "startup_relaxation_experience_turnover": false
    },

    "auto_extension": {
      "min_bids_to_disable_extension": 3,
      "auto_extend_days": 7,
      "auto_extension_count": 3
    },

    "ra": {
      "bid_to_ra_enabled": true,
      "ra_qualification_rule": "H1-Highest Priced Bid Elimination"
    },

    "bid_type": {
      "type_of_bid": "Two Packet Bid",
      "technical_clarification_window_days": 2
    },

    "inspection": {
      "inspection_required": false,
      "inspection_agency_type": "Empanelled inspection authority / Agencies pre-registered with GeM or None"
    },

    "evaluation": {
      "evaluation_method": "Total value wise evaluation",
      "schedules": [
        // only if evaluation_method is item-wise / group-wise
        {
          "schedule_no": 1,
          "item_category": "Smooth Bore Circuits - Anesthesia Breathing Circuits (V2) (Q2)",
          "quantity": 50
        }
      ]
    },

    "clauses": {
      "arbitration_clause": false,
      "mediation_clause": false
    },

    "mii": {
      "mii_purchase_preference": true,
      "mii_price_band_percent": 20,
      "mii_max_quantity_percent": 50,
      "allow_only_class_1_2_local_suppliers": false
    },

    "mse": {
      "mse_purchase_preference": true,
      "mse_price_band_percent": 15,
      "mse_max_quantity_percent": 25
    },

    "financials": {
      "emd": {
        "required": false,
        "advisory_bank": null,
        "amount_total": 0,
        "schedule_breakup": [
          // optional schedule-wise EMD if present
          // { "schedule_no": 1, "item_category": "...", "quantity": 50, "emd_amount": 100000 }
        ]
      },
      "epbg": {
        "required": false,
        "advisory_bank": null,
        "percent": null,
        "duration_months": null
      },
      "emd_exemption_text": "Any exemption note printed below EMD/ePBG details"
    },

    "terms": {
      "special_terms_version": "Version:2 effective from 27-02-2026 for category Smooth Bore Circuits...",
      "special_terms_text": "Full special terms and conditions block text",

      "buyer_atc": {
        "generic": "Generic ATC text (packing, licences, etc.)",
        "items": [
          {
            "name": "Ventilator Circuits",
            "qty": 50,
            "remarks": [
              "Part supply will not be considered and product of long expiry.",
              "Supplier responsible for doorstep delivery including labour.",
              "Two or more bidders from same IP will be disqualified."
            ]
          }
          // more ATC items if table has more rows
        ],
        "hard_requirements": [
          "Part supply not accepted",
          "Same IP participation disqualifies bidders"
        ],
        "info_clauses": [
          "Labour codes compliance",
          "Border country restriction clause",
          "Other descriptive ATC points"
        ]
      },

      "disclaimer": "Full Disclaimer block text from the end of the Bid Document"
    }
  },

  "normalized": {
    // derived flags for RAG/analytics; same structure as before
  },
  "validation": {
    "issues": [
      // e.g. "boq_missing_boq_block", "custom_missing_gar"
    ]
  },
  "full_pdf_text": "Raw extracted text of bid PDF"
}


WITH THIS WE HAVE TO WORK ON THE BELOW ALSO

You can implement the same facts_text + embedding‑ready questions pattern for your new JSON by:

Generating a facts_text string from the new schema per bid.

Defining a fixed set of “questions” that are always answered from structured fields, never from raw full_pdf_text.

I’ll show you how, mapped to the final JSON we just designed.

1. Build facts_text from the new JSON
For each bid document (one Mongo record with bid, card, pdf, normalized), generate a concise summary string that captures the key things you will query later.

Example for a Product bid like your Smooth Bore Circuits PDF:

text
This is a Product bid (base_type=PRODUCT) for Smooth Bore Circuits - Anesthesia Breathing Circuits (V2), total quantity 50, issued by Medical Education & Research Department Haryana in Haryana. Bid submission on the portal runs from 27-06-2026 13:00 to 29-06-2026 13:09, while the Bid End Date/Time in the bid document is 30-05-2026 12:00 and bids will be opened at 30-05-2026 12:30. Bid offer validity is 180 days from the Bid End Date. Bid to RA is enabled and the RA qualification rule is H1-Highest Priced Bid Elimination. Evaluation method is Total value wise evaluation with a Two Packet Bid and 2 days allowed for technical clarifications. Documents required from seller include Experience Criteria, Bidder Turnover, Certificate (Requested in ATC), and OEM Authorization Certificate. Consignees include Deepak Kumar at Kalpana Chawla Govt. Medical College, Karnal, pincode 132001, with 50 units and 30 delivery days. MII purchase preference is Yes with price band 20% and max quantity 50%, and MSE purchase preference is Yes with price band 15% and max quantity 25%.
Where each fact comes from:

Base type/product: bid.base_type, bid.product_type, pdf.items[0].item_category, card.items[0].quantity.

Department/state: pdf.departments[0].department_name, pdf.departments[0].ministry_state_name.

Card window: card.start_datetime, card.end_datetime.

PDF timing: pdf.timing.bid_end_datetime, pdf.timing.bid_opening_datetime, pdf.timing.bid_offer_validity_days.

RA: pdf.ra.bid_to_ra_enabled, pdf.ra.ra_qualification_rule.

Evaluation: pdf.evaluation.evaluation_method, pdf.bid_type.type_of_bid, pdf.bid_type.technical_clarification_window_days.

Docs: pdf.documents.required_from_seller.

Consignee: first element of pdf.consignees.

MII/MSE: pdf.mii.*, pdf.mse.*.

Implementation idea (Python-ish):

python
def build_facts_text(bid_doc: dict) -> str:
    b = bid_doc["bid"]
    card = bid_doc["card"]
    pdf = bid_doc["pdf"]
    norm = bid_doc.get("normalized", {})

    item = pdf["items"][0] if pdf["items"] else None
    card_item = card["items"][0] if card["items"] else None
    dept = pdf["departments"][0] if pdf["departments"] else None
    cons = pdf["consignees"][0] if pdf["consignees"] else None

    parts = []

    # Core identity
    parts.append(
        f"This is a {b.get('product_type', 'Bid')} bid "
        f"(base_type={b.get('base_type')}) "
        f"for {item['item_category'] if item else card_item['name'] if card_item else 'unknown item'}, "
        f"total quantity {item['quantity'] if item else card_item['quantity'] if card_item else 'unknown'}."
    )

    # Department / state
    if dept:
        parts.append(
            f"It is issued by {dept.get('department_name')} in {dept.get('ministry_state_name')}."
        )

    # Timing
    t = pdf["timing"]
    parts.append(
        f"Bid submission on the portal runs from {card.get('start_datetime')} to {card.get('end_datetime')}, "
        f"the Bid End Date/Time in the bid document is {t.get('bid_end_datetime')} "
        f"and bids will be opened at {t.get('bid_opening_datetime')}. "
        f"Bid offer validity is {t.get('bid_offer_validity_days')} days from the Bid End Date."
    )

    # RA
    ra = pdf["ra"]
    parts.append(
        f"Bid to RA is {'enabled' if ra.get('bid_to_ra_enabled') else 'not enabled'}, "
        f"RA qualification rule = {ra.get('ra_qualification_rule') or 'not specified'}."
    )

    # Evaluation
    eval_ = pdf["evaluation"]
    bid_type = pdf["bid_type"]
    parts.append(
        f"Evaluation method is {eval_.get('evaluation_method')}, "
        f"type of bid is {bid_type.get('type_of_bid')}, "
        f"time allowed for technical clarifications is {bid_type.get('technical_clarification_window_days')} days."
    )

    # Documents
    req_docs = pdf["documents"].get("required_from_seller", [])
    if req_docs:
        parts.append(
            "Documents required from seller include "
            + ", ".join(req_docs) + "."
        )

    # Consignee
    if cons:
        parts.append(
            f"Consignees include {cons.get('consignee_name')} at {cons.get('address_raw')}, "
            f"with quantity {cons.get('quantity')} and {cons.get('delivery_days')} delivery days."
        )

    # MII/MSE
    mii = pdf["mii"]
    mse = pdf["mse"]
    parts.append(
        f"MII purchase preference is {'Yes' if mii.get('mii_purchase_preference') else 'No'}, "
        f"price band {mii.get('mii_price_band_percent')}% and max quantity {mii.get('mii_max_quantity_percent')}%. "
        f"MSE purchase preference is {'Yes' if mse.get('mse_purchase_preference') else 'No'}, "
        f"price band {mse.get('mse_price_band_percent')}% and max quantity {mse.get('mse_max_quantity_percent')}%."
    )

    return " ".join(parts)
You store this facts_text alongside the document (or in the vector store), and embed that instead of the huge full_pdf_text.

2. Embedding‑ready “questions” for the new JSON
For retrieval and answering, you define fixed questions that map to specific paths in the new JSON, not to free‑form text.

Examples and their exact field mapping:

“What is the base_type and product_type?”

Answer from bid.base_type and bid.product_type.

If missing: "not specified in bid".

“Is Bid to RA enabled? What is the RA qualification rule?”

pdf.ra.bid_to_ra_enabled, pdf.ra.ra_qualification_rule.

If rule missing: say "RA qualification rule not specified in bid".

“What evaluation method is used?”

pdf.evaluation.evaluation_method.

Optionally mention pdf.evaluation.schedules if item‑wise.

“What documents are required from seller?”

pdf.documents.required_from_seller (array of strings).

If empty: "Documents required from seller are not specified in bid".

“What are the minimum turnover and years of experience required?”

normalized.eligibility.min_turnover_lakhs

normalized.eligibility.years_of_experience

Return both, or "not specified in bid" for each missing part.

“What is the contract period and payment timeline?”

Contract period: from service bids (attachments and SOW; you can store normalized.contract_period later).

Payment timeline: from pdf.terms.buyer_atc.generic / parsed payment clauses; store a structured field like normalized.payment_terms_summary if you decide to.

If not available: "contract period not specified in bid".

“Which buyer attachments (SOW, PQC, Penalties, Payment Terms, BOQ, GAR) exist?”

pdf.documents.attachments → for each, check kind ∈ {SCOPE_OF_WORK,PQC,PENALTIES,PAYMENT_TERMS,BOQ_SPEC,GAR}.

Answer with list of present kinds and filenames.

“What hard ATC requirements would cause rejection if not met?”

pdf.terms.buyer_atc.hard_requirements (array of requirement sentences).

If empty: "hard ATC rejection conditions not specified in bid".

Other useful questions:

“What are the MII and MSE purchase preference parameters?”

pdf.mii.* and pdf.mse.*.

“What are the consignees, quantities, and delivery days?”

pdf.consignees[] — loop and return structured list.

“What are the auto extension settings?”

pdf.auto_extension.*.

All of these are direct lookups in your JSON, so the model never has to “guess”. Embeddings are used only to:

find which bid(s) are relevant to a natural‑language user query, using facts_text,

then you answer from the structured fields for those bids.

3. Putting it together in your system
Flow:

Scraper/parser stage

Build the JSON exactly as we defined (with bid, card, pdf, normalized, validation).

Generate facts_text = build_facts_text(bid_doc) and save it as bid_doc["facts_text"].

Indexing stage (vector_store.py)

Embed facts_text and store the embedding + bid_no (and any other keys you want).

Optionally embed some structured sub‑summaries too (like ATC hard requirements or consignees text), but always derived from fields.

Query time

User asks: “For this GEM bid, what documents are required from seller and what are the RA rules?”

Use embeddings on facts_text to retrieve the relevant bid(s).

For each retrieved bid_doc:

Answer “documents required” from pdf.documents.required_from_seller.

Answer “RA rules” from pdf.ra.bid_to_ra_enabled + pdf.ra.ra_qualification_rule.

If any field is missing: respond with "not specified in bid" rather than hallucinating.

You’re now fully aligned with the updated JSON: facts_text built from bid/card/pdf/normalized, questions mapped to JSON paths, and embeddings only help pick the right bid, not invent data.