import { config } from '../config'
import { post } from './http'
import type { R2Answer } from '../types'

/** POST /r2/ask: one question to the Round-2 agent; the record carries its trace.
 *  Errors (503 TigerGraph/LLM unavailable, 500 agent failure) throw ApiError — never a fake answer. */
export async function askRound2(question: string): Promise<R2Answer> {
  if (config.useMockApi) {
    throw new Error('The Round 2 agent needs the live backend (VITE_USE_MOCK_API is on).')
  }
  return post<R2Answer>('/r2/ask', { question, backend: 'tigergraph' })
}
