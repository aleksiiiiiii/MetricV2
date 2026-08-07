import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router';

import { Badge, Button, Card, Empty, Heatmap, PageHead, Rule } from '@/components/ui';
import { heatmapApi, type DayEntry, type Grid } from '@/features/heatmap/api';
import { duration, integer, isoDay, km, longDate, num, percent } from '@/lib/format';
import { keys } from '@/lib/query';

import styles from './Assiduity.module.css';

/**
 * Écran Assiduité (`L11-06` → `L11-09`).
 *
 * Neuf grilles, **un seul appel réseau** (`HEAT-25`). Les demander une par une coûterait
 * neuf allers-retours au client et autant de relectures au serveur, pour des grilles qui
 * partagent leurs fichiers sources.
 *
 * ## Ce que l'écran ne fait pas
 *
 * Il ne calcule rien. Ni état, ni niveau, ni série, ni taux de respect (`HEAT-30`). Il ne
 * décide pas non plus qu'une piste est hebdomadaire : il regarde si le serveur a renvoyé
 * des `weeks`. La différence est de taille — lire `cadence.type === 'per_week'` reviendrait
 * à recoder la règle ici, et à la voir diverger le jour où une sixième cadence
 * apparaîtrait.
 *
 * ## Ce qu'il faut voir en trois secondes
 *
 * Qu'une piste tenue est verte et qu'une piste non quotidienne est **grise et non rouge**.
 * Une grille « deux fois par semaine » est `off` cinq jours sur sept ; la lire comme un
 * échec annulerait tout le travail du moteur.
 */

/** Ton de la charte porté par chaque piste, en composantes RVB (`L11-12`). */
const ACCENT_RGB: Record<string, string> = {
  signal: 'var(--signal-rgb)',
  effort: 'var(--effort-rgb)',
  load: 'var(--load-rgb)',
  recover: 'var(--recover-rgb)',
};

const DEFAULT_ACCENT = 'var(--signal-rgb)';

function accentOf(accent: string): string {
  return ACCENT_RGB[accent] ?? DEFAULT_ACCENT;
}

/**
 * Cumul d'une piste, dans son unité.
 *
 * Le formatage seul est ici ; la valeur vient du serveur. `HEAT-03` veut qu'une source ne
 * rende qu'un nombre par jour — l'unité dit comment l'écrire, pas comment le calculer.
 */
function totalOf(grid: Grid): string {
  const { total } = grid.stats;
  switch (grid.track.unit) {
    case 'km':
      return km(total);
    case 'ml':
      return total >= 1000 ? `${num(total / 1000, 1)} L` : `${integer(total)} ml`;
    case 'min':
      return duration(total);
    default:
      return `${integer(total)} ${grid.track.unit}${total > 1 ? 's' : ''}`;
  }
}

function streakLabel(days: number): string {
  if (days === 0) return '—';
  return days === 1 ? '1 jour' : `${integer(days)} jours`;
}

/** Chiffres d'une piste (`L11-09`, `HEAT-26`). */
function TrackStats({ grid }: { grid: Grid }) {
  const { stats } = grid;

  return (
    <div className={styles.stats}>
      <div className={styles.stat}>
        <span className={styles.statKey}>Respect</span>
        {/* `null` et zéro sont deux choses différentes : sans attente, il n'y a pas de
            taux, et afficher « 0 % » se lirait comme un échec (`HEAT-07`). */}
        <span className="num">{stats.compliance === null ? '—' : percent(stats.compliance)}</span>
        <span className={styles.statHint}>
          {stats.expected_days === 0
            ? 'rien n’était attendu'
            : `${integer(stats.validated_days)} / ${integer(stats.expected_days)}`}
        </span>
      </div>

      <div className={styles.stat}>
        <span className={styles.statKey}>Série en cours</span>
        <span className="num">{streakLabel(stats.current_streak)}</span>
        <span className={styles.statHint}>record {streakLabel(stats.longest_streak)}</span>
      </div>

      <div className={styles.stat}>
        <span className={styles.statKey}>Total</span>
        <span className="num">{totalOf(grid)}</span>
        <span className={styles.statHint}>
          {stats.best_day === null || stats.best_value === null
            ? 'sur la plage affichée'
            : `record le ${longDate(stats.best_day)}`}
        </span>
      </div>
    </div>
  );
}

/** Une ligne de saisie du tiroir (`HEAT-29`). Le serveur envoie des nombres, on compose. */
function EntryLine({ entry }: { entry: DayEntry }) {
  const parts: string[] = [];

  if (entry.sets !== null && entry.reps !== null) {
    parts.push(`${entry.sets} × ${entry.reps}`);
  }
  if (entry.weight_kg !== null && entry.weight_kg > 0) {
    parts.push(`${num(entry.weight_kg)} kg`);
  }
  // `weight_kg = 0` signifie poids du corps (`ACT-07`) : c'est une valeur, pas un vide.
  if (entry.weight_kg === 0) parts.push('poids du corps');
  if (entry.distance_km !== null) parts.push(km(entry.distance_km));
  if (entry.duration_min !== null) parts.push(duration(entry.duration_min));
  if (entry.pace_min_km !== null) parts.push(`${duration(entry.pace_min_km)} /km`);
  if (entry.dose !== null) parts.push(`${num(entry.dose)} ${entry.dose_unit ?? ''}`.trim());

  return (
    <li className={styles.entry}>
      <div className={styles.entryHead}>
        <span className={styles.entryLabel}>{entry.label}</span>
        <span className="num">
          {num(entry.value)} {entry.unit}
        </span>
      </div>
      {parts.length > 0 && <div className={styles.entryDetail}>{parts.join(' · ')}</div>}
      {entry.note !== null && entry.note !== '' && (
        <div className={styles.entryNote}>{entry.note}</div>
      )}
    </li>
  );
}

