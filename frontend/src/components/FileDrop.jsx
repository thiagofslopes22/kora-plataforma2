import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { FileSpreadsheet, FileText, UploadCloud, X, Check } from 'lucide-react'
import { cn } from '../lib/cn'

const ACCEPT_XLS = {
  'application/vnd.ms-excel': ['.xls'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'application/octet-stream': ['.xls', '.xlsx'],
  'application/zip': ['.xlsx'],
  'application/x-zip-compressed': ['.xlsx'],
}
const ACCEPT_PDF = { 'application/pdf': ['.pdf'] }

export const accepts = { xls: ACCEPT_XLS, pdf: ACCEPT_PDF }

function prettySize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// ── Large drop zone (conciliação) ─────────────────────────────
export function FileDrop({ label, subtitle, hint, kind = 'xls', file, onFile, onClear }) {
  const accept = kind === 'pdf' ? ACCEPT_PDF : ACCEPT_XLS
  const rx = kind === 'pdf' ? /\.pdf$/i : /\.(xls|xlsx)$/i

  const onDrop = useCallback(
    (accepted, rejected) => {
      const f = accepted[0] ?? rejected.find((r) => rx.test(r.file.name))?.file
      if (f) onFile(f)
    },
    [onFile, rx],
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, accept, multiple: false })
  const Icon = kind === 'pdf' ? FileText : FileSpreadsheet

  if (file) {
    return (
      <div className="group relative flex items-center gap-4 rounded-2xl border border-gold-ring bg-gold-soft p-4 shadow-soft transition-all duration-300 ease-expo">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gold text-white shadow-soft">
          <Icon size={22} strokeWidth={1.75} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-[12.5px] font-semibold tracking-tight text-gold-deep">
            <Check size={13} strokeWidth={2.5} /> {label}
          </div>
          <p className="mt-0.5 truncate text-sm font-medium text-ink">{file.name}</p>
          <p className="text-[12px] text-stone-400 tnum">{prettySize(file.size)}</p>
        </div>
        <button
          type="button"
          onClick={onClear}
          title="Remover arquivo"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-stone-400 transition-all duration-200 hover:bg-white hover:text-danger"
        >
          <X size={16} />
        </button>
      </div>
    )
  }

  return (
    <div
      {...getRootProps()}
      className={cn(
        'flex cursor-pointer items-center gap-4 rounded-2xl border border-dashed p-4 transition-all duration-300 ease-expo',
        isDragActive
          ? 'border-gold bg-gold-wash scale-[1.01]'
          : 'border-stone-300 bg-stone-50 hover:border-gold hover:bg-gold-soft',
      )}
    >
      <input {...getInputProps()} />
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-surface text-stone-400 shadow-soft transition-colors group-hover:text-gold">
        <UploadCloud size={22} strokeWidth={1.75} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-semibold tracking-tight text-ink">{label}</p>
        {subtitle && <p className="mt-0.5 text-[12.5px] leading-snug text-stone-500">{subtitle}</p>}
        <p className="mt-1 text-[11.5px] text-stone-400">{hint || (kind === 'pdf' ? '.pdf — clique ou arraste' : '.xls ou .xlsx — clique ou arraste')}</p>
      </div>
    </div>
  )
}

// ── Compact slot (auditor grid) ───────────────────────────────
export function FileSlot({ label, badge, kind = 'pdf', file, onFile, onClear }) {
  const accept = kind === 'xls' ? ACCEPT_XLS : ACCEPT_PDF
  const rx = kind === 'xls' ? /\.(xls|xlsx)$/i : /\.pdf$/i

  const onDrop = useCallback(
    (accepted, rejected) => {
      const f = accepted[0] ?? rejected.find((r) => rx.test(r.file.name))?.file
      if (f) onFile(f)
    },
    [onFile, rx],
  )
  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, accept, multiple: false })
  const filled = !!file

  return (
    <div
      {...getRootProps()}
      className={cn(
        'group relative flex cursor-pointer flex-col gap-2 rounded-2xl border p-4 transition-all duration-300 ease-expo',
        filled
          ? 'border-gold-ring bg-gold-soft shadow-soft'
          : isDragActive
            ? 'border-gold bg-gold-wash'
            : 'border-dashed border-stone-300 bg-surface hover:border-gold hover:bg-gold-soft/50',
      )}
    >
      <input {...getInputProps()} />
      <div className="flex items-start justify-between gap-2">
        <span className="text-[12.5px] font-semibold leading-snug tracking-tight text-ink">{label}</span>
        {badge && (
          <span
            className={cn(
              'shrink-0 rounded-pill px-1.5 py-0.5 font-mono text-[9px] font-medium uppercase tracking-wide',
              badge === 'Camelot'
                ? 'bg-info-bg text-info'
                : badge === 'Excel'
                  ? 'bg-success-bg text-success'
                  : 'bg-stone-100 text-stone-500',
            )}
          >
            {badge}
          </span>
        )}
      </div>

      {filled ? (
        <div className="flex items-center gap-1.5">
          <Check size={12} strokeWidth={2.5} className="shrink-0 text-gold" />
          <span className="truncate text-[11.5px] font-medium text-gold-deep">{file.name}</span>
        </div>
      ) : (
        <span className="flex items-center gap-1.5 text-[11.5px] text-stone-400">
          <UploadCloud size={13} strokeWidth={1.75} />
          {kind === 'xls' ? 'Selecionar Excel' : 'Selecionar PDF'}
        </span>
      )}

      {filled && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onClear()
          }}
          title="Remover"
          className="absolute right-2.5 top-2.5 flex h-6 w-6 items-center justify-center rounded-full bg-white/80 text-stone-400 opacity-0 transition-opacity duration-200 hover:text-danger group-hover:opacity-100"
        >
          <X size={13} />
        </button>
      )}
    </div>
  )
}
