/** The set a new run defaults to: the public set, else any set that is not a
 *  hidden/holdout set. The hidden set is run once, deliberately; the list
 *  sorts it first, so an alphabetical default made one click spend it. */
export function defaultDataset(names: string[]): string {
  return (
    names.find((n) => n === 'eval_public') ??
    names.find((n) => !/hidden|holdout/i.test(n)) ??
    names[0] ??
    ''
  )
}
