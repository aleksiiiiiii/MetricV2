/**
 * Graphique croisé (`L03-04`).
 *
 * « La vue qui justifie l'app : trois signaux sur le même axe temporel. L'allure seule ne
 * dit rien ; l'allure au-dessus du sommeil et de la charge, ça se lit. » — la charte.
 *
 * ## Sur les échelles multiples
 *
 * La charte superpose une série principale et une série de contexte qui n'ont pas la même
 * unité. C'est un choix discutable en général : deux échelles verticales rendent les
 * croisements arbitraires, et on peut faire dire ce qu'on veut à un tel graphique en
 * changeant une borne.
 *
 * Trois garde-fous, déjà présents dans la charte, rendent la lecture honnête ici :
 *
 * * **un seul axe est gradué**, celui de la série principale — la seconde n'a pas de
 *   graduation, donc n'invite pas à lire sa position ;
 * * **la série de contexte est en pointillé** et volontairement discrète, elle donne une
 *   tendance et non une valeur ;
 * * **l'infobulle donne les chiffres exacts** des deux, avec leur unité : la lecture
 *   précise passe par le curseur, jamais par la géométrie.
 *
 * La troisième série vit dans sa propre bande sous l'axe — c'est un petit multiple, pas
 * une troisième échelle superposée.
 */

import { useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { cx } from '@/lib/cx';

import type { Tone } from './primitives';
import { axisLabels } from './chart-axis';
import styles from './Chart.module.css';

const TONE_VAR: Record<Tone, string> = {
  signal: 'var(--signal)',
  effort: 'var(--effort)',
  load: 'var(--load)',
  recover: 'var(--recover)',
};

// Géométrie reprise de la charte.
const VIEW_W = 720;

/**
 * Hauteurs du viewBox, **selon qu'il y a une bande ou non**.
 *
 * Il n'y en avait qu'une, 320, et un graphique sans bande réservait quand même la place
 * de la bande : près d'un tiers de sa hauteur en blanc sous les étiquettes de dates. Sur
 * un écran large, où le `<svg>` s'étire à toute la largeur de la carte, cela donnait
 * 430 px de haut pour une courbe qui en occupait 250.
 *
 * Le tracé lui-même est aplati de 170 à 150 unités. **La bande, elle, ne bouge pas** :
 * ses deux graduations font 26 unités chacune, et les 54 unités qui les séparent sont
 * exactement ce qu'il leur faut. Un premier essai les avait ramenées à 40 — les deux
 * étiquettes se chevauchaient sur téléphone, ce qui ne s'est vu qu'à l'écran.
 *
 * Les deux hauteurs sont les seules valeurs à changer pour régler la taille encore.
 * Attention : c'est un **rapport**, donc raccourcir pour un écran large raccourcit
 * autant sur téléphone, où la place manque déjà.
 */
const VIEW_H_BAND = 274;
const VIEW_H_PLAIN = 212;
/**
 * Gouttière de gauche : la place réservée aux graduations verticales.
 *
 * La charte donnait 54, calibrés sur des étiquettes de 9 unités. Depuis que le texte des
 * axes est dimensionné pour être **lu** — 26 unités sur téléphone, parce que le SVG est
 * réduit d'un facteur 0,47 —, une graduation coûte bien davantage.
 *
 * **Le chiffre est mesuré, plus estimé.** `getComputedTextLength()` sur les étiquettes
 * réellement rendues donne **17,68 unités par caractère**, letter-spacing compris et à
 * la virgule près sur tous les échantillons. La valeur précédente, 78, prétendait tenir
 * « cinq caractères de chasse fixe » : cinq en demandent 88,4, plus 10 de gouttière, soit
 * 98. Elle n'en tenait pas quatre — « 5:11 » débordait déjà de 2,4 unités —, et une
 * étiquette de six comme « 1,25 m » sortait de 38, soit 17 px de la carte sur un
 * téléphone. `overflow: visible` sur le `<svg>` — voulu, pour l'infobulle — laissait le
 * texte se peindre par-dessus le rembourrage de la carte, vers le bord de la page.
 *
 * 118 tient **six caractères** : 6 × 17,68 = 106, plus les 10 unités qui séparent la
 * graduation de l'axe, et une unité de battement. Au-delà de six, l'étiquette ressortira :
 * une graduation n'a pas à porter son unité, que la légende écrit déjà.
 */
const LEFT = 118;

/**
 * Largeur maximale d'une barre de bande, en unités de viewBox.
 *
 * Sans plafond, quatre sorties donnaient des barres de 143 unités — un quart de la largeur
 * du tracé chacune. Ce ne sont plus des barres mais des dalles, et c'est ce qui rendait le
 * débordement spectaculaire au lieu d'imperceptible.
 */
const MAX_BAND_BAR = 56;

/**
 * Centre d'une barre de bande, ramené dans le tracé.
 *
 * **Les points sont posés sur les bords** : `x(0)` vaut `LEFT` et `x(count - 1)` vaut
 * `RIGHT`. Une barre centrée sur eux déborde donc de la moitié de sa largeur, par-dessus
 * la gouttière des graduations à gauche, et hors du `<svg>` à droite — où `overflow:
 * visible`, voulu pour l'infobulle, la laisse se peindre sur la page.
 *
 * Les barres des extrémités sont **décalées vers l'intérieur** plutôt que rognées. Rogner
 * les aurait laissées à demi-largeur, et une bande sert à comparer des valeurs entre
 * elles : deux barres deux fois plus étroites que les autres se lisent comme deux valeurs
 * plus faibles, alors que c'est la hauteur qui porte la mesure. Le décalage vaut au plus
 * une demi-barre, soit 28 unités sur 588.
 */
function bandCentre(centre: number, width: number): number {
  const half = width / 2;
  return Math.min(Math.max(centre, LEFT + half), RIGHT - half);
}
const RIGHT = 706;
const TOP = 22;
const BOTTOM = 172;
const BAND_TOP = 204;
const BAND_BOTTOM = 258;

export interface Series {
  label: string;
  values: readonly number[];
  tone: Tone;
  unit?: string | undefined;
  format?: ((value: number) => string) | undefined;
}

export interface BandSeries extends Series {
  /** Sous ce seuil, les barres passent en `recover` : le signal qu'on cherche à voir venir. */
  alertBelow?: number | undefined;
  /** Bornes de la bande. Par défaut, les extrêmes de la série. */
  domain?: readonly [number, number] | undefined;
}

export interface ChartProps {
  /** Étiquettes de l'axe horizontal, une par point. */
  labels: readonly string[];
  /** Série graduée, tracée avec son aire dégradée. */
  primary: Series & {
    domain?: readonly [number, number] | undefined;
    ticks?: readonly number[] | undefined;
  };
  /**
   * Séries partageant l'unité et l'échelle de la principale — une tendance lissée, par
   * exemple. Contrairement à `context`, elles se lisent **sur le même axe** : leur
   * position relative a un sens, et les comparer à l'œil est légitime.
   */
  overlays?: readonly (Series & { dashed?: boolean | undefined })[] | undefined;
  /** Série de contexte, à l'unité différente : en pointillé, sans graduation. */
  context?: Series | undefined;
  /** Bande inférieure, en barres. */
  band?: BandSeries | undefined;
  /**
   * **Plancher** du pas entre deux étiquettes d'axe, jamais un plafond.
   *
   * Par défaut `1` : le composant en dessine autant que la place le permet, et calcule
   * lui-même le pas qui les empêche de se toucher. Ne le passer que pour en vouloir
   * *moins* — un appelant ne peut pas en vouloir plus sans risquer le chevauchement,
   * puisqu'il ne connaît ni la largeur d'une étiquette ni l'écart entre deux points.
   */
  labelEvery?: number | undefined;
  note?: ReactNode | undefined;
}

const identity = (value: number) => String(value);

function scale(value: number, [min, max]: readonly [number, number], top: number, bottom: number) {
  const span = max - min || 1;
  return bottom - ((value - min) / span) * (bottom - top);
}

function extent(values: readonly number[]): readonly [number, number] {
  return [Math.min(...values), Math.max(...values)];
}

export function Chart({
  labels,
  primary,
  overlays = [],
  context,
  band,
  labelEvery = 1,
  note,
}: ChartProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [active, setActive] = useState<number | null>(null);

  const count = primary.values.length;
  if (count < 2) return null;

  const x = (index: number) => LEFT + (index * (RIGHT - LEFT)) / (count - 1);

  const primaryDomain = primary.domain ?? extent(primary.values);
  const yPrimary = (value: number) => scale(value, primaryDomain, TOP, BOTTOM);

  const contextDomain = context ? extent(context.values) : ([0, 1] as const);
  const yContext = (value: number) => scale(value, contextDomain, TOP, BOTTOM);

  const bandDomain = band ? (band.domain ?? extent(band.values)) : ([0, 1] as const);

  const formatPrimary = primary.format ?? identity;
  const formatContext = context?.format ?? identity;
  const formatBand = band?.format ?? identity;

  // Largeur d'une barre de bande. **`count - 1` et non `count`** : les points sont posés
  // *sur* les bords du tracé, il y a donc un intervalle de moins que de points. L'ancienne
  // division par `count` donnait des barres plus larges que l'écart réel, ce qui ne se
  // voyait pas à quatorze points et sautait aux yeux à quatre.
  const viewH = band ? VIEW_H_BAND : VIEW_H_PLAIN;
  const bandStep = (RIGHT - LEFT) / Math.max(1, count - 1);
  const bandWidth = Math.max(2, Math.min(bandStep - 4, MAX_BAND_BAR));

  const primaryPoints = primary.values
    .map((value, index) => `${x(index)},${yPrimary(value)}`)
    .join(' ');
  const ticks = primary.ticks ?? [primaryDomain[0], primaryDomain[1]];

  function locate(clientX: number) {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const position = ((clientX - rect.left) / rect.width) * VIEW_W;
    const index = Math.round((position - LEFT) / ((RIGHT - LEFT) / (count - 1)));
    setActive(Math.max(0, Math.min(count - 1, index)));
  }

  const tipLeft = active === null ? 0 : (x(active) / VIEW_W) * 100;
  const tipTop = active === null ? 0 : (yPrimary(primary.values[active] ?? 0) / viewH) * 100;

  return (
    <>
      <div className={styles.legend}>
        <span className={styles.legendItem}>
          <b className={styles.legendLine} style={{ background: TONE_VAR[primary.tone] }} />
          {primary.label}
          {primary.unit !== undefined && ` (${primary.unit})`}
        </span>
        {overlays.map((overlay) => (
          <span className={styles.legendItem} key={overlay.label}>
            <b
              className={styles.legendLine}
              style={
                overlay.dashed
                  ? {
                      background: `repeating-linear-gradient(90deg, ${TONE_VAR[overlay.tone]} 0 4px, transparent 4px 7px)`,
                    }
                  : { background: TONE_VAR[overlay.tone] }
              }
            />
            {overlay.label}
          </span>
        ))}
        {context && (
          <span className={styles.legendItem}>
            <b
              className={styles.legendLine}
              style={{
                background: `repeating-linear-gradient(90deg, ${TONE_VAR[context.tone]} 0 4px, transparent 4px 7px)`,
              }}
            />
            {context.label}
            {context.unit !== undefined && ` (${context.unit})`}
          </span>
        )}
        {band && (
          <span className={styles.legendItem}>
            <b className={styles.legendBlock} style={{ background: TONE_VAR[band.tone] }} />
            {band.label}
            {band.unit !== undefined && ` (${band.unit})`}
          </span>
        )}
      </div>

      <div className={styles.wrap} ref={wrapRef}>
        <svg
          ref={svgRef}
          className={styles.svg}
          viewBox={`0 0 ${VIEW_W} ${viewH}`}
          role="img"
          aria-label={`${primary.label}${context ? `, ${context.label}` : ''}${band ? `, ${band.label}` : ''}`}
          onPointerMove={(event) => {
            locate(event.clientX);
          }}
          onPointerLeave={() => {
            setActive(null);
          }}
        >
          <defs>
            <linearGradient id="chartFade" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={TONE_VAR[primary.tone]} stopOpacity="0.20" />
              <stop offset="100%" stopColor={TONE_VAR[primary.tone]} stopOpacity="0" />
            </linearGradient>
          </defs>

          {/* Grille de fond et graduations — recessives, elles ne doivent jamais
              concurrencer la donnée. */}
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={LEFT}
                x2={RIGHT}
                y1={yPrimary(tick)}
                y2={yPrimary(tick)}
                stroke="var(--line)"
                strokeWidth="1"
              />
              <text x={LEFT - 10} y={yPrimary(tick) + 3} textAnchor="end" className={styles.axis}>
                {formatPrimary(tick)}
              </text>
            </g>
          ))}

          {/* Quelles étiquettes, et par quel bord : `axisLabels` décide, parce qu'il est
              le seul à connaître la géométrie. Les écrans passaient jusqu'ici un
              `labelEvery` estimé sur le nombre de points, et « 28/05 » se peignait
              par-dessus « 11/06 ». La première s'aligne par sa gauche et la dernière par
              sa droite : centrées, elles débordaient d'un côté sur les graduations et de
              l'autre hors du cadre. */}
          {axisLabels(labels, count, x, labelEvery).map(({ index, anchor }) => (
            <text
              key={`${String(index)}-${labels[index] ?? ''}`}
              x={x(index)}
              y={BOTTOM + 24}
              textAnchor={anchor}
              className={styles.axis}
            >
              {labels[index]}
            </text>
          ))}

          <polygon
            points={`${primaryPoints} ${RIGHT},${BOTTOM} ${LEFT},${BOTTOM}`}
            fill="url(#chartFade)"
          />

          {context && (
            <polyline
              points={context.values
                .map((value, index) => `${x(index)},${yContext(value)}`)
                .join(' ')}
              fill="none"
              stroke={TONE_VAR[context.tone]}
              strokeWidth="1.5"
              strokeDasharray="4 3"
              strokeOpacity="0.85"
            />
          )}

          {overlays.map((overlay) => (
            <polyline
              key={overlay.label}
              points={overlay.values
                .map((value, index) => `${x(index)},${yPrimary(value)}`)
                .join(' ')}
              fill="none"
              stroke={TONE_VAR[overlay.tone]}
              strokeWidth="1.5"
              strokeLinejoin="round"
              {...(overlay.dashed ? { strokeDasharray: '4 3' } : {})}
            />
          ))}

          <polyline
            points={primaryPoints}
            fill="none"
            stroke={TONE_VAR[primary.tone]}
            strokeWidth="2"
            strokeLinejoin="round"
          />
          <circle
            cx={x(count - 1)}
            cy={yPrimary(primary.values[count - 1] ?? 0)}
            r="4"
            fill={TONE_VAR[primary.tone]}
          />

          {band && (
            <>
              <text x={LEFT - 10} y={BAND_TOP + 10} textAnchor="end" className={styles.axis}>
                {formatBand(bandDomain[1])}
              </text>
              <text x={LEFT - 10} y={BAND_BOTTOM} textAnchor="end" className={styles.axis}>
                {formatBand(bandDomain[0])}
              </text>
              {band.values.map((value, index) => {
                const span = bandDomain[1] - bandDomain[0] || 1;
                const height = Math.max(
                  3,
                  ((value - bandDomain[0]) / span) * (BAND_BOTTOM - BAND_TOP),
                );
                const alerting = band.alertBelow !== undefined && value < band.alertBelow;
                return (
                  <rect
                    key={index}
                    x={bandCentre(x(index), bandWidth) - bandWidth / 2}
                    y={BAND_BOTTOM - height}
                    width={bandWidth}
                    height={height}
                    rx="2"
                    fill={alerting ? TONE_VAR.recover : TONE_VAR[band.tone]}
                    // 0,55 délavait la barre jusqu'au beige : sur fond blanc, l'ambre
                    // `#a45a00` y ressortait en `#cda473`, à quelques unités de l'argile
                    // qu'il remplaçait. Changer le token ne se voyait donc pas. À 0,85 la
                    // barre porte sa couleur, tout en restant en retrait du tracé.
                    fillOpacity={alerting ? 0.9 : 0.85}
                  />
                );
              })}
              <line
                x1={LEFT}
                x2={RIGHT}
                y1={BAND_BOTTOM}
                y2={BAND_BOTTOM}
                stroke="var(--line)"
                strokeWidth="1"
              />
            </>
          )}

          {active !== null && (
            <>
              <line
                x1={x(active)}
                x2={x(active)}
                y1={TOP - 6}
                y2={band ? BAND_BOTTOM : BOTTOM}
                stroke="var(--ink-mid)"
                strokeWidth="1"
                strokeOpacity="0.5"
                strokeDasharray="3 3"
              />
              <circle
                cx={x(active)}
                cy={yPrimary(primary.values[active] ?? 0)}
                r="4"
                fill="var(--bg)"
                stroke={TONE_VAR[primary.tone]}
                strokeWidth="2"
              />
            </>
          )}
        </svg>

        <div
          className={cx(styles.tip, active !== null && styles.tipVisible)}
          style={{ left: `${tipLeft}%`, top: `${tipTop}%` }}
          role="status"
        >
          {active !== null && (
            <>
              <div className={styles.tipDate}>{labels[active]}</div>
              <span className={styles.tipMark} style={{ color: TONE_VAR[primary.tone] }}>
                ▬
              </span>{' '}
              {formatPrimary(primary.values[active] ?? 0)} {primary.unit}
              {overlays.map((overlay) => (
                <span key={overlay.label}>
                  <br />
                  <span className={styles.tipMark} style={{ color: TONE_VAR[overlay.tone] }}>
                    ▬
                  </span>{' '}
                  {(overlay.format ?? formatPrimary)(overlay.values[active] ?? 0)} {overlay.unit}
                </span>
              ))}
              {context && (
                <>
                  <br />
                  <span className={styles.tipMark} style={{ color: TONE_VAR[context.tone] }}>
                    ▬
                  </span>{' '}
                  {formatContext(context.values[active] ?? 0)} {context.unit}
                </>
              )}
              {band && (
                <>
                  <br />
                  <span
                    className={styles.tipMark}
                    style={{
                      color:
                        band.alertBelow !== undefined &&
                        (band.values[active] ?? 0) < band.alertBelow
                          ? TONE_VAR.recover
                          : TONE_VAR[band.tone],
                    }}
                  >
                    ▬
                  </span>{' '}
                  {formatBand(band.values[active] ?? 0)} {band.unit}
                </>
              )}
            </>
          )}
        </div>
      </div>

      {note !== undefined && <p className={styles.note}>{note}</p>}
    </>
  );
}
