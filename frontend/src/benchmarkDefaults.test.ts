import { describe, expect, it } from 'vitest'
import { defaultDataset } from './benchmarkDefaults'

describe('defaultDataset', () => {
  it('never defaults to the hidden set, although it sorts first', () => {
    expect(defaultDataset(['eval_hidden', 'eval_public'])).toBe('eval_public')
    expect(defaultDataset(['eval_hidden', 'my_questions'])).toBe('my_questions')
    expect(defaultDataset(['holdout_v2', 'eval_hidden'])).toBe('holdout_v2')
    expect(defaultDataset([])).toBe('')
  })
})
