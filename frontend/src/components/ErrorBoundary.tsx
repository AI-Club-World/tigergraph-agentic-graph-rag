import { Component, type ReactNode } from 'react'

interface State {
  error: Error | null
}

/** One screen failing to render (e.g. an imported run with a missing field)
 *  shows its error in place instead of blanking the whole app. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null })
  }

  render() {
    if (this.state.error) {
      return (
        <div className="notice error-box pad" role="alert">
          <span className="notice-text">
            This screen could not be shown: {this.state.error.message}. Other screens still work.
          </span>
        </div>
      )
    }
    return this.props.children
  }
}
