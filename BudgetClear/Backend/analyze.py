from functools import lru_cache
import math
import threading

from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
import pandas as pd
import numpy as np
import faiss

from services import get_current_user, load_records
from ai_explanations import explain_flags

app = FastAPI(title="BudgetClear AI Analysis API")
_model_lock = threading.Lock()


@lru_cache(maxsize=1)
def get_model():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name='sentence-transformers/all-MiniLM-L6-v2', threads=2)


def evidence(row, role="flagged record"):
    keys = ("evidence_id", "source_file_id", "source_filename", "source_record_number", "source_sha256",
            "transaction_id", "date", "vendor", "amount", "currency", "description", "category", "invoice_number")
    result = {key: row.get(key, "") for key in keys}
    result["amount"] = float(result["amount"])
    result["source_record_number"] = int(result["source_record_number"])
    result["role"] = role
    return result


def make_flag(row, scheme, score, rationale, basis, metrics, related=(), required=None):
    primary = evidence(row)
    refs = [primary]
    seen = {primary["evidence_id"]}
    for other, role in related:
        if other["evidence_id"] not in seen:
            refs.append(evidence(other, role))
            seen.add(other["evidence_id"])
    return {"transaction_id": str(row["transaction_id"]), "scheme_detected": scheme,
            "confidence_score": round(max(0, min(100, float(score))), 2),
            "confidence_basis": basis, "score_type": "heuristic_signal_strength",
            "rationale": rationale, "detector_rationale": rationale, "metrics": metrics,
            "primary_evidence_id": primary["evidence_id"], "evidence": refs,
            "required_evidence_ids": required or [primary["evidence_id"]]}


def detect_category_camouflage(df, anomaly_threshold=0.60):
    flags = []
    df = df.dropna(subset=["description", "category"]).copy()
    df = df[df["category"] != "Uncategorized"]
    if df.empty or not (df.groupby("category").size() >= 3).any():
        return flags
    unique_descriptions, inverse = np.unique(df["description"].astype(str).to_numpy(), return_inverse=True)
    with _model_lock:
        unique_embeddings = np.asarray(list(get_model().embed(unique_descriptions.tolist(), batch_size=32)), dtype=np.float32)
    embeddings = unique_embeddings[inverse]
    faiss.normalize_L2(embeddings)
    df["embedding"] = list(embeddings)
    for category, group in df.groupby("category"):
        if len(group) < 3:
            continue
        vectors = np.vstack(group["embedding"].values)
        centroid = np.mean(vectors, axis=0).reshape(1, -1)
        faiss.normalize_L2(centroid)
        index = faiss.IndexFlatIP(centroid.shape[1])
        index.add(centroid)
        similarities, _ = index.search(vectors, 1)
        similarities = similarities[:, 0]
        for position, (_, row) in enumerate(group.iterrows()):
            distance = float(1 - similarities[position])
            if distance < anomaly_threshold:
                continue
            peer_positions = [int(i) for i in np.argsort(-similarities) if i != position][:3]
            peers = [(group.iloc[i], "category reference sample") for i in peer_positions]
            flags.append(make_flag(row, "Category Camouflage", distance * 100,
                f"Description differs from the '{category}' category centroid (cosine distance {distance:.3f}; review threshold {anomaly_threshold:.2f}).",
                "100 × cosine distance from the category centroid, capped at 100. Signal strength; not a calibrated probability.",
                {"cosine_distance": round(distance, 6), "review_threshold": anomaly_threshold,
                 "category": str(category), "category_records": len(group), "reference_sample_count": len(peers)}, peers))
    return flags


