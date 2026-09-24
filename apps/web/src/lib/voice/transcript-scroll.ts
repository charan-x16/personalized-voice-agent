/** A little tolerance allows for wrapped lines and fractional browser scroll positions. */
export function isNearTranscriptBottom(scrollTop: number, scrollHeight: number, clientHeight: number) {
  return scrollHeight - scrollTop - clientHeight <= 48;
}
