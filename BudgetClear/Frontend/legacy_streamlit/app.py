import streamlit as st
import pandas as pd
import requests
import io
import os

# Configure the dashboard layout
st.set_page_config(page_title="BudgetClear", layout="wide")

st.title("BudgetClear: AI-Powered Forensic Auditor")
st.markdown("Upload government procurement ledgers to identify mathematically balanced fraud schemes.")

INGEST_API_URL = os.getenv("BUDGETCLEAR_INGEST_API_URL", "http://localhost:8000/api/v1")
ANALYZE_API_URL = os.getenv("BUDGETCLEAR_ANALYZE_API_URL", "http://localhost:8001/api/v1")

# File Upload Module
uploaded_file = st.file_uploader("Upload Department Ledger (CSV)", type=["csv"])

if uploaded_file is not None:
    st.info("File uploaded successfully. Awaiting deterministic validation...")
    
    # ---------------------------------------------------------
    # Layer 1: Deterministic Engine (Hard Math)
    # ---------------------------------------------------------
    if st.button("Step 1: Run Deterministic Math Validation", type="primary"):
        with st.spinner("Executing mathematical baseline checks..."):
            # Post the raw CSV file to the backend
            files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "text/csv")}
            
            try:
                response = requests.post(f"{INGEST_API_URL}/ingest", files=files)
                data = response.json()
                
                if response.status_code == 200 and data.get("status") == "success":
                    st.success(f"✅ {data['message']}")
                    # Store validated data in session state for Layer 2
                    st.session_state['validated_csv'] = uploaded_file.getvalue()
                else:
                    st.error(f"❌ {data.get('reason', 'Validation failed')}")
                    if "failed_rows" in data:
                        st.write("Corrupted Rows (Missing Data or Math Errors):", data["failed_rows"])
            except requests.exceptions.ConnectionError:
                st.error("Failed to connect to backend. Ensure FastAPI is running on port 8000.")

    # ---------------------------------------------------------
    # Layer 2: Probabilistic AI Engine (Behavioral Flags)
    # ---------------------------------------------------------
    if 'validated_csv' in st.session_state:
        st.markdown("---")
        
        if st.button("Step 2: Run Probabilistic AI Audit", type="secondary"):
            with st.spinner("Analyzing semantics, statistical distributions, and fuzzy string topologies..."):
                # Parse the mathematically validated CSV and send as JSON
                df = pd.read_csv(io.BytesIO(st.session_state['validated_csv']))
                payload = df.to_dict(orient="records")
                
                try:
                    response = requests.post(f"{ANALYZE_API_URL}/analyze", json=payload)
                    
                    if response.status_code == 200:
                        results = response.json()
                        st.subheader(f"⚠️ Unified Evidence Report: {results['total_anomalies_flagged']} Anomalies Detected")
                        
                        if results['total_anomalies_flagged'] > 0:
                            anomalies_df = pd.DataFrame(results['results'])
                            
                            # Format confidence scores for visual triage
                            def highlight_confidence(val):
                                color = '#ff4b4b' if val > 95 else '#ffa500'
                                return f'color: {color}; font-weight: bold'
                                
                            st.dataframe(
                                anomalies_df.style.map(highlight_confidence, subset=['confidence_score']),
                                use_container_width=True,
                                height=250
                            )
                        else:
                            st.success("No behavioral anomalies detected in this ledger.")
                            
                        # Mandatory Legal Guardrail
                        st.error(f"⚖️ **MANDATORY LEGAL DISCLAIMER:** {results['disclaimer']}")
                    else:
                        st.error("AI Analysis failed to process the request.")
                except requests.exceptions.ConnectionError:
                    st.error("Failed to connect to backend. Ensure FastAPI is running on port 8000.")
