import type { PipelineId } from '../types'

/**
 * Chart colours reference the theme tokens rather than literals, so swatches,
 * bars and scatter points follow the light/dark switch. `var()` only resolves
 * in CSS, so SVG shapes must set these via `style`, not `fill`/`stroke`.
 */
export const PIPELINE_COLORS: Record<PipelineId, string> = {
  rag: 'var(--rag)',
  graphrag: 'var(--graphrag)',
  agentic_graphrag: 'var(--agentic)',
}
