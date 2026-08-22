/**
 * Nuage de points — une sortie, un point (`ACT-20`).
 *
 * ## Pourquoi ce composant existe, et ce qu'il remplace
 *
 * La page « Toutes tes courses » traçait une **courbe d'allure au fil du temps**. Elle
 * portait trois lignes d'avertissement expliquant pourquoi il ne fallait pas s'y fier :
 * une allure de 5'30" sur 15 km vaut mieux qu'une de 5'10" sur 3 km, si bien que la courbe
 * montrait surtout quelles distances avaient été courues. Un graphique qui a besoin d'un
 * paragraphe pour dire de s'en méfier est un mauvais graphique.
 *
 * Elle avait un second défaut, plus discret : elle **reliait** des sorties séparées de
 * plusieurs semaines. Un trait entre deux points dit « ceci est devenu cela », alors que
 * rien ne s'est passé entre les deux.
 *
 * Le nuage résout les deux d'un coup, en portant la distance sur l'abscisse plutôt que de
 * la reléguer en note : **on lit l'allure à distance comparable**. Deux points à la même
 * abscisse sont deux sorties comparables, et celui du haut est le meilleur. Il n'y a plus
 * rien à avertir — la réserve est devenue l'axe.
 *
 * ## L'axe des allures est retourné
 *
 * Comme partout où ce dépôt trace une allure : une allure basse est une course rapide, et
 * une courbe qui descend quand on accélère se lit à l'envers. Le plus lent est en bas.
 *
 * ## Ce que la fraîcheur dit
 *
 * Les points pâlissent avec l'âge. La progression n'est donc pas une pente à interpréter
 * mais quelque chose qui **se voit** : si les points francs sont au-dessus des pâles à
 * abscisse voisine, on court plus vite qu'avant sur les mêmes distances.
 *
 * ## Aucun calcul métier ici
 *
 * Les deux domaines arrivent du serveur, retournés comme il faut. L'opacité se déduit du
 * rang dans une liste déjà ordonnée par lui : c'est une décision d'affichage, pas une
 * mesure.
 */

import type { ReactNode } from 'react';
import { useId, useState } from 'react';

import { cx } from '@/lib/cx';

import type { Tone } from './primitives';
import styles from './Scatter.module.css';

const TONE_VAR: Record<Tone, string> = {
  signal: 'var(--signal)',
  effort: 'var(--effort)',
  load: 'var(--load)',
  recover: 'var(--recover)',
};

const VIEW_W = 720;
const VIEW_H = 300;

/** Même gouttière que `Chart`, pour la même raison : six caractères de graduation. */
const LEFT = 118;
const RIGHT = 700;
const TOP = 24;
const BOTTOM = 236;

/** Rayon d'un point. 9 unités de viewBox font ~9 px sur téléphone : visible, pas lourd. */
const DOT = 9;

/** Opacité du point le plus ancien. En dessous, il disparaît sur fond clair. */
const FADE_FLOOR = 0.28;

/**
 * Retrait du tracé, pour qu'un point posé sur une borne reste **entier**.
 *
 * Sans lui, la sortie la plus courte a son centre exactement sur `LEFT` : la moitié du
 * disque déborde dans la gouttière des graduations, et la plus rapide se fait couper par
 * la ligne du haut. Un nuage a besoin de cette marge là où une courbe n'en veut pas —
 * une courbe touche ses bords par construction, un point a un rayon.
 */
const PAD = DOT + 5;

export interface ScatterPoint {
  /** Abscisse — la distance, dans l'unité du domaine. */
  x: number;
  /** Ordonnée — l'allure. */
  y: number;
  /** Ce que l'infobulle écrit en tête : la date de la sortie. */
  label: string;
  /** Détail sous le libellé — « 8,14 km · 5:02 /km ». */
  detail: string;
}

export interface ScatterProps {
  /** Les points, **du plus ancien au plus récent** : c'est cet ordre qui fait la fraîcheur. */
  points: readonly ScatterPoint[];
  /** Bornes de l'abscisse, servies par le serveur. Le plus petit d'abord. */
  xDomain: readonly [number, number];
  /** Bornes de l'ordonnée, servies retournées : **le plus lent d'abord**. */
  yDomain: readonly [number, number];
  xLabel: string;
  yLabel: string;
  formatX: (value: number) => string;
  formatY: (value: number) => string;
  tone?: Tone | undefined;
  note?: ReactNode | undefined;
}

