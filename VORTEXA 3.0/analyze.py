from fastapi import FastAPI, HTTPException, Request
from sentence_transformers import SentenceTransformer
import pandas as pd
import numpy as np
import faiss
import recordlinkage
import math

app = FastAPI(title="BudgetClear AI Analysis API")

# Load SBERT model globally into VRAM on startup
# all-MiniLM-L6-v2 is highly optimized (384 dimensions) and handles semantic text fast.
print("Loading SBERT Model...")
model = SentenceTransformer('all-MiniLM-L6-v2')
print("Model loaded successfully.")


def detect_category_camouflage(df: pd.DataFrame, anomaly_threshold: float = 0.60) -> list:
    """
    Uses SBERT and FAISS to detect if a transaction's free-text description
    is semantically distant from its assigned budget category centroid.
    """
    anomalies = []
    
    # Ensure data is clean
    df = df.dropna(subset=['description', 'category']).copy()
    if df.empty: return []

    # 1. Vectorize all invoice descriptions at once for GPU/CPU efficiency
    descriptions = df['description'].tolist()
    embeddings = model.encode(descriptions)
    
    # Normalize vectors in-place (Requirement for FAISS Cosine Similarity)
    faiss.normalize_L2(embeddings)
    df['embedding'] = list(embeddings)

    categories = df['category'].unique()

    # 2. Iterate over each category to build local centroids and search
    for category in categories:
        cat_df = df[df['category'] == category]
        
        # Need enough data to form a reliable centroid
        if len(cat_df) < 3: 
            continue 

        # Compute the centroid (mean vector of all standard items in this category)
        cat_embeddings = np.vstack(cat_df['embedding'].values)
        centroid = np.mean(cat_embeddings, axis=0).reshape(1, -1)
        faiss.normalize_L2(centroid)

        # Build FAISS index for Cosine Similarity (Inner Product on normalized vectors)
        d = centroid.shape[1]
        index = faiss.IndexFlatIP(d)
        index.add(centroid)

        # Compare every item in the category against the centroid
        similarities, _ = index.search(cat_embeddings, 1)
        
        # Convert Cosine Similarity (0 to 1) into an Anomaly Outlier Score
        cat_df = cat_df.copy()
        cat_df['anomaly_score'] = 1.0 - similarities[:, 0]

        # Filter strictly for high-confidence anomalies
        outliers = cat_df[cat_df['anomaly_score'] >= anomaly_threshold]

        for _, row in outliers.iterrows():
            anomalies.append({
                "transaction_id": row['transaction_id'],
                "scheme_detected": "Category Camouflage",
                "confidence_score": round(row['anomaly_score'] * 100, 2),
                "rationale": f"Description '{row['description']}' is semantically distant from standard items in '{category}'."
            })

    return anomalies


def detect_smurfing_benfords_mad(df: pd.DataFrame, mad_critical_value: float = 0.015) -> list:
    """
    Applies Benford's Law Mean Absolute Deviation (MAD) test to catch probability 
    mass spikes (e.g., repeating $9,900 to dodge $10k limits).
    """
    anomalies = []
    
    # 1. Extract leading non-zero digit
    def get_leading_digit(x):
        s = str(float(x)).replace('.', '').lstrip('0')
        return int(s[0]) if s else None
        
    df['leading_digit'] = df['amount'].apply(get_leading_digit)
    df_clean = df.dropna(subset=['leading_digit'])
    
    # 2. Calculate empirical digit frequencies
    observed_probs = df_clean['leading_digit'].value_counts(normalize=True).to_dict()
    
    # 3. Compute MAD against Theoretical Benford Probabilities
    mad = 0
    for d in range(1, 10):
        obs = observed_probs.get(d, 0.0)
        exp = math.log10(1 + 1/d)
        mad += abs(obs - exp)
    mad /= 9
    
    # 4. If dataset distribution is manipulated, isolate the exact clusters
    if mad > mad_critical_value:
        # Find exact recurring high-value amounts per vendor
        vendor_counts = df_clean[df_clean['amount'] > 1000].groupby(['vendor', 'amount']).size()
        suspicious_clusters = vendor_counts[vendor_counts >= 3].reset_index()
        
        for _, cluster in suspicious_clusters.iterrows():
            suspicious_txs = df_clean[(df_clean['vendor'] == cluster['vendor']) & (df_clean['amount'] == cluster['amount'])]
            
            for _, tx in suspicious_txs.iterrows():
                anomalies.append({
                    "transaction_id": tx['transaction_id'],
                    "scheme_detected": "Structuring / Threshold Dodging",
                    "confidence_score": 96.0, # Scaled for PoC
                    "rationale": f"Dataset failed Benford's MAD test (MAD={mad:.4f}). Amount ${cluster['amount']} to '{cluster['vendor']}' is part of an unnatural high-velocity cluster."
                })
                
    return anomalies


