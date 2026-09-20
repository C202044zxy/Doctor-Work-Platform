"""M4-04 server-side checks shared by preflight, create and modify."""

import re
from decimal import Decimal

from fastapi import HTTPException

from app.allergies import allergen_name, get_patient_allergens
from app.emr_models import Drug

FREQUENCIES = {"qd": 1, "bid": 2, "tid": 3, "qid": 4}
UNITS = {"mg": Decimal(1), "g": Decimal(1000), "mcg": Decimal("0.001")}
RANK = {"passed": 0, "warning": 1, "blocked": 2}


def validate_orders(db, patient_no, items):
    allergies = get_patient_allergens(db, patient_no)
    results = []
    for index, item in enumerate(items):
        reasons = []
        if item.order_type == "drug":
            if not item.dose:
                raise HTTPException(422, f"items.{index}.dose is required")
            drug = db.get(Drug, item.drug_code)
            if drug is None:
                raise HTTPException(422, f"items.{index}.drug_code is unknown")
            match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(mg|g|mcg|tablets?)\s*", item.dose)
            if not match or Decimal(match[1]) <= 0:
                raise HTTPException(
                    422, f"items.{index}.dose must be a positive quantity with units"
                )
            if item.frequency not in FREQUENCIES:
                raise HTTPException(422, f"items.{index}.frequency must be qd, bid, tid or qid")
            rule = drug.dose_rule
            unit = "tablets" if match[2].startswith("tablet") else match[2]
            value = Decimal(match[1])
            if unit != rule["unit"]:
                if unit not in UNITS or rule["unit"] not in UNITS:
                    raise HTTPException(422, f"items.{index}.dose has incompatible units")
                value *= UNITS[unit] / UNITS[rule["unit"]]
            if rule["daily"]:
                value *= FREQUENCIES[item.frequency]
            for allergy in allergies:
                if allergy.allergen in drug.contraindications:
                    reasons.append(
                        {
                            "kind": "allergy",
                            "severity": allergy.severity,
                            "allergen": allergy.allergen,
                            "message": f"Patient is allergic to {allergen_name(allergy.allergen)}; this order is blocked.",
                        }
                    )
            if not Decimal(str(rule["min"])) <= value <= Decimal(str(rule["max"])):
                normal = f"{rule['min']:g}-{rule['max']:g}{rule['unit']}" + (
                    "/day" if rule["daily"] else "/dose"
                )
                reasons.append(
                    {
                        "kind": "dose",
                        "normal_range": normal,
                        "observed": item.dose,
                        "message": f"Usual dose {normal}; this order is {item.dose} {item.frequency}.",
                    }
                )
        status = (
            "blocked"
            if any(r["kind"] == "allergy" for r in reasons)
            else "warning"
            if reasons
            else "passed"
        )
        results.append({"index": index, "status": status, "reasons": reasons})
    return {"overall": max((r["status"] for r in results), key=RANK.get), "results": results}
