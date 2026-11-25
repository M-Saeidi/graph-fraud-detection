export interface ScoreRequest {
  amount: number
  client_id: number
  card_id: number
  merchant_id: number
  transaction_time: string
}

export interface ScoreResponse {
  prediction: boolean
  fraud_confidence: number
  non_fraud_confidence: number
  evidence: Record<string, number>
  timings_ms: Record<string, number>
  model_parity: 'not_exactly_equivalent_to_ai_studio'
}

export interface HealthResponse {
  status: string
  model_parity: ScoreResponse['model_parity']
}

export type DemoDefaults = ScoreRequest

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`

    try {
      const body: unknown = await response.json()
      if (
        typeof body === 'object'
        && body !== null
        && 'detail' in body
        && typeof body.detail === 'string'
      ) {
        message = body.detail
      }
    } catch {
      // Preserve the generic status message for non-JSON errors.
    }

    throw new Error(message)
  }

  return response.json() as Promise<T>
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`)
  return parseResponse<HealthResponse>(response)
}

export async function getDemoDefaults(): Promise<DemoDefaults> {
  const response = await fetch(`${API_BASE_URL}/demo-defaults`)
  return parseResponse<DemoDefaults>(response)
}

export async function scoreTransaction(request: ScoreRequest): Promise<ScoreResponse> {
  const response = await fetch(`${API_BASE_URL}/score`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })

  return parseResponse<ScoreResponse>(response)
}
