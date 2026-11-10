/** Product mark: an isometric block (inline SVG, follows the text colour). */
export function Logo({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M12 2.5 21 7.5v9L12 21.5 3 16.5v-9L12 2.5Z" fill="var(--accent)" />
      <path d="M12 12 21 7.5v9L12 21.5V12Z" fill="#000" fillOpacity="0.22" />
      <path d="M12 12 3 7.5l9-5 9 5-9 4.5Z" fill="#fff" fillOpacity="0.28" />
      <path d="M9 14.2v3.4l-2.6-1.4v-3.4L9 14.2Z" fill="#fff" fillOpacity="0.75" />
    </svg>
  );
}
