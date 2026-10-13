import Papa from 'papaparse'

export const REQUIRED_COLUMNS = ['transaction_id', 'date', 'vendor', 'category', 'description', 'amount', 'invoice_number'] as const
export type ColumnName = typeof REQUIRED_COLUMNS[number]
export type ColumnMapping = Partial<Record<ColumnName, string>>
export type ParsedCsv = { headers: string[]; mapping: ColumnMapping; missing: ColumnName[]; rows: Record<string, any>[]; isDwp: boolean }

const ALIASES: Record<ColumnName, string[]> = {
  transaction_id: ['transaction id', 'transaction number', 'transaction no', 'payment id', 'payment number', 'reference', 'reference number', 'voucher number', 'document number'],
  date: ['transaction date', 'payment date', 'invoice date', 'date paid', 'posting date', 'accounting date'],
  vendor: ['payee', 'supplier', 'supplier name', 'vendor name', 'merchant', 'recipient', 'beneficiary', 'company name'],
  category: ['expense category', 'spend category', 'account category', 'cost centre', 'cost center', 'department', 'expense type', 'head of account'],
  description: ['transaction description', 'payment description', 'invoice description', 'details', 'item description', 'narrative', 'purpose', 'particulars'],
  amount: ['payment amount', 'invoice amount', 'total amount', 'disbursed amount', 'value', 'gross amount', 'net amount', 'expenditure', 'paid amount', 'payment value'],
  invoice_number: ['invoice number', 'invoice no', 'invoice id', 'bill number', 'bill no', 'bill id', 'bill reference'],
}

const key = (value: string) => value.trim().toLowerCase().replace(/[_-]/g, ' ').replace(/\s+/g, ' ')

export async function parseSourceCsv(file: File, overrides: ColumnMapping = {}): Promise<ParsedCsv> {
  const bytes = await file.arrayBuffer()
  let text: string
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes) }
  catch { text = new TextDecoder('windows-1252').decode(bytes) }
  const parsed = Papa.parse<Record<string, string>>(text, { header: true, skipEmptyLines: 'greedy', transformHeader: h => h.trim() })
  if (parsed.errors.length) throw Error(parsed.errors[0].message)
  const headers = parsed.meta.fields || []
  if (!parsed.data.length) throw Error('The CSV has no data rows.')

  if (headers.includes('Transparency Invoice Amount')) {
    const needed = ['Date', 'Invoice Cost Centre Description', 'Description', 'Vendor', 'Payment Number', 'Transparency Invoice Amount']
    const missing = needed.filter(name => !headers.includes(name))
    if (missing.length) throw Error(`DWP CSV is missing columns: ${missing.join(', ')}`)
    const rows = parsed.data.map((r, i) => ({
      transaction_id: `DWP-${(r['Payment Number'] || '').trim()}-L${i + 2}`,
      date: (r.Date || '').trim().split('-').reverse().join('-'),
      vendor: (r.Vendor || '').trim(),
      category: (r['Invoice Cost Centre Description'] || '').trim(),
      description: (r.Description || '').trim(),
      amount: Number((r['Transparency Invoice Amount'] || '').replace(/[£,\s]/g, '')),
      invoice_number: '',
      payment_number: (r['Payment Number'] || '').trim(),
      source_format: 'dwp',
    }))
    return { headers, mapping: {}, missing: [], rows, isDwp: true }
  }

  const lookup = new Map(headers.map(name => [key(name), name]))
  const mapping: ColumnMapping = {}
  for (const target of REQUIRED_COLUMNS) {
    const explicit = overrides[target]
    mapping[target] = explicit !== undefined ? explicit : [target, ...ALIASES[target]].map(alias => lookup.get(key(alias))).find(Boolean)
  }
  const missing = REQUIRED_COLUMNS.filter(target => !mapping[target])
  if (missing.length) return { headers, mapping, missing, rows: [], isDwp: false }

  const rows = parsed.data.map((record, i) => {
    const result: Record<string, any> = {}
    for (const target of REQUIRED_COLUMNS) {
      const source = mapping[target]!
      result[target] = source.startsWith('__') ? '' : (record[source] || '').trim()
    }
    if (mapping.transaction_id === '__generated_id') result.transaction_id = `ROW-${i + 2}`
    if (mapping.category === '__uncategorized') result.category = 'Uncategorized'
    if (mapping.invoice_number === '__missing_invoice') {
      result.invoice_number = ''
      result.invoice_number_missing = true
    }
    result.amount = result.amount ? Number(String(result.amount).replace(/[£$₹€,\s]/g, '')) : NaN
    result.source_format = 'canonical'
    return result
  })
  return { headers, mapping, missing: [], rows, isDwp: false }
}
