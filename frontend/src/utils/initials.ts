/**
 * "Aman" -> "A". "Aman Kulwal" -> "AK". "Aman Yogesh Kulwal" -> "AK" -
 * first word's first letter plus LAST word's first letter, middle
 * name(s) skipped entirely, matching how initials normally work for a
 * full name rather than trying to represent every word given.
 */
export function getInitials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "";
  if (words.length === 1) return words[0][0].toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}
