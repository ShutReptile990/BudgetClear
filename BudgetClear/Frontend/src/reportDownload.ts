type EvidenceRef = {
  evidence_id?: string
  source_filename?: string
  source_record_number?: number
}

type Finding = {
  transaction_id?: string
  scheme_detected?: string
  confidence_score?: number
  rationale?: string
  detector_rationale?: string
  cited_evidence_ids?: string[]
  evidence?: EvidenceRef[]
}

type Issue = Record<string, unknown>

export type DownloadableReport = {
  auditId?: string
  budgetName?: string
  generatedAt?: string
  originalFilename?: string
  anomalies?: Finding[]
  issues?: Issue[]
}

function issueText(issue: Issue, ...keys: string[]): string {
  for (const key of keys) {
    const value = issue[key]
    if (value !== undefined && value !== null && String(value).trim()) return String(value)
  }
  return ''
}

function findings(report: DownloadableReport) {
  const deterministic = (report.issues || []).map(issue => ({
    transactionId: issueText(issue, 'transaction_id', 'row_id', 'rowId', 'id') || 'Unknown row',
    flag: issueText(issue, 'error_type', 'type', 'field') || 'Deterministic discrepancy',
    reason: issueText(issue, 'rationale', 'reason', 'description', 'message') || 'The source record did not pass a deterministic check.',
  }))

  const reviewFlags = (report.anomalies || []).map(flag => {
    const cited = flag.evidence?.filter(ref =>
      !flag.cited_evidence_ids?.length || flag.cited_evidence_ids.includes(ref.evidence_id || ''),
    ) || []
    const sources = [...new Set(cited.map(ref =>
      ref.source_filename && ref.source_record_number
        ? `${ref.source_filename}, record ${ref.source_record_number}`
        : '',
    ).filter(Boolean))]
    const confidence = Number.isFinite(flag.confidence_score)
      ? ` (${Number(flag.confidence_score).toFixed(1)}% signal strength)`
      : ''
    return {
      transactionId: flag.transaction_id || 'Unknown transaction',
      flag: `${flag.scheme_detected || 'Review flag'}${confidence}`,
      reason: `${flag.rationale || flag.detector_rationale || 'Review the linked source evidence.'}${sources.length ? `\nEvidence: ${sources.join('; ')}` : ''}`,
    }
  })

  return [...deterministic, ...reviewFlags]
}

export async function downloadReportDocx(report: DownloadableReport): Promise<void> {
  const { Document, HeadingLevel, Packer, Paragraph, Table, TableCell, TableRow, TextRun, VerticalAlign, WidthType } = await import('docx')
  const rows = findings(report)
  const cell = (value: string, header = false) => new TableCell({
    children: [new Paragraph({
      children: [new TextRun({ text: value, bold: header, size: 19, color: header ? '163047' : '263B4B' })],
      spacing: { after: 0 },
    })],
    margins: { top: 110, bottom: 110, left: 110, right: 110 },
    verticalAlign: VerticalAlign.CENTER,
    shading: header ? { fill: 'E5F3F0' } : undefined,
  })
  const table = new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [1800, 2500, 5060],
    rows: [
      new TableRow({ tableHeader: true, cantSplit: true, children: [
        cell('Transaction ID', true), cell('Flagged finding', true), cell('Why it was flagged', true),
      ] }),
      ...rows.map(row => new TableRow({ cantSplit: true, children: [
        cell(row.transactionId), cell(row.flag), cell(row.reason),
      ] })),
    ],
  })
  const date = report.generatedAt && !Number.isNaN(Date.parse(report.generatedAt))
    ? new Date(report.generatedAt).toLocaleString()
    : new Date().toLocaleString()
  const wordDocument = new Document({
    sections: [{
      children: [
        new Paragraph({ text: 'BudgetClear G-03', heading: HeadingLevel.HEADING_2 }),
        new Paragraph({ text: 'Audit findings report', heading: HeadingLevel.TITLE }),
        new Paragraph({ text: `Audit: ${report.budgetName || report.auditId || 'Untitled audit'}` }),
        new Paragraph({ text: `Audit ID: ${report.auditId || 'Pending'}  |  Generated: ${date}` }),
        new Paragraph({ text: `Source: ${report.originalFilename || 'Uploaded CSV'}  |  Flagged findings: ${rows.length}`, spacing: { after: 240 } }),
        ...(rows.length ? [table] : [new Paragraph({ text: 'No transactions were flagged in this audit.' })]),
        new Paragraph({
          text: 'AI review flags are suggestions, not proof of wrongdoing. Confirm each finding against its source evidence.',
          spacing: { before: 240 },
        }),
      ],
    }],
  })
  const blob = await Packer.toBlob(wordDocument)
  const name = (report.auditId || report.budgetName || 'report').replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-|-$/g, '').slice(0, 80) || 'report'
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `budgetclear-${name}-findings.docx`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
