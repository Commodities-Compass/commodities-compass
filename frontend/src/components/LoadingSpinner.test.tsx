import { describe, it, expect } from 'vitest'
import { render } from '../test/test-utils'
import LoadingSpinner from './LoadingSpinner'

describe('LoadingSpinner', () => {
  it('renders the spinner', () => {
    const { container } = render(<LoadingSpinner />)
    const spinner = container.querySelector('.animate-spin')
    expect(spinner).toBeInTheDocument()
  })
})
