import io
import pandas as pd


def read_ledger(content):
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = content.decode('cp1252')
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    df.columns = df.columns.str.strip()
    if 'Transparency Invoice Amount' in df.columns:
        df = pd.DataFrame({
            'transaction_id': [f'DWP-{payment}-L{i + 2}' for i, payment in enumerate(df['Payment Number'])],
            'date': pd.to_datetime(df['Date'], format='%d-%m-%Y').dt.strftime('%Y-%m-%d'),
            'vendor': df['Vendor'], 'category': df['Invoice Cost Centre Description'],
            'description': df['Description'],
            'amount': df['Transparency Invoice Amount'].str.replace('£', '', regex=False).str.replace(',', '', regex=False).str.strip(),
            'invoice_number': '', 'payment_number': df['Payment Number'],
            'currency': 'GBP', 'source_format': 'dwp',
        })
    else:
        df['source_format'] = 'canonical'
        if 'currency' not in df.columns:
            df['currency'] = 'USD'
        df['currency'] = df['currency'].str.strip().str.upper().replace('', 'USD')
        if not df['currency'].isin(['USD', 'GBP']).all():
            raise ValueError('Supported currencies are USD and GBP.')
    required = ['transaction_id', 'date', 'vendor', 'category', 'description', 'amount', 'invoice_number']
    missing = [key for key in required if key not in df.columns]
    if missing:
        raise ValueError(f'Missing columns: {", ".join(missing)}')
    if df.empty:
        raise ValueError('Empty ledger')
    for key in required:
        df[key] = df[key].astype(str).str.strip()
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
    return df


def invalid_rows(df):
    dwp = df.get('source_format', pd.Series('', index=df.index)).eq('dwp')
    required = ['transaction_id', 'date', 'vendor', 'category', 'description', 'amount', 'invoice_number']
    blank = df[required].apply(lambda col: col.isna() | col.astype(str).str.strip().eq(''))
    blank.loc[dwp, 'invoice_number'] = False
    invalid = blank.any(axis=1) | df['amount'].isin([float('inf'), float('-inf')]) | ((df['amount'] < 0) & ~dwp)
    return df[invalid]
