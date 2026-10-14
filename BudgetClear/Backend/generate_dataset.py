import pandas as pd
import random
from datetime import datetime, timedelta

def generate_rigged_dataset():
    # 1. Generate 500 Normal Transactions
    categories = {
        "Office Supplies": ["Printer Paper", "Staplers", "Pens", "Desk Organizers", "Whiteboard Markers"],
        "IT Infrastructure": ["Server Rack", "Ethernet Cables", "Cloud Storage Fees", "Router", "Monitor"],
        "General Logistics": ["Warehouse Shelving", "Pallet Jack", "Shipping Boxes", "Packing Tape", "Forklift Maintenance"]
    }
    
    data = []
    start_date = datetime(2026, 1, 1)
    
    for i in range(1, 501):
        cat = random.choice(list(categories.keys()))
        desc = random.choice(categories[cat])
        date = start_date + timedelta(days=random.randint(0, 200))
        amount = round(random.uniform(50, 4999), 2)
        data.append([f"TX-{1000+i}", date.strftime("%Y-%m-%d"), f"Vendor_{random.randint(1,50)}", cat, desc, amount, f"INV-{1000+i}"])
        
    df = pd.DataFrame(data, columns=["transaction_id", "date", "vendor", "category", "description", "amount", "invoice_number"])
    
    # 2. Inject Anomaly 1: Category Camouflage (AI Target)
    # A luxury item perfectly hidden inside a boring category.
    df.loc[500] = ["TX-9991", "2026-05-12", "Vendor_12", "General Logistics", "Sony PlayStation 5 Console", 499.00, "INV-9991"]
    
    # 3. Inject Anomaly 2 & 3: Fuzzy Duplicates (Record Linkage Target)
    # Same amount, same vendor, slightly perturbed invoice number.
    df.loc[501] = ["TX-9992", "2026-06-01", "TechCorp", "IT Infrastructure", "Dell XPS 15 Laptop", 2500.00, "INV-777"]
    df.loc[502] = ["TX-9993", "2026-06-03", "TechCorp", "IT Infrastructure", "Dell XPS 15 Laptop", 2500.00, "INV-777-A"]
    
    # 4. Inject Anomaly 4-7: Threshold Dodging / Smurfing (Benford's Law Target)
    # 4 consecutive payments of $9,900 to bypass a $10,000 oversight limit.
    for i in range(4):
        date = (datetime(2026, 7, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
        df.loc[503+i] = [f"TX-999{4+i}", date, "Consulting_LLC", "IT Infrastructure", "Network Audit Services", 9900.00, f"INV-888{i}"]
        
    # 5. Inject Deterministic Error: Missing Vendor Name (Layer 1 Target)
    df.loc[507] = ["TX-9998", "2026-07-20", None, "Office Supplies", "Printer Ink", 120.00, "INV-9998"]
    
    # Shuffle so the anomalies aren't all at the bottom, then save.
    df = df.sample(frac=1).reset_index(drop=True)
    df.to_csv("budget_data_rigged.csv", index=False)
    print("Generated 'budget_data_rigged.csv' with 508 rows.")

if __name__ == "__main__":
    generate_rigged_dataset()