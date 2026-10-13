import io
import pandas as pd

SUPPORTED_CURRENCIES = {'USD', 'GBP', 'INR', 'EUR'}
COLUMN_ALIASES = {
    'transaction_id': ('transaction id', 'transaction number', 'transaction no', 'payment id', 'payment number', 'reference', 'reference number'),
    'date': ('transaction date', 'payment date', 'invoice date', 'date paid'),
    'vendor': ('payee', 'supplier', 'supplier name', 'vendor name', 'merchant', 'recipient', 'beneficiary'),
    'category': ('expense category', 'spend category', 'account category', 'cost centre', 'cost center', 'department'),
    'description': ('transaction description', 'payment description', 'invoice description', 'details', 'item description', 'narrative', 'purpose'),
    'amount': ('payment amount', 'invoice amount', 'total amount', 'disbursed amount', 'value', 'gross amount', 'net amount'),
    'invoice_number': ('invoice number', 'invoice no', 'invoice id', 'bill number', 'bill no', 'bill id'),
}

def _header_key(name):
    return ' '.join(str(name).strip().lower().replace('_', ' ').replace('-', ' ').split())


def read_ledger(content, currency=None):
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = content.decode('cp1252')
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    df.columns = df.columns.str.strip()
    if currency is not None:
        currency = currency.strip().upper()
        if currency not in SUPPORTED_CURRENCIES:
            raise ValueError('Choose USD, GBP, INR, or EUR.')
    if 'Transparency Invoice Amount' in df.columns:
        df = pd.DataFrame({
            'transaction_id': [f'DWP-{payment}-L{i + 2}' for i, payment in enumerate(df['Payment Number'])],
            'date': pd.to_datetime(df['Date'], format='%d-%m-%Y').dt.strftime('%Y-%m-%d'),
            'vendor': df['Vendor'], 'category': df['Invoice Cost Centre Description'],
            'description': df['Description'],
            'amount': df['Transparency Invoice Amount'].str.replace('£', '', regex=False).str.replace(',', '', regex=False).str.strip(),
            'invoice_number': '', 'payment_number': df['Payment Number'],
            'currency': currency or 'GBP', 'source_format': 'dwp',
        })
    else:
        keyed = {_header_key(column): column for column in df.columns}
        rename = {}
        for target, aliases in COLUMN_ALIASES.items():
            if target not in df.columns:
                match = next((keyed[alias] for alias in (_header_key(target), *aliases) if alias in keyed), None)
                if match:
                    rename[match] = target
        df = df.rename(columns=rename)
        df['source_format'] = 'canonical'
        if currency:
            df['currency'] = currency
        elif 'currency' not in df.columns:
            df['currency'] = 'USD'
        df['currency'] = df['currency'].str.strip().str.upper().replace('', 'USD')
        if not df['currency'].isin(SUPPORTED_CURRENCIES).all():
            raise ValueError('Supported currencies are USD, GBP, INR, and EUR.')
    required = ['transaction_id', 'date', 'vendor', 'category', 'description', 'amount', 'invoice_number']
    missing = [key for key in required if key not in df.columns]
    if missing:
        raise ValueError(f'Missing columns: {", ".join(missing)}')
    if df.empty:
        raise ValueError('Empty ledger')
    for key in required:
        df[key] = df[key].astype(str).str.strip()
    df['amount'] = pd.to_numeric(df['amount'].astype(str).str.replace(r'[£$₹€,\s]', '', regex=True), errors='coerce')
    return df


def invalid_rows(df):
    dwp = df.get('source_format', pd.Series('', index=df.index)).eq('dwp')
    required = ['transaction_id', 'date', 'vendor', 'category', 'description', 'amount', 'invoice_number']
    blank = df[required].apply(lambda col: col.isna() | col.astype(str).str.strip().eq(''))
    blank.loc[dwp, 'invoice_number'] = False
    if 'invoice_number_missing' in df.columns:
        blank.loc[df['invoice_number_missing'].astype(str).str.lower().eq('true'), 'invoice_number'] = False
    invalid = blank.any(axis=1) | df['amount'].isin([float('inf'), float('-inf')]) | ((df['amount'] < 0) & ~dwp)
    return df[invalid]