def detect_fuzzy_duplicates(df: pd.DataFrame) -> list:
    """
    Uses Locality-Sensitive Hashing (Blocking) and Jaro-Winkler string metrics 
    to catch perturbed invoice strings double-billed for the exact same amount.
    """
    anomalies = []
    df = df.reset_index(drop=True)
    
    # 1. Create candidate pairs blocking by Vendor to reduce search space (LSH equivalent)
    indexer = recordlinkage.Index()
    indexer.block('vendor')
    candidate_links = indexer.index(df, df)
    
    # Remove self-matches and mirrored duplicate pairs
    candidate_links = candidate_links[candidate_links.get_level_values(0) < candidate_links.get_level_values(1)]
    if len(candidate_links) == 0: return anomalies
        
    # 2. Apply Fuzzy String Comparison
    compare = recordlinkage.Compare()
    compare.exact('amount', 'amount', label='amount_match')
    compare.string('invoice_number', 'invoice_number', method='jarowinkler', threshold=0.85, label='invoice_sim')
    
    features = compare.compute(candidate_links, df)
    
    # 3. Flag matches: Exact same amount + highly similar (but not exact) invoice string
    matches = features[(features['amount_match'] == 1) & (features['invoice_sim'] == 1)]
    
    for idx1, idx2 in matches.index:
        tx1, tx2 = df.loc[idx1], df.loc[idx2]
        
        # Ignore if the invoice numbers are 100% identical (SQL UNIQUE constraints usually catch these)
        if tx1['invoice_number'] == tx2['invoice_number']: continue 
            
        anomalies.append({
            "transaction_id": f"{tx1['transaction_id']} / {tx2['transaction_id']}",
            "scheme_detected": "Fuzzy Duplicate Billing",
            "confidence_score": 98.5,
            "rationale": f"Highly similar invoice strings ({tx1['invoice_number']} vs {tx2['invoice_number']}) billed for exact amount ${tx1['amount']}."
        })
        
    return anomalies


@app.post("/api/v1/analyze")
async def analyze_ledger(request: Request):
    """
    Ingests mathematically validated JSON data from Layer 1 and executes the AI analysis.
    """
    payload = await request.json()
    df = pd.DataFrame(payload)
    
    if df.empty:
        raise HTTPException(status_code=400, detail="Empty transaction dataset.")
        
    final_flags = []
    
    # Execute AI Modules sequentially 
    # (In production, run these asynchronously using Celery)
    final_flags.extend(detect_category_camouflage(df))
    final_flags.extend(detect_smurfing_benfords_mad(df))
    final_flags.extend(detect_fuzzy_duplicates(df))
    
    # Rank anomalies by severity/confidence
    final_flags = sorted(final_flags, key=lambda x: x['confidence_score'], reverse=True)
    
    return {
        "status": "success",
        "total_anomalies_flagged": len(final_flags),
        "disclaimer": "An anomaly flag is a statistical deviation, not proof of fraud or corruption. All flags require independent human verification.",
        "results": final_flags
    }