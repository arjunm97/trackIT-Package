'use client'

import { useEffect, useMemo, useRef, useState } from 'react'

const PROVIDERS = [
  { value: 'local', label: 'Local' },
  { value: 'bedrock', label: 'AWS Bedrock' },
]

export default function TrackitDashboard() {
  const API_BASE = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8090'

  // Provider
  const [provider, setProvider] = useState('local')

  // Activity stream
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Hi 👋 Select a notebook, run Trackit, then summarize a log.' },
  ])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const scrollRef = useRef(null)

  // Notebooks + run controls
  const [nbList, setNbList] = useState([])
  const [nbLoading, setNbLoading] = useState(false)
  const [selectedNb, setSelectedNb] = useState('')

  const [trackitStatus, setTrackitStatus] = useState({
    running: false,
    pid: null,
    notebook: null,
  })
  const [runBusy, setRunBusy] = useState(false)

  // Logs + summary
  const [logs, setLogs] = useState([])
  const [logsLoading, setLogsLoading] = useState(false)
  const [selectedLog, setSelectedLog] = useState('')
  const [summarizing, setSummarizing] = useState(false)
  const [summaryText, setSummaryText] = useState('')

  // ---- Helpers
  const statusPill = useMemo(() => {
    if (trackitStatus.running) {
      return {
        cls: 'bg-emerald-500/15 text-emerald-900 ring-emerald-600/20',
        text: `Running · PID ${trackitStatus.pid ?? '—'}`,
      }
    }
    return {
      cls: 'bg-neutral-900/5 text-neutral-800 ring-neutral-900/10',
      text: 'Idle',
    }
  }, [trackitStatus.running, trackitStatus.pid])

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Load notebooks (mount)
  useEffect(() => {
    let ignore = false
    ;(async () => {
      setNbLoading(true)
      try {
        const res = await fetch(`${API_BASE}/getNotebooks`, {
          headers: { Accept: 'application/json' },
          cache: 'no-store',
        })
        const data = await res.json()
        if (!ignore && Array.isArray(data)) {
          setNbList(data)
          setSelectedNb((prev) => prev || data[0] || '')
        }
      } catch (e) {
        console.error(e)
      } finally {
        if (!ignore) setNbLoading(false)
      }
    })()
    return () => {
      ignore = true
    }
  }, [API_BASE])

  // Load logs (mount + manual refresh)
  async function refreshLogs() {
    setLogsLoading(true)
    try {
      const res = await fetch(`${API_BASE}/getLogs`, {
        headers: { Accept: 'application/json' },
        cache: 'no-store',
      })
      const data = await res.json()
      if (Array.isArray(data)) {
        setLogs(data)
        setSelectedLog((prev) => prev || data[0] || '')
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLogsLoading(false)
    }
  }

  useEffect(() => {
    refreshLogs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API_BASE])

  // Optional: light polling for status
  useEffect(() => {
    let alive = true
    const t = setInterval(() => {
      if (!alive) return
      refreshStatus().catch(() => {})
    }, 2500)
    return () => {
      alive = false
      clearInterval(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API_BASE])

  // Trackit actions
  async function runTrackit() {
    if (!selectedNb) return
    setRunBusy(true)
    try {
      const res = await fetch(`${API_BASE}/trackit/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ notebook: selectedNb, json: false, debounce: 0.5 }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.detail || res.status)

      setTrackitStatus({ running: true, pid: data.pid, notebook: data.notebook })
      setMessages((p) => [...p, { role: 'assistant', content: `▶ Running ${data.notebook} (PID ${data.pid})` }])
      refreshLogs()
    } catch (e) {
      console.error(e)
      pushAssist(`⚠️ Run failed: ${e?.message || String(e)}`)
    } finally {
      setRunBusy(false)
    }
  }

  async function stopTrackit() {
    setRunBusy(true)
    try {
      const res = await fetch(`${API_BASE}/trackit/stop`, { method: 'POST' })
      if (!res.ok) throw new Error(await res.text())
      setTrackitStatus({ running: false, pid: null, notebook: null })
      setMessages((p) => [...p, { role: 'assistant', content: `■ Stopped` }])
    } catch (e) {
      console.error(e)
      pushAssist(`⚠️ Stop failed: ${e?.message || String(e)}`)
    } finally {
      setRunBusy(false)
    }
  }

  async function refreshStatus() {
    const res = await fetch(`${API_BASE}/trackit/status`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    })
    const data = await res.json()
    setTrackitStatus(data)
  }

  function pushAssist(content) {
    setMessages((p) => [...p, { role: 'assistant', content }])
  }

  async function handleSummarize() {
    if (!selectedLog) return
    setSummarizing(true)
    setSummaryText('')
    try {
      const res = await fetch(`${API_BASE}/summary`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ filename: selectedLog, provider: provider }),
      })

      if (!res.ok) {
        const errText = await safeReadError(res)
        throw new Error(errText || `Request failed: ${res.status}`)
      }

      const ct = res.headers.get('content-type') || ''
      let text = ''
      if (ct.includes('application/json')) {
        const data = await res.json()
        text = typeof data === 'string' ? data : data?.summary || JSON.stringify(data)
      } else {
        text = await res.text()
      }

      setSummaryText(text)
      pushAssist(`✅ Summary generated from ${selectedLog} (${providerLabel(provider)})`)
    } catch (e) {
      console.error(e)
      pushAssist(`⚠️ Summary failed: ${e?.message || 'Unknown error'}`)
    } finally {
      setSummarizing(false)
    }
  }

  // Chat send
  async function sendMessage() {
    if (!input.trim()) return
    const newMsg = { role: 'user', content: input.trim() }
    setMessages((prev) => [...prev, newMsg])
    setInput('')
    setSending(true)
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider,
          messages: [...messages, newMsg],
        }),
      })
      const data = await res.json()
      setMessages((prev) => [...prev, { role: 'assistant', content: data.reply }])
    } catch (err) {
      console.error(err)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Q/A and RAG currently not supported. Will be available in the next version' },
      ])
    } finally {
      setSending(false)
    }
  }

  return (
    <main className="min-h-screen relative text-neutral-900">
      {/* Background */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(70%_80%_at_15%_10%,rgba(16,185,129,0.10),transparent_60%),radial-gradient(60%_70%_at_90%_0%,rgba(56,189,248,0.10),transparent_60%),linear-gradient(to_bottom,white,rgba(255,255,255,0.65))]" />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.03] mix-blend-soft-light"
        style={{
          backgroundImage:
            'url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 width=%27140%27 height=%27140%27 viewBox=%270 0 20 20%27%3E%3Cpath fill=%27%23000%27 fill-opacity=%270.4%27 d=%27M0 0h1v1H0z%27/%3E%3C/svg%3E")',
        }}
      />

      {/* Top Bar */}
      <header className="sticky top-0 z-20">
        <div className="mx-auto max-w-7xl px-4 py-4">
          <div className="backdrop-blur-xl bg-white/60 border border-white/40 shadow-[0_6px_40px_rgba(0,0,0,0.05)] rounded-2xl px-5 py-4 flex flex-wrap gap-3 items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="h-9 w-9 rounded-2xl bg-gradient-to-br from-emerald-400 to-sky-400 ring-1 ring-black/10 shadow-sm" />
              <div>
                <h1 className="font-semibold tracking-tight text-[15px] sm:text-base">Trackit</h1>
                <p className="text-[12px] text-neutral-600">Run notebooks · Generate summaries</p>
              </div>
            </div>

            {/* Provider */}
            <div className="flex items-center gap-2">
              <span className="text-xs text-neutral-600">Provider</span>
              <div className="relative">
                <select
                  className="appearance-none rounded-xl border border-black/10 bg-white/70 backdrop-blur px-3 py-2 text-sm pr-8 focus:outline-none focus:ring-2 focus:ring-sky-300"
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                  title="Choose inference provider"
                >
                  {PROVIDERS.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
                <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-neutral-500">▾</span>
              </div>

              <span className={`ml-2 text-xs rounded-full px-2.5 py-1 ring-1 ${statusPill.cls}`}>{statusPill.text}</span>
            </div>
          </div>
        </div>
      </header>

      {/* Main */}
      <div className="mx-auto w-full max-w-7xl px-4 pb-24 pt-4">
        {/* Bigger Summary, slightly tighter Activity */}
        <div className="grid grid-cols-1 xl:grid-cols-[320px_0.95fr_520px] gap-6">
          {/* LEFT: Control panel */}
          <aside className="rounded-3xl border border-white/40 bg-white/70 backdrop-blur-xl p-5 shadow-[0_12px_40px_rgba(0,0,0,0.06)]">
            <h2 className="text-sm font-semibold tracking-tight text-neutral-900">Run</h2>
            <p className="text-[12px] text-neutral-600 mt-1">Pick a notebook and Trackit.</p>

            <div className="mt-4 space-y-3">
              <div>
                <label className="text-xs text-neutral-600">Notebook</label>
                <div className="relative mt-1">
                  <select
                    className="w-full appearance-none rounded-2xl border border-black/10 bg-white/70 px-3 py-2.5 text-sm pr-8 focus:outline-none focus:ring-2 focus:ring-emerald-300 disabled:opacity-60"
                    value={selectedNb}
                    onChange={(e) => setSelectedNb(e.target.value)}
                    disabled={nbLoading || nbList.length === 0 || runBusy || trackitStatus.running}
                  >
                    {nbList.length === 0 ? (
                      <option>{nbLoading ? 'Loading…' : 'No notebooks found'}</option>
                    ) : (
                      nbList.map((f) => (
                        <option key={f} value={f}>
                          {f}
                        </option>
                      ))
                    )}
                  </select>
                  <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-neutral-500">▾</span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={runTrackit}
                  disabled={!selectedNb || runBusy || trackitStatus.running}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl px-3 py-2.5 bg-neutral-900 text-white shadow-sm hover:opacity-95 disabled:opacity-50 active:scale-[.99]"
                >
                  ▶ Run
                </button>
                <button
                  onClick={stopTrackit}
                  disabled={!trackitStatus.running || runBusy}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl px-3 py-2.5 border border-black/10 bg-white hover:bg-neutral-50 disabled:opacity-50 active:scale-[.99]"
                >
                  ■ Stop
                </button>
              </div>

              <button
                onClick={() => refreshStatus().catch(() => {})}
                className="w-full inline-flex items-center justify-center gap-2 rounded-2xl px-3 py-2.5 border border-black/10 bg-white hover:bg-neutral-50 active:scale-[.99]"
                title="Refresh status"
              >
                ⟳ Refresh status
              </button>

              <div className="mt-2 rounded-2xl border border-black/10 bg-white/70 p-3">
                <div className="text-xs text-neutral-600">Current</div>
                <div className="mt-1 text-sm text-neutral-900 font-medium">
                  {trackitStatus.running ? (
                    <>
                      {trackitStatus.notebook || 'Notebook'}{' '}
                      <span className="text-neutral-500 font-normal">· PID {trackitStatus.pid}</span>
                    </>
                  ) : (
                    'No active run'
                  )}
                </div>
              </div>
            </div>

            {/* Outputs */}
            <div className="mt-6">
              <h3 className="text-sm font-semibold tracking-tight text-neutral-900">Outputs</h3>
              <p className="text-[12px] text-neutral-600 mt-1">Choose a log and generate summary.</p>

              <div className="mt-3 space-y-2">
                <div className="flex items-center gap-2">
                  <div className="relative flex-1">
                    <select
                      className="w-full appearance-none rounded-2xl border border-black/10 bg-white/70 px-3 py-2.5 text-sm pr-8 focus:outline-none focus:ring-2 focus:ring-sky-300 disabled:opacity-60"
                      value={selectedLog}
                      onChange={(e) => setSelectedLog(e.target.value)}
                      disabled={logsLoading || logs.length === 0 || summarizing}
                      title="Choose a log file"
                    >
                      {logs.length === 0 ? (
                        <option>{logsLoading ? 'Loading…' : 'No logs yet'}</option>
                      ) : (
                        logs.map((f) => (
                          <option key={f} value={f}>
                            {f}
                          </option>
                        ))
                      )}
                    </select>
                    <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-neutral-500">▾</span>
                  </div>
                  <button
                    onClick={refreshLogs}
                    className="rounded-2xl px-3 py-2.5 border border-black/10 bg-white hover:bg-neutral-50 active:scale-[.99]"
                    title="Refresh logs"
                  >
                    ⟳
                  </button>
                </div>

                <button
                  onClick={handleSummarize}
                  disabled={summarizing || !selectedLog}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-2xl px-4 py-3 bg-neutral-900 text-white shadow-sm transition hover:opacity-95 active:scale-[.99] disabled:opacity-50"
                >
                  <span className={`h-2 w-2 rounded-full ${summarizing ? 'bg-neutral-400 animate-pulse' : 'bg-emerald-400'}`} />
                  {summarizing ? 'Summarizing…' : `Summarize with ${providerLabel(provider)}`}
                </button>
              </div>
            </div>
          </aside>

          {/* CENTER: Activity (slightly smaller + denser) */}
          <section className="rounded-3xl border border-white/40 bg-white/70 backdrop-blur-xl p-4 shadow-[0_12px_40px_rgba(0,0,0,0.06)]">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold tracking-tight text-neutral-900">Activity</h2>
                <p className="text-[12px] text-neutral-600 mt-1">Lightweight stream of actions and assistant notes.</p>
              </div>
              <span className="text-[11px] text-neutral-500">Provider: {providerLabel(provider)}</span>
            </div>

            <div
              className="mt-3 space-y-2 max-h-[56vh] overflow-y-auto pr-2"
              style={{ scrollbarGutter: 'stable' }}
            >
              {messages.map((m, i) => (
                <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[82%] rounded-2xl px-3.5 py-2.5 text-[12.5px] leading-relaxed shadow-[0_2px_12px_rgba(0,0,0,0.06)] ring-1 ${
                      m.role === 'user'
                        ? 'bg-neutral-900 text-white ring-black/10 rounded-br-md'
                        : 'bg-white/80 text-neutral-800 ring-black/10 rounded-bl-md'
                    }`}
                  >
                    {m.content}
                  </div>
                </div>
              ))}
              <div ref={scrollRef} />
            </div>

            {/* Composer */}
            <form
              onSubmit={(e) => {
                e.preventDefault()
                sendMessage()
              }}
              className="mt-4 rounded-2xl border border-white/50 bg-white/60 backdrop-blur p-2 flex items-center gap-2 shadow-[0_8px_24px_rgba(0,0,0,0.04)]"
            >
              <input
                className="flex-1 bg-transparent rounded-xl px-3 py-2 text-[13px] outline-none placeholder:text-neutral-400"
                placeholder="Ask something…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
              />
              <button
                type="submit"
                disabled={sending}
                className="inline-flex items-center gap-2 rounded-xl bg-neutral-900 text-white px-4 py-2 shadow-sm transition hover:opacity-95 active:scale-[.99] disabled:opacity-50"
              >
                {sending ? 'Sending…' : 'Send'}
              </button>
            </form>
          </section>

          {/* RIGHT: Summary (bigger + more “document-like”) */}
          <section className="rounded-3xl border border-white/40 bg-white/70 backdrop-blur-xl p-6 shadow-[0_12px_40px_rgba(0,0,0,0.06)]">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold tracking-tight text-neutral-900">Summary</h2>
                <p className="text-[12px] text-neutral-600 mt-1">Readable output for quick scanning.</p>
              </div>

              <div className="shrink-0 inline-flex items-center gap-2 rounded-2xl bg-neutral-900/90 text-white text-[11px] px-3 py-2 shadow-[0_10px_30px_rgba(0,0,0,0.10)]">
                <span className={`h-1.5 w-1.5 rounded-full ${summaryText ? 'bg-emerald-400' : 'bg-neutral-500'}`} />
                <span className="max-w-[260px] truncate">{selectedLog || 'No log selected'}</span>
              </div>
            </div>

            <div className="mt-4 h-1 rounded-full bg-gradient-to-r from-emerald-400 via-teal-400 to-sky-400" />

            <article className="mt-5 text-[15px] sm:text-[16px] text-neutral-800 leading-[1.85] whitespace-pre-wrap min-h-[520px]">
              {summaryText || (
                <div className="rounded-2xl border border-dashed border-black/10 bg-white/70 p-5 text-neutral-600">
                  Generate a summary to see it here. Tip: keep logs short + structured for best results.
                </div>
              )}
            </article>

            <div className="mt-5 flex items-center gap-2">
              <button
                onClick={() => summaryText && navigator.clipboard.writeText(summaryText)}
                disabled={!summaryText}
                className="inline-flex items-center gap-2 rounded-2xl border border-black/10 bg-white/75 px-3 py-2 text-[12px] text-neutral-800 hover:bg-white transition active:scale-[.985] disabled:opacity-50 shadow-[0_8px_20px_rgba(0,0,0,0.04)]"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                Copy
              </button>
              <button
                onClick={() => setSummaryText('')}
                disabled={!summaryText}
                className="inline-flex items-center gap-2 rounded-2xl border border-black/10 bg-white/75 px-3 py-2 text-[12px] text-neutral-800 hover:bg-white transition active:scale-[.985] disabled:opacity-50 shadow-[0_8px_20px_rgba(0,0,0,0.04)]"
              >
                Clear
              </button>
              <span className="ml-auto text-[12px] text-neutral-500">Provider: {providerLabel(provider)}</span>
            </div>
          </section>
        </div>
      </div>
    </main>
  )
}

function providerLabel(v) {
  return v === 'bedrock' ? 'AWS Bedrock' : 'Local'
}

async function safeReadError(res) {
  try {
    const ct = res.headers.get('content-type') || ''
    if (ct.includes('application/json')) {
      const j = await res.json()
      return j?.detail || j?.message || JSON.stringify(j)
    }
    return await res.text()
  } catch {
    return ''
  }
}
