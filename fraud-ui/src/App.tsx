import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import {
  Activity,
  ArrowRight,
  CircleAlert,
  CircleCheck,
  Clock3,
  CreditCard,
  LoaderCircle,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Store,
} from 'lucide-react'
import { getDemoDefaults, getHealth, scoreTransaction } from './api'
import type { HealthResponse, ScoreResponse } from './api'
import './App.css'

type FormValues = {
  amount: string
  clientId: string
  cardId: string
  merchantId: string
  transactionTime: string
}

const CARD_EVIDENCE = [
  ['card_prior_txn_count', 'Prior transactions'],
  ['card_prior_avg_amount', 'Average amount'],
  ['amount_vs_card_avg', 'Amount vs. average'],
  ['time_since_prev_card_txn', 'Since last transaction'],
] as const

const MERCHANT_EVIDENCE = [
  ['merchant_prior_txn_count', 'Eligible transactions'],
  ['merchant_prior_fraud_count', 'Prior fraud transactions'],
  ['merchant_prior_fraud_rate_pct', 'Observed fraud rate'],
  ['merchant_prior_unique_cards', 'Cards observed'],
  ['merchant_prior_unique_fraud_cards', 'Cards with fraud'],
  ['merchant_prior_fraud_card_ratio_pct', 'Fraud-card ratio'],
] as const

const TIMING_STAGES = [
  ['A0 · Profile', 'a0'],
  ['B1 · Card history', 'b1'],
  ['C1 · Merchant history', 'c1'],
  ['Feature assembly', 'assembly'],
  ['Model inference', 'model_inference'],
] as const

const AMOUNT_PRESETS = [25, 75, 250, 1000]

type ResultView = 'snapshot' | 'signals' | 'timing'

function localDateTimeNow(): string {
  const now = new Date()
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)
}

function formatEvidenceValue(name: string, value: number): string {
  if (name.endsWith('_pct')) return `${formatNumber(value)}%`
  if (name === 'time_since_prev_card_txn') return `${formatNumber(value)} h`
  if (name === 'amount_vs_card_avg') return `${formatNumber(value)}×`
  if (name === 'card_prior_avg_amount') return `${formatNumber(value)} units`
  return formatNumber(value)
}

function EvidenceRows({
  items,
  evidence,
}: {
  items: ReadonlyArray<readonly [string, string]>
  evidence: Record<string, number>
}) {
  return (
    <dl className="signal-list">
      {items.map(([name, label]) => (
        <div className="signal-row" key={name}>
          <dt>{label}</dt>
          <dd>{formatEvidenceValue(name, evidence[name] ?? 0)}</dd>
        </div>
      ))}
    </dl>
  )
}

