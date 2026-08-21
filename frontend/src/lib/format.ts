/**
 * Formatage des valeurs affichées.
 *
 * Tout ce qui devient du texte lisible passe ici. Deux raisons : la virgule décimale
 * française et les formats de durée sont trop faciles à écrire de six façons
 * différentes, et les tests de ce module valent pour toute l'application.
 *
 * Aucune règle métier ici — seulement de la présentation. Les calculs sont côté
 * serveur (`HEAT-30`).
 */

const LOCALE = 'fr-FR';

/** Nombre à virgule française, sans zéros inutiles. */
export function num(value: number, decimals = 1): string {
  return value.toLocaleString(LOCALE, {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  });
}

/** Entier avec séparateur de milliers insécable. */
export function integer(value: number): string {
  return Math.round(value).toLocaleString(LOCALE);
}

/** Valeur signée, pour un delta : `+1,2` / `−0,4`. */
export function delta(value: number, decimals = 1): string {
  // Signe moins typographique (U+2212) et non trait d'union : il s'aligne sur le plus
  // et sur les chiffres à chasse fixe.
  if (value < 0) return `−${num(Math.abs(value), decimals)}`;
  if (value > 0) return `+${num(value, decimals)}`;
  return num(0, decimals);
}

export function percent(ratio: number, decimals = 0): string {
  return `${num(ratio * 100, decimals)} %`;
}

// ── Durées ────────────────────────────────────────────

/**
 * Durée en minutes décimales → `mm:ss` ou `h:mm:ss`.
 *
 * Le passage à trois segments se fait à partir d'une heure, comme dans la charte
 * (« 44:12 » pour une sortie courte, « 1:18:44 » pour une longue).
 */
export function duration(minutes: number): string {
  const total = Math.round(minutes * 60);
  const hours = Math.floor(total / 3600);
  const mins = Math.floor((total % 3600) / 60);
  const secs = total % 60;

  const pad = (n: number) => String(n).padStart(2, '0');
  return hours > 0 ? `${hours}:${pad(mins)}:${pad(secs)}` : `${mins}:${pad(secs)}`;
}

/** Durée en minutes → `7 h 20`, pour le sommeil et les volumes hebdomadaires. */
export function hoursMinutes(minutes: number): string {
  const total = Math.round(minutes);
  const hours = Math.floor(total / 60);
  const mins = total % 60;

  if (hours === 0) return `${mins} min`;
  if (mins === 0) return `${hours} h`;
  return `${hours} h ${String(mins).padStart(2, '0')}`;
}

/** Allure en minutes par kilomètre → `5:16`. */
export function pace(minutesPerKm: number): string {
  return duration(minutesPerKm);
}

/** Allure dérivée d'une distance et d'une durée. `null` si indéterminable. */
export function paceOf(distanceKm: number, minutes: number): string | null {
  if (distanceKm <= 0 || minutes <= 0) return null;
  return pace(minutes / distanceKm);
}

// ── Unités ────────────────────────────────────────────

export function km(value: number): string {
  return `${num(value, 2)} km`;
}

export function kg(value: number): string {
  return `${num(value, 1)} kg`;
}

/** Volume en millilitres, exprimé en litres au-delà du litre. */
export function volume(milliliters: number): string {
  if (milliliters < 1000) return `${integer(milliliters)} ml`;
  return `${num(milliliters / 1000, 2)} L`;
}

// ── Dates ─────────────────────────────────────────────

function asDate(value: Date | string): Date {
  return value instanceof Date ? value : new Date(value);
}

/** `26/07`, pour les colonnes de tableau. */
export function dayMonth(value: Date | string): string {
  return asDate(value).toLocaleDateString(LOCALE, { day: '2-digit', month: '2-digit' });
}

/**
 * `26`, le quantième seul.
 *
 * Pour une bande de sept jours consécutifs, où le mois est le même six fois sur sept et
 * n'apprend rien. Ce n'est pas qu'une question de goût : `26/07` demande 36 px en chasse
 * fixe, et sept cases de 42 px réclament **330 px là où un téléphone de 360 en offre
 * 294** — la page se mettait à défiler horizontalement. Mesuré, à la largeur que l'audit
 * ne regarde pas.
 */
export function dayOfMonth(value: Date | string): string {
  return asDate(value).toLocaleDateString(LOCALE, { day: '2-digit' });
}

/** `26/07/2026`. */
export function shortDate(value: Date | string): string {
  return asDate(value).toLocaleDateString(LOCALE, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

/** `samedi 26 juillet`, pour un titre de journée. */
export function longDate(value: Date | string): string {
  return asDate(value).toLocaleDateString(LOCALE, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });
}

/** `JUL`, en-tête de mois d'une heatmap. */
export function monthAbbrev(value: Date | string): string {
  return asDate(value)
    .toLocaleDateString(LOCALE, { month: 'short' })
    .replace('.', '')
    .toUpperCase();
}

/** `21:00`, heure locale. */
export function time(value: Date | string): string {
  return asDate(value).toLocaleTimeString(LOCALE, { hour: '2-digit', minute: '2-digit' });
}

/**
 * Écart en jours par rapport à aujourd'hui, en clair.
 *
 * Utilisé pour les libellés d'axe et les rappels de dernière performance. Les bornes
 * sont volontairement grossières : au-delà d'une semaine, la date exacte est plus utile
 * qu'un « il y a 12 jours ».
 */
export function relativeDay(value: Date | string): string {
  const target = asDate(value);
  const today = new Date();
  const days = Math.round(
    (Date.UTC(target.getFullYear(), target.getMonth(), target.getDate()) -
      Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())) /
      86_400_000,
  );

  if (days === 0) return "aujourd'hui";
  if (days === -1) return 'hier';
  if (days === 1) return 'demain';
  if (days > 1 && days <= 7) return `dans ${days} jours`;
  if (days < -1 && days >= -7) return `il y a ${Math.abs(days)} jours`;
  return shortDate(target);
}

/** Date au format `AAAA-MM-JJ` en heure **locale**, pour les paramètres d'API. */
export function isoDay(value: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
}

/**
 * Accorde un nom au nombre qui le précède.
 *
 * Douze endroits écrivaient « 1 séance(s) », « 3 groupe(s) travaillé(s) ». Le gabarit se
 * lit comme un texte qu'on a oublié de finir, et il apparaît précisément là où le compte
 * vaut un — c'est-à-dire au premier jour d'usage, quand l'application se juge.
 *
 * Zéro prend le singulier : « 0 séance », comme en français.
 */
export function plural(count: number, singular: string, many?: string): string {
  return count > 1 ? (many ?? `${singular}s`) : singular;
}
