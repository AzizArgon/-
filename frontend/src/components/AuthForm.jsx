// Shared building blocks for the login and register pages
export function AuthCard({ title, children }) {
  return (
    <div className="mx-auto mt-6 max-w-sm rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
      <h1 className="mb-6 text-2xl font-semibold">{title}</h1>
      {children}
    </div>
  )
}

export function Field({ label, ...props }) {
  return (
    <label className="mb-4 block">
      <span className="mb-1 block text-sm text-slate-600">{label}</span>
      <input
        {...props}
        className="w-full rounded-md border border-slate-300 px-3 py-2 outline-none focus:border-slate-900 focus:ring-1 focus:ring-slate-900"
      />
    </label>
  )
}

export function ErrorText({ children }) {
  if (!children) return null
  return <p className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{children}</p>
}

export function SubmitButton({ busy, busyText, children }) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="w-full rounded-md bg-slate-900 py-2 font-medium text-white hover:bg-slate-700 disabled:opacity-60"
    >
      {busy ? busyText : children}
    </button>
  )
}
