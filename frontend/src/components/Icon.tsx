/**
 * Inline stroke icons for the Search and Build screens. Kept local (no icon
 * font, no dependency) so they render offline and inherit `currentColor`.
 */
const PATHS = {
  terminal: 'M4 17l6-5-6-5M12 19h8',
  play: 'M7 4.5v15l12-7.5z',
  scan: 'M3 7V4h3M21 7V4h-3M3 17v3h3M21 17v3h-3M10.5 15a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zM14 14l3.5 3.5',
  checkCircle: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM8.5 12.2l2.4 2.4 4.6-4.9',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  sparkle: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.7 1.8 1.8.7-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z',
  warning: 'M12 4L2.5 20h19zM12 10v4.5M12 17.2v.3',
  flag: 'M5 21V4M5 4h11l-2 4 2 4H5',
  fork: 'M6 3v6a6 6 0 0 0 6 6h0a6 6 0 0 1 6 6M18 3v4M15 5.5L18 3l3 2.5',
  tokens: 'M8 4H5v16h3M16 4h3v16h-3',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
  layers: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5',
  link: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',
  tree: 'M4 4h6v5H4zM14 15h6v5h-6zM14 4h6v5h-6zM7 9v8.5h7M10 6.5h4',
  verified: 'M12 2.5l2.4 1.8 3-.1.9 2.9 2.4 1.8-1 2.8 1 2.8-2.4 1.8-.9 2.9-3-.1L12 21.5l-2.4-1.8-3 .1-.9-2.9-2.4-1.8 1-2.8-1-2.8 2.4-1.8.9-2.9 3 .1zM8.5 12l2.4 2.4 4.6-4.8',
  restart: 'M4 12a8 8 0 1 0 2.3-5.7M4 4v4.5h4.5',
  sync: 'M20 12a8 8 0 0 1-14.3 4.9M4 12a8 8 0 0 1 14.3-4.9M18.5 3v4.2h-4.2M5.5 21v-4.2h4.2',
  arrowRight: 'M5 12h14M13 6l6 6-6 6',
  grid: 'M4 4h16v16H4zM4 12h16M12 4v16',
  doc: 'M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7',
  database: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
  hub: 'M12 14.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM12 3v6.5M12 14.5V21M4.2 7.5l5.6 3.2M14.2 13.3l5.6 3.2M4.2 16.5l5.6-3.2M14.2 10.7l5.6-3.2',
  bot: 'M5 8h14v11H5zM12 8V4.5M9.5 13v1M14.5 13v1M2.5 12.5v3M21.5 12.5v3M12 4.5h.01',
  chip: 'M7 7h10v10H7zM10 10h4v4h-4zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4',
  chevronRight: 'M9 5l7 7-7 7',
  gauge: 'M4.5 18a9 9 0 1 1 15 0M12 13l4-4.5',
  circle: 'M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16z',
  share: 'M18 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8.6 13.5l6.8 4M15.4 6.5l-6.8 4',
} as const

export type IconName = keyof typeof PATHS

interface Props {
  name: IconName
  size?: number
  className?: string
}

export function Icon({ name, size = 16, className }: Props) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className ? `icon ${className}` : 'icon'}
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