function App() {
  const [form, setForm] = useState<FormValues>({
    amount: '',
    clientId: '',
    cardId: '',
    merchantId: '',
    transactionTime: localDateTimeNow(),
  })
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [healthError, setHealthError] = useState(false)
  const [result, setResult] = useState<ScoreResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [scoring, setScoring] = useState(false)
  const [loadingExample, setLoadingExample] = useState(false)
  const [defaultsStatus, setDefaultsStatus] = useState<string | null>(null)
  const [resultView, setResultView] = useState<ResultView>('snapshot')
  const formTouched = useRef(false)

  useEffect(() => {
    let active = true
    getHealth()
      .then((response) => {
        if (active) setHealth(response)
      })
      .catch(() => {
        if (active) setHealthError(true)
      })

    getDemoDefaults()
      .then((defaults) => {
        if (!active || formTouched.current) return
        setForm({
          amount: String(defaults.amount),
          clientId: String(defaults.client_id),
          cardId: String(defaults.card_id),
          merchantId: String(defaults.merchant_id),
          transactionTime: defaults.transaction_time.slice(0, 16),
        })
        setDefaultsStatus('Local graph example loaded')
      })
      .catch(() => {
        if (active) setDefaultsStatus('No local graph example available')
      })

    return () => {
      active = false
    }
  }, [])

  function updateField(field: keyof FormValues, value: string) {
    formTouched.current = true
    setForm((current) => ({ ...current, [field]: value }))
    setResult(null)
    setError(null)
  }

  async function loadExample() {
    setLoadingExample(true)
    setError(null)
    try {
      const defaults = await getDemoDefaults()
      formTouched.current = true
      setForm({
        amount: String(defaults.amount),
        clientId: String(defaults.client_id),
        cardId: String(defaults.card_id),
        merchantId: String(defaults.merchant_id),
        transactionTime: defaults.transaction_time.slice(0, 16),
      })
      setDefaultsStatus('Local graph example loaded')
      setResult(null)
      setResultView('snapshot')
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not load a local example.')
    } finally {
      setLoadingExample(false)
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setScoring(true)
    setError(null)
    setResult(null)
    setResultView('snapshot')

    try {
      const response = await scoreTransaction({
        amount: Number(form.amount),
        client_id: Number(form.clientId),
        card_id: Number(form.cardId),
        merchant_id: Number(form.merchantId),
        transaction_time: form.transactionTime,
      })
      setResult(response)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Scoring request failed.')
    } finally {
      setScoring(false)
    }
  }

  const fraudPercent = result ? Math.min(100, Math.max(0, result.fraud_confidence * 100)) : 0
  const amountValue = Math.min(2000, Math.max(0, Number(form.amount) || 0))
  const timingMaximum = result
    ? Math.max(1, ...TIMING_STAGES.map(([, key]) => result.timings_ms[key] ?? 0))
    : 1

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#main-content" aria-label="Fraud scoring workbench home">
          <span className="brand-mark"><Activity size={18} strokeWidth={2.2} /></span>
          <span>Signal / Graph</span>
        </a>
        <div className={`service-status ${health ? 'online' : healthError ? 'offline' : 'checking'}`} role="status">
          {health ? <CircleCheck size={15} /> : healthError ? <CircleAlert size={15} /> : <Activity size={15} />}
          <span>{health ? 'API connected' : healthError ? 'API unavailable' : 'Connecting'}</span>
        </div>
      </header>

      <section className="page-heading" id="main-content">
        <div>
          <p className="eyebrow">LOCAL FRAUD SCORING</p>
          <h1>Transaction assessment</h1>
          <p className="page-subtitle">A single transaction, enriched with card and merchant history.</p>
        </div>
        <div className="run-badge"><span className="run-dot" /> Synthetic graph · Native model</div>
      </section>

      <div className="workbench">
        <section className="input-panel" aria-labelledby="form-title">
          <div className="panel-heading">
            <div className="heading-count">01</div>
            <div>
              <p className="section-kicker">SCORING REQUEST</p>
              <h2 id="form-title">Transaction details</h2>
            </div>
          </div>

          <form className="transaction-form" onSubmit={handleSubmit}>
            <div className="form-block amount-block">
              <div className="field-label-row">
                <label htmlFor="amount">Transaction amount</label>
                <span className="field-unit">SOURCE UNITS</span>
              </div>
              <div className="amount-input-wrap">
                <input
                  id="amount"
                  type="number"
                  name="amount"
                  min="0"
                  step="0.01"
                  required
                  value={form.amount}
                  onChange={(event) => updateField('amount', event.target.value)}
                />
              </div>
              <div className="range-row">
                <input
                  aria-label="Adjust transaction amount from zero to two thousand"
                  className="amount-range"
                  type="range"
                  min="0"
                  max="2000"
                  step="5"
                  value={amountValue}
                  onChange={(event) => updateField('amount', event.target.value)}
                />
                <span>2,000 units</span>
              </div>
              <div className="preset-row" role="group" aria-label="Amount presets">
                <span>Try an amount</span>
                {AMOUNT_PRESETS.map((amount) => (
                  <button
                    aria-pressed={Number(form.amount) === amount}
                    className="preset-button"
                    key={amount}
                    onClick={() => updateField('amount', String(amount))}
                    type="button"
                  >
                    {formatNumber(amount)}
                  </button>
                ))}
              </div>
            </div>

            <div className="form-block time-block">
              <div className="field-label-row">
                <label htmlFor="transaction-time">Transaction time</label>
                <Clock3 size={15} aria-hidden="true" />
              </div>
              <input
                id="transaction-time"
                type="datetime-local"
                name="transaction-time"
                required
                value={form.transactionTime}
                onChange={(event) => updateField('transactionTime', event.target.value)}
              />
              <p className="field-note">History is evaluated relative to this time.</p>
            </div>

            <fieldset className="identity-fields">
              <legend>Graph entities</legend>
              <div className="identity-grid">
                <label htmlFor="client-id">
                  <span>Client ID</span>
                  <input
                    id="client-id"
                    type="number"
                    name="client-id"
                    min="0"
                    step="1"
                    required
                    value={form.clientId}
                    onChange={(event) => updateField('clientId', event.target.value)}
                  />
                </label>
                <label htmlFor="card-id">
                  <span>Card ID</span>
                  <input
                    id="card-id"
                    type="number"
                    name="card-id"
                    min="0"
                    step="1"
                    required
                    value={form.cardId}
                    onChange={(event) => updateField('cardId', event.target.value)}
                  />
                </label>
                <label htmlFor="merchant-id">
                  <span>Merchant ID</span>
                  <input
                    id="merchant-id"
                    type="number"
                    name="merchant-id"
                    min="0"
                    step="1"
                    required
                    value={form.merchantId}
                    onChange={(event) => updateField('merchantId', event.target.value)}
                  />
                </label>
              </div>
              <p className="field-note">IDs must exist in the local graph.</p>
            </fieldset>

            <div className="form-actions">
              <button className="score-button" type="submit" disabled={scoring || !health}>
                {scoring ? <LoaderCircle className="spin" size={17} /> : <ArrowRight size={17} />}
                <span>{scoring ? 'Scoring transaction' : 'Run assessment'}</span>
              </button>
              <button className="reset-button" type="button" onClick={loadExample} disabled={loadingExample}>
                {loadingExample ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={15} />}
                <span>Load example</span>
              </button>
            </div>
            {defaultsStatus && <p className="request-status" role="status">{defaultsStatus}</p>}
            {error && <p className="error-message" role="alert"><CircleAlert size={16} />{error}</p>}
          </form>
        </section>

        <section className="result-panel" aria-labelledby="result-title" aria-live="polite" aria-busy={scoring}>
          <div className="panel-heading result-panel-heading">
            <div className="heading-count">02</div>
            <div>
              <p className="section-kicker">MODEL OUTPUT</p>
              <h2 id="result-title">Assessment</h2>
            </div>
            {result && <span className="model-chip">XGBoost · local</span>}
          </div>

          {!result ? (
            <div className={`result-empty ${scoring ? 'is-scoring' : ''}`}>
              <div className="empty-orbit" aria-hidden="true">
                {scoring ? <LoaderCircle className="spin" size={27} /> : <Activity size={27} />}
              </div>
              <p className="empty-label">{scoring ? 'RUNNING FEATURE LOOKUPS' : 'AWAITING INPUT'}</p>
              <h3>{scoring ? 'Building the assessment' : 'No assessment yet'}</h3>
              <div className="empty-track" aria-hidden="true"><span /></div>
            </div>
          ) : (
            <>
              <div className="result-tabs" role="group" aria-label="Assessment view">
                {([
                  ['snapshot', 'Snapshot'],
                  ['signals', 'History signals'],
                  ['timing', 'Request timing'],
                ] as const).map(([view, label]) => (
                  <button
                    aria-pressed={resultView === view}
                    className={resultView === view ? 'selected' : ''}
                    key={view}
                    onClick={() => setResultView(view)}
                    type="button"
                  >
                    {label}
                  </button>
                ))}
              </div>

              {resultView === 'snapshot' && (
                <div className="snapshot-view">
                  <div className={`decision-banner ${result.prediction ? 'fraud' : 'clear'}`}>
                    <div className="decision-icon">
                      {result.prediction ? <ShieldAlert size={22} /> : <ShieldCheck size={22} />}
                    </div>
                    <div className="decision-copy">
                      <p className="section-kicker">BINARY PREDICTION</p>
                      <h3>{result.prediction ? 'Fraud predicted' : 'Non-fraud predicted'}</h3>
                    </div>
                    <span className="uncalibrated-tag">Uncalibrated score</span>
                  </div>

                  <div className={`score-summary ${result.prediction ? 'fraud' : 'clear'}`}>
                    <div className="score-gauge" style={{ '--score-sweep': `${fraudPercent}%` } as CSSProperties} role="img" aria-label={`Fraud model score ${fraudPercent.toFixed(1)} percent`}>
                      <div className="gauge-center">
                        <strong>{fraudPercent.toFixed(1)}<small>%</small></strong>
                        <span>fraud score</span>
                      </div>
                    </div>
                    <div className="confidence-details">
                      <p className="confidence-intro">Native model output</p>
                      <div className="confidence-row">
                        <span><i className="confidence-dot fraud-dot" />Fraud</span>
                        <strong>{(result.fraud_confidence * 100).toFixed(2)}%</strong>
                      </div>
                      <div className="confidence-row">
                        <span><i className="confidence-dot clear-dot" />Non-fraud</span>
                        <strong>{(result.non_fraud_confidence * 100).toFixed(2)}%</strong>
                      </div>
                      <p className="confidence-footnote">Scores are not calibrated for real-world decisioning.</p>
                    </div>
                  </div>

                  <div className="snapshot-metrics">
                    <div className="snapshot-metric">
                      <CreditCard size={16} />
                      <span>Card history</span>
                      <strong>{formatNumber(result.evidence.card_prior_txn_count ?? 0)}</strong>
                    </div>
                    <div className="snapshot-metric">
                      <Store size={16} />
                      <span>Merchant history</span>
                      <strong>{formatNumber(result.evidence.merchant_prior_txn_count ?? 0)}</strong>
                    </div>
                    <div className="snapshot-metric">
                      <Clock3 size={16} />
                      <span>Request time</span>
                      <strong>{formatNumber(result.timings_ms.end_to_end ?? 0)} ms</strong>
                    </div>
                  </div>
                  <p className="evidence-caveat">History values are model inputs, not explanations of feature contribution.</p>
                </div>
              )}

              {resultView === 'signals' && (
                <div className="signals-view">
                  <div className="signals-intro">
                    <div>
                      <p className="section-kicker">RDF-DERIVED CONTEXT</p>
                      <h3>History signals</h3>
                    </div>
                    <span>10 values</span>
                  </div>
                  <section className="signal-group" aria-labelledby="card-signals-title">
                    <div className="signal-group-heading">
                      <span className="signal-icon card-icon"><CreditCard size={17} /></span>
                      <div><h4 id="card-signals-title">Card behavior</h4><p>Prior activity at assessment time</p></div>
                    </div>
                    <EvidenceRows items={CARD_EVIDENCE} evidence={result.evidence} />
                  </section>
                  <section className="signal-group" aria-labelledby="merchant-signals-title">
                    <div className="signal-group-heading">
                      <span className="signal-icon merchant-icon"><Store size={17} /></span>
                      <div><h4 id="merchant-signals-title">Merchant profile</h4><p>Eligible history, at least 7 days old</p></div>
                    </div>
                    <EvidenceRows items={MERCHANT_EVIDENCE} evidence={result.evidence} />
                    <div className="rate-track" aria-label={`Observed merchant fraud rate ${formatNumber(result.evidence.merchant_prior_fraud_rate_pct ?? 0)} percent`}>
                      <span style={{ width: `${Math.min(100, Math.max(0, result.evidence.merchant_prior_fraud_rate_pct ?? 0))}%` }} />
                    </div>
                  </section>
                  <p className="evidence-caveat">History values are context supplied to the model. They are not feature-importance scores.</p>
                </div>
              )}

              {resultView === 'timing' && (
                <div className="timing-view">
                  <div className="timing-summary">
                    <div>
                      <p className="section-kicker">END TO END</p>
                      <strong>{formatNumber(result.timings_ms.end_to_end ?? 0)} <small>ms</small></strong>
                    </div>
                    <Activity size={19} />
                  </div>
                  <p className="timing-caption">Time spent in each part of this request</p>
                  <div className="timing-list">
                    {TIMING_STAGES.map(([label, key]) => {
                      const duration = result.timings_ms[key] ?? 0
                      return (
                        <div className="timing-item" key={key}>
                          <div className="timing-item-label"><span>{label}</span><strong>{formatNumber(duration)} ms</strong></div>
                          <div className="timing-track"><span style={{ width: `${Math.max(2, (duration / timingMaximum) * 100)}%` }} /></div>
                        </div>
                      )
                    })}
                  </div>
                  <p className="evidence-caveat">Bars are scaled to the slowest stage in this request, not across multiple runs.</p>
                </div>
              )}
            </>
          )}
        </section>
      </div>

      <section className="method-strip" aria-label="Feature stages">
        <div className="method-title">
          <p className="section-kicker">FEATURE BUILD-UP</p>
          <h2>Context, added in stages</h2>
        </div>
        <div className="method-stage">
          <span className="stage-index">A0</span>
          <div><strong>Static profile</strong><span>Amount + customer/card attributes</span></div>
        </div>
        <ArrowRight className="method-arrow" size={17} aria-hidden="true" />
        <div className="method-stage">
          <span className="stage-index">B1</span>
          <div><strong>Card behavior</strong><span>Earlier activity + recency</span></div>
        </div>
        <ArrowRight className="method-arrow" size={17} aria-hidden="true" />
        <div className="method-stage">
          <span className="stage-index">C1</span>
          <div><strong>Merchant context</strong><span>Lagged fraud + card aggregates</span></div>
        </div>
      </section>

      <footer className="app-footer">
        <span>LOCAL WORKBENCH <i /> RDF features <i /> XGBoost</span>
        <span>Not a production decision system</span>
      </footer>
    </main>
  )
}

export default App