export function Scatter({
  points,
  xDomain,
  yDomain,
  xLabel,
  yLabel,
  formatX,
  formatY,
  tone = 'signal',
  note,
}: ScatterProps) {
  const [active, setActive] = useState<number | null>(null);
  const titleId = useId();

  // Un domaine plat — toutes les sorties à la même distance — donnerait une division par
  // zéro et empilerait les points sur un bord. On l'ouvre, ce qui déplace l'échelle et
  // non les points.
  const xSpan = xDomain[1] - xDomain[0] || 1;
  const ySpan = yDomain[1] - yDomain[0] || 1;

  // Le retrait s'applique aux **deux** bornes : les graduations suivent, si bien qu'un
  // point extrême reste posé sur sa ligne, entier, au lieu d'être coupé par elle.
  const px = (value: number) =>
    LEFT + PAD + ((value - xDomain[0]) / xSpan) * (RIGHT - LEFT - 2 * PAD);
  const py = (value: number) =>
    BOTTOM - PAD - ((value - yDomain[0]) / ySpan) * (BOTTOM - TOP - 2 * PAD);

  const colour = TONE_VAR[tone];
  const last = points.length - 1;

  return (
    <>
      <p className={styles.legend}>
        <span className={styles.legendDot} style={{ background: colour }} />
        {yLabel} <span className={styles.legendSep}>selon</span> {xLabel}
      </p>

      <div className={styles.wrap}>
        <svg
          className={styles.svg}
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          role="img"
          aria-labelledby={titleId}
        >
          <title id={titleId}>
            {points.length} sorties, {yLabel.toLowerCase()} selon {xLabel.toLowerCase()}
          </title>

          {/* Deux graduations par axe, pas davantage : le nuage porte l'information, la
              grille ne fait que la situer. */}
          {[yDomain[0], yDomain[1]].map((value) => (
            <g key={`y${String(value)}`}>
              <line
                x1={LEFT}
                x2={RIGHT}
                y1={py(value)}
                y2={py(value)}
                stroke="var(--line)"
                strokeWidth="1"
              />
              <text x={LEFT - 10} y={py(value) + 8} textAnchor="end" className={styles.axis}>
                {formatY(value)}
              </text>
            </g>
          ))}

          {[xDomain[0], xDomain[1]].map((value, index) => (
            <text
              key={`x${String(value)}`}
              x={px(value)}
              y={BOTTOM + 32}
              textAnchor={index === 0 ? 'start' : 'end'}
              className={styles.axis}
            >
              {formatX(value)}
            </text>
          ))}

          {points.map((point, index) => {
            // Le plus ancien au plancher, le plus récent à plein. Sur une seule sortie,
            // `last` vaut 0 : elle est récente, donc pleine.
            const freshness = last === 0 ? 1 : index / last;
            const opacity = FADE_FLOOR + (1 - FADE_FLOOR) * freshness;
            const newest = index === last;
            return (
              <g key={`${point.label}-${String(index)}`}>
                {newest && (
                  // La dernière sortie porte un anneau : c'est celle qu'on vient de
                  // courir, et la chercher dans un nuage n'a aucun intérêt.
                  <circle
                    cx={px(point.x)}
                    cy={py(point.y)}
                    r={DOT + 6}
                    fill="none"
                    stroke={colour}
                    strokeWidth="2"
                    opacity="0.45"
                  />
                )}
                <circle
                  cx={px(point.x)}
                  cy={py(point.y)}
                  r={active === index ? DOT + 3 : DOT}
                  fill={colour}
                  opacity={opacity}
                  className={styles.dot}
                />
                {/* La cible de pointage est bien plus large que le point : au pouce, un
                    disque de 9 unités est intouchable. Elle est transparente et ne se
                    voit pas — elle ne fait qu'écouter. */}
                <circle
                  cx={px(point.x)}
                  cy={py(point.y)}
                  r={26}
                  fill="transparent"
                  onPointerEnter={() => {
                    setActive(index);
                  }}
                  onPointerDown={() => {
                    setActive(index);
                  }}
                  onPointerLeave={() => {
                    setActive(null);
                  }}
                />
              </g>
            );
          })}
        </svg>

        {active !== null && points[active] && (
          <div
            className={cx(styles.tip, px(points[active].x) > VIEW_W / 2 && styles.tipLeft)}
            style={{
              left: `${String((px(points[active].x) / VIEW_W) * 100)}%`,
              top: `${String((py(points[active].y) / VIEW_H) * 100)}%`,
            }}
          >
            <b className={styles.tipDate}>{points[active].label}</b>
            {points[active].detail}
          </div>
        )}
      </div>

      {note !== undefined && <p className={styles.note}>{note}</p>}
    </>
  );
}
