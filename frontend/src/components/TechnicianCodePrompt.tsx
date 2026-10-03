import { useId, useState, type FormEvent } from 'react'
import { SpinnerIcon } from './icons'

interface FieldProps {
  id: string
  value: string
  onChange: (value: string) => void
  testId: string
  disabled?: boolean
  invalid?: boolean
  autoFocus?: boolean
}

/** The code input itself: masked (shoulder-surfing in a workshop), never autofilled, never spell-checked. */
export function TechnicianCodeField({ id, value, onChange, testId, disabled, invalid, autoFocus }: FieldProps) {
  return (
    <input
      id={id}
      type="password"
      autoComplete="off"
      spellCheck={false}
      maxLength={128}
      value={value}
      disabled={disabled}
      autoFocus={autoFocus}
      onChange={(e) => onChange(e.target.value)}
      placeholder="Technician code"
      aria-invalid={invalid ? true : undefined}
      data-testid={testId}
      className={`block w-44 rounded-md border bg-white px-2 py-1 text-xs text-slate-900 shadow-sm focus:border-accent-500 disabled:bg-slate-50 ${
        invalid ? 'border-red-400 bg-red-50/40' : 'border-slate-300'
      }`}
    />
  )
}

interface Props {
  /** Called with the trimmed, non-empty code. */
  onSubmit: (code: string) => void
  onCancel: () => void
  /** A message from the server about the last attempt, e.g. "Invalid technician code.". */
  error?: string | null
  busy?: boolean
}

/** A small "Enter technician code" box, shown when Verify/Confirm/Correct is clicked and the server wants a code. */
export function TechnicianCodePrompt({ onSubmit, onCancel, error, busy = false }: Props) {
  const id = useId()
  const [value, setValue] = useState('')
  const [empty, setEmpty] = useState(false)

  function submit(event: FormEvent) {
    event.preventDefault()
    const code = value.trim()
    if (busy) return
    setEmpty(code.length === 0)
    if (code) onSubmit(code)
  }

  const message = empty ? 'Enter the technician code.' : error

  return (
    <form
      onSubmit={submit}
      noValidate
      className="basis-full rounded-md border border-accent-300 bg-sky-50/60 p-2"
      data-testid="technician-code-prompt"
    >
      <label htmlFor={id} className="block text-xs font-semibold text-navy-900">
        Enter technician code
      </label>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        <TechnicianCodeField
          id={id}
          value={value}
          onChange={setValue}
          testId="technician-code-input"
          disabled={busy}
          invalid={Boolean(message)}
          autoFocus
        />
        <button
          type="submit"
          disabled={busy}
          data-testid="technician-code-submit"
          className="inline-flex items-center gap-1 rounded-md bg-accent-600 px-2 py-1 text-xs font-semibold text-white hover:bg-accent-700 disabled:opacity-70"
        >
          {busy && <SpinnerIcon className="h-3.5 w-3.5" />}
          Continue
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          data-testid="technician-code-cancel"
          className="rounded-md bg-white px-2 py-1 text-xs font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 disabled:opacity-70"
        >
          Cancel
        </button>
      </div>
      {message && (
        <p role="alert" className="mt-1 text-xs text-red-700" data-testid="technician-code-error">
          {message}
        </p>
      )}
    </form>
  )
}
