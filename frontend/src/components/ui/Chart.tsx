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
import styles from './Chart.module.css';

const TONE_VAR: Record<Tone, string> = {
  signal: 'var(--signal)',
  effort: 'var(--effort)',
  load: 'var(--load)',
  recover: 'var(--recover)',
};

// Géométrie reprise de la charte.
const VIEW_W = 720;
const VIEW_H = 320;
const LEFT = 54;
const RIGHT = 706;
const TOP = 26;
const BOTTOM = 196;
const BAND_TOP = 228;
const BAND_BOTTOM = 282;

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
  /** Une étiquette d'axe sur `labelEvery` points, pour ne pas les entasser. */
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
  labelEvery = 6,
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
  const tipTop = active === null ? 0 : (yPrimary(primary.values[active] ?? 0) / VIEW_H) * 100;

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
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
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

          {labels.map((label, index) =>
            index % labelEvery === 0 ? (
              <text
                key={label}
                x={x(index)}
                y={BOTTOM + 16}
                textAnchor="middle"
                className={styles.axis}
              >
                {label}
              </text>
            ) : null,
          )}

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
                const width = (RIGHT - LEFT) / count - 4;
                const alerting = band.alertBelow !== undefined && value < band.alertBelow;
                return (
                  <rect
                    key={index}
                    x={x(index) - width / 2}
                    y={BAND_BOTTOM - height}
                    width={width}
                    height={height}
                    rx="2"
                    fill={alerting ? TONE_VAR.recover : TONE_VAR[band.tone]}
                    fillOpacity={alerting ? 0.9 : 0.55}
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