def detect_smurfing_benfords_mad(df, mad_critical_value=0.015):
    flags = []
    df = df[df["amount"] > 0].copy()
    if len(df) < 100:
        return flags
    def leading_digit(value):
        return int(format(float(value), ".15e")[0])
    observed = df["amount"].map(leading_digit).value_counts(normalize=True).to_dict()
    mad = sum(abs(observed.get(d, 0) - math.log10(1 + 1 / d)) for d in range(1, 10)) / 9
    if mad <= mad_critical_value:
        return flags
    for (vendor, amount), group in df[df["amount"] > 1000].groupby(["vendor", "amount"]):
        if len(group) < 3:
            continue
        sample = list(group.head(10).iterrows())
        for _, row in group.iterrows():
            peers = [(other, "same vendor and amount") for _, other in sample if other["evidence_id"] != row["evidence_id"]][:9]
            flags.append(make_flag(row, "Repeated Payment / Benford Deviation", min(100, mad / 0.1 * 100),
                f"{len(group)} payments of {row.get('currency', 'USD')} {amount:,.2f} to '{vendor}' repeat in a ledger with Benford MAD {mad:.4f}. Review for legitimate recurring costs or duplicate payments.",
                "100 × dataset Benford MAD / 0.10, capped at 100; a heuristic distribution score shared by this cluster, not a fraud probability.",
                {"benford_mad": round(mad, 6), "review_threshold": mad_critical_value,
                 "population_records": len(df), "cluster_records": len(group), "repeated_amount": float(amount),
                 "observed_digit_frequencies": {str(k): float(v) for k, v in observed.items()}}, peers))
    return flags


def detect_fuzzy_duplicates(df):
    import recordlinkage
    df = df[df["invoice_number"].astype(str).str.strip().ne("")].reset_index(drop=True)
    if len(df) < 2:
        return []
    sizes = df.groupby(["vendor", "amount"]).size()
    if int((sizes * (sizes - 1) // 2).sum()) > 100_000:
        raise HTTPException(413, "Too many identical vendor/amount combinations. Split this ledger into smaller audits.")
    indexer = recordlinkage.Index()
    indexer.block(["vendor", "amount"])
    candidate_links = indexer.index(df)
    if len(candidate_links) == 0:
        return []
    compare = recordlinkage.Compare()
    compare.string("invoice_number", "invoice_number", method="jarowinkler", label="invoice_similarity")
    features = compare.compute(candidate_links, df)
    flags = []
    for (left, right), metrics in features[features["invoice_similarity"] >= 0.85].iterrows():
        a, b = df.loc[left], df.loc[right]
        similarity = float(metrics["invoice_similarity"])
        flag = make_flag(a, "Fuzzy Duplicate Billing", similarity * 100,
                         f"Invoices '{a['invoice_number']}' and '{b['invoice_number']}' have {similarity * 100:.1f}% string similarity with the same vendor and amount. Review both source records.",
                         "Jaro-Winkler invoice similarity × 100, conditional on identical vendor and amount. Match strength; not a fraud probability.",
                         {"invoice_similarity": round(similarity, 6), "review_threshold": 0.85,
                          "vendor_matches": True, "amount_matches": True},
                         [(b, "possible duplicate")], [a["evidence_id"], b["evidence_id"]])
        flag["transaction_id"] = f"{a['transaction_id']} / {b['transaction_id']}"
        flags.append(flag)
    return flags


def detect(records):
    df = pd.DataFrame(records)
    if df.empty:
        raise HTTPException(400, "Empty transaction dataset.")
    flags = detect_category_camouflage(df)
    full_ledger = df[df["source_format"] != "dwp"].copy() if "source_format" in df else df
    if not full_ledger.empty:
        flags.extend(detect_smurfing_benfords_mad(full_ledger))
        flags.extend(detect_fuzzy_duplicates(full_ledger))
    flags.sort(key=lambda flag: flag["confidence_score"], reverse=True)
    for index, flag in enumerate(flags, 1):
        flag["flag_id"] = f"FLAG-{index:05d}"
    return flags


class AnalysisInput(BaseModel):
    source_ids: list[str] = Field(min_length=1, max_length=50)


@app.post("/api/v1/analyze")
async def analyze_ledger(data: AnalysisInput, user: dict = Depends(get_current_user)):
    records = await run_in_threadpool(load_records, user, data.source_ids)
    flags = await run_in_threadpool(detect, records)
    flags = await explain_flags(flags)
    return {"status": "success", "total_anomalies_flagged": len(flags), "records": records,
            "explanation_summary": {"ai": sum(f["explanation_source"] == "ai" for f in flags),
                                    "detector": sum(f["explanation_source"] == "detector" for f in flags)},
            "disclaimer": "Confidence measures detector signal strength. All flags require independent human review.",
            "results": flags}