/** Tiroir de détail (`L11-08`, `HEAT-29`). */
function DayDrawer({
  trackId,
  day,
  onClose,
}: {
  trackId: string;
  day: string;
  onClose: () => void;
}) {
  const { data, isPending, error } = useQuery({
    queryKey: keys.heatmap.day(trackId, day),
    queryFn: () => heatmapApi.day(trackId, day),
  });

  return (
    <aside className={styles.drawer} role="dialog" aria-label={`Détail du ${longDate(day)}`}>
      <div className="spread">
        <div>
          <p className="eyebrow">{data?.track.label ?? 'Détail'}</p>
          <h2 className={styles.drawerTitle}>{longDate(day)}</h2>
        </div>
        <Button variant="quiet" onClick={onClose}>
          Fermer
        </Button>
      </div>

      {isPending && <p className={styles.muted}>chargement…</p>}

      {error && (
        <p className={styles.muted} role="alert">
          {error instanceof Error ? error.message : 'Détail indisponible.'}
        </p>
      )}

      {data && (
        <>
          <div className={styles.drawerSummary}>
            <span className="num">
              {num(data.day.value)} {data.track.unit}
            </span>
            <Badge tone={data.day.state === 'missed' ? 'recover' : 'effort'}>
              {data.day.state === 'missed'
                ? 'manqué'
                : data.day.state === 'off'
                  ? 'rien attendu'
                  : data.day.state === 'bonus'
                    ? 'bonus'
                    : 'validé'}
            </Badge>
          </div>

          {data.entries.length === 0 ? (
            <Empty title="Rien ce jour-là">
              Aucune saisie n’alimente cette piste pour cette journée.
            </Empty>
          ) : (
            <ul className={styles.entries}>
              {data.entries.map((entry, index) => (
                <EntryLine entry={entry} key={index} />
              ))}
            </ul>
          )}
        </>
      )}
    </aside>
  );
}

function TrackCard({
  grid,
  today,
  onSelectDay,
}: {
  grid: Grid;
  today: string;
  /** Le jour choisi, et lui seul : la carte n'a pas à propager une cellule entière. */
  onSelectDay: (date: string) => void;
}) {
  return (
    <Card className={styles.track}>
      <div className="spread">
        <div>
          <h2 className={styles.trackName}>{grid.track.label}</h2>
          {/* Le libellé de la cadence vient du serveur : le reconstruire ici serait
              réimplémenter la grammaire des cadences (`HEAT-30`). */}
          <p className={styles.cadence}>{grid.cadence.label}</p>
        </div>
        {grid.weeks !== null && <Badge tone="load">au rythme hebdomadaire</Badge>}
      </div>

      <TrackStats grid={grid} />

      <Heatmap
        days={grid.days}
        weeks={grid.weeks}
        accentRgb={accentOf(grid.track.accent)}
        unit={grid.track.unit}
        label={`Assiduité — ${grid.track.label}`}
        today={today}
        onSelectDay={(day) => {
          onSelectDay(day.date);
        }}
      />

      {grid.weeks !== null && (
        <p className={styles.footnote}>
          Sur cette piste, un jour sans séance n’est pas un échec : c’est la <b>semaine</b> qui est
          jugée, et la bande sous la grille en porte le verdict.
        </p>
      )}
    </Card>
  );
}

export function Assiduity() {
  const [opened, setOpened] = useState<{ trackId: string; day: string } | null>(null);
  const today = isoDay(new Date());

  const { data, isPending, error } = useQuery({
    queryKey: keys.heatmap.screen(),
    queryFn: () => heatmapApi.grids(),
  });

  if (isPending) {
    return (
      <div className="wrap">
        <p className={styles.muted}>chargement…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="wrap">
        <Empty title="Assiduité indisponible">
          {error instanceof Error ? error.message : 'Le serveur n’a pas répondu.'}
        </Empty>
      </div>
    );
  }

  return (
    <div className="wrap">
      <PageHead
        eyebrow="Assiduité"
        title="Ce que tu tiens"
        actions={
          <Link to="/reglages" className={styles.settingsLink}>
            Régler les pistes, les cadences et les seuils
          </Link>
        }
      >
        Une heatmap ne mesure pas l’activité, elle mesure le respect d’un engagement. Un jour vide
        n’est un échec que si quelque chose était attendu ce jour-là — c’est pourquoi le gris y est
        la couleur la plus fréquente, et qu’il ne veut rien dire de mauvais.
      </PageHead>

      {data.grids.length === 0 ? (
        <Empty title="Aucune piste active">
          Toutes les pistes sont désactivées. Réactive-en une depuis les réglages pour retrouver ta
          grille — l’historique n’a pas bougé.
        </Empty>
      ) : (
        <>
          <Rule>{`${data.range.from} → ${data.range.to}`}</Rule>

          <div className={styles.tracks}>
            {data.grids.map((grid) => (
              <TrackCard
                key={grid.track.id}
                grid={grid}
                today={today}
                onSelectDay={(date) => {
                  setOpened({ trackId: grid.track.id, day: date });
                }}
              />
            ))}
          </div>
        </>
      )}

      {opened && (
        <DayDrawer
          trackId={opened.trackId}
          day={opened.day}
          onClose={() => {
            setOpened(null);
          }}
        />
      )}
    </div>
  );
}
